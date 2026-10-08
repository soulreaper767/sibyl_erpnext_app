"""Bring documents created before customer-wise naming onto the new names.

Every document covered by a Sibyl Naming Rule is renumbered per series key
(prefix + customer ID [+ date tokens]) in chronological order, so a
customer's oldest Sales Order becomes SO-ACME-0001. Amendments follow their
original as <new original name>-1, -2 ... (Frappe's own amend convention).

Renames go through frappe.rename_doc, which rewrites every Link / Dynamic
Link pointing at the document (GL / stock / payment ledgers, child rows,
references on other transactions, comments, attachments). Text fields such
as remarks that merely mention an old number are not touched.

Idempotent: a second run finds nothing to do. Series counters are set to the
highest number used, so new documents continue from there.
"""

import frappe
from frappe.model.rename_doc import rename_doc
from frappe.query_builder import DocType
from frappe.utils import getdate

from sibyl_app.naming import CUSTOMER_ID_FIELD, customer_fields, get_customer, get_settings, is_return

DATE_FIELDS = ("posting_date", "transaction_date", "inst_date", "delivery_date")
COMMIT_EVERY = 50


def resolve_prefix(key, doc_date):
	"""'SO-ACME-.YY.-.####' + date -> ('SO-ACME-26-', 4). Date tokens use the document's own date."""
	prefix, digits = "", 0
	for part in key.split("."):
		if not part:
			continue
		if part.startswith("#"):
			digits = len(part)
			break
		prefix += {
			"YY": doc_date.strftime("%y"),
			"YYYY": doc_date.strftime("%Y"),
			"MM": doc_date.strftime("%m"),
			"DD": doc_date.strftime("%d"),
		}.get(part, part)
	return prefix, digits or 4


def plan(doctypes=None):
	"""Return {doctype: {"renames": [(old, new)], "counters": {prefix: n}, "skipped": n}}."""
	settings = get_settings()
	if not settings or not settings.enabled:
		frappe.throw("Customer-wise naming is disabled in Sibyl Naming Settings.")

	customer_ids = dict(
		frappe.get_all("Customer", fields=["name", CUSTOMER_ID_FIELD], as_list=True)
	)
	result = {}
	for rule in settings.rules:
		if not rule.enabled or (doctypes and rule.document_type not in doctypes):
			continue
		result[rule.document_type] = _plan_doctype(rule, settings.name_pattern, customer_ids)
	return result


def _plan_doctype(rule, pattern, customer_ids):
	doctype = rule.document_type
	meta = frappe.get_meta(doctype)
	date_field = next((f for f in DATE_FIELDS if meta.has_field(f)), None)
	fields = ["name", "creation", "amended_from", *customer_fields(rule, meta)]
	if date_field:
		fields.append(date_field)
	rows = frappe.get_all(doctype, fields=fields, order_by="creation asc")

	series, amended, skipped = {}, [], 0
	for row in rows:
		if row.amended_from:
			amended.append(row)
			continue
		customer = get_customer(row, rule, meta)
		customer_id = customer_ids.get(customer) if customer else None
		if not customer_id:
			skipped += 1  # no customer (e.g. quotation to a lead) -> keeps its name
			continue
		doc_date = getdate(row.get(date_field) or row.creation)
		prefix_word = (is_return(row, doctype) and rule.return_prefix) or rule.prefix
		key = pattern.replace("{prefix}", prefix_word).replace("{customer_id}", customer_id)
		series.setdefault(resolve_prefix(key, doc_date), []).append((doc_date, row.creation, row.name))

	targets, counters = {}, {}
	for (prefix, digits), docs in series.items():
		docs.sort()
		for n, (_date, _creation, name) in enumerate(docs, start=1):
			targets[name] = f"{prefix}{str(n).zfill(digits)}"
		counters[prefix] = len(docs)

	# amendments: <root's new name>-<depth>, following Frappe's amend convention
	parent_of = {row.name: row.amended_from for row in amended}
	for row in amended:
		root, depth = row.name, 0
		while root in parent_of:
			root, depth = parent_of[root], depth + 1
		if root in targets:
			targets[row.name] = f"{targets[root]}-{depth}"
		else:
			skipped += 1

	renames = [(old, new) for old, new in targets.items() if old != new]
	return {"renames": renames, "counters": counters, "skipped": skipped, "total": len(rows)}


def run(doctypes=None, dry_run=False):
	"""Entry point: bench --site X execute sibyl_app.rename_existing.run --kwargs "{'dry_run': True}" """
	if isinstance(doctypes, str):
		doctypes = frappe.parse_json(doctypes)
	plans = plan(doctypes)
	summary = {}
	for doctype, p in plans.items():
		summary[doctype] = {
			"documents": p["total"],
			"to_rename": len(p["renames"]),
			"kept_no_customer": p["skipped"],
			"examples": p["renames"][:3],
		}
		if not dry_run:
			_apply(doctype, p)
	if not dry_run:
		frappe.clear_cache()
	print(frappe.as_json(summary))
	return summary


def _refresh_dynamic_link_map():
	"""rename_doc only rewrites Dynamic Links (GL Entry.voucher_no, Payment Entry Reference.reference_name,
	Payment Ledger Entry ...) for doctypes in a map cached in redis for 12h, which goes stale when ledger
	rows are inserted by raw queries. A stale map silently leaves ledgers pointing at old names - so drop
	it and let rename_doc rebuild it from the tables."""
	frappe.cache.delete_keys("dynamic_link_map::")
	frappe.local.dynamic_link_map = None


def _apply(doctype, p):
	renames = p["renames"]
	if not renames:
		return
	_refresh_dynamic_link_map()
	moving = {old for old, _new in renames}
	existing = set(frappe.get_all(doctype, pluck="name"))

	# targets currently held by another document that is itself moving -> park on a temp name first
	direct, parked = [], []
	for old, new in renames:
		if new in existing:
			if new not in moving:
				frappe.throw(f"{doctype} {new} already exists and is not part of the renumbering.")
			parked.append((old, new, f"{old}~SIBYLTMP"))
		else:
			direct.append((old, new))

	steps = [(old, tmp) for old, _new, tmp in parked] + direct + [(tmp, new) for _old, new, tmp in parked]
	for i, (old, new) in enumerate(steps, start=1):
		rename_doc(
			doctype, old, new, force=True, ignore_permissions=True, show_alert=False, rebuild_search=False
		)
		if i % COMMIT_EVERY == 0:
			frappe.db.commit()

	series = DocType("Series")
	for prefix, count in p["counters"].items():
		if frappe.db.exists("Series", prefix):
			frappe.qb.update(series).set(series.current, count).where(series.name == prefix).run()
		else:
			frappe.qb.into(series).insert(prefix, count).run()
	frappe.db.commit()

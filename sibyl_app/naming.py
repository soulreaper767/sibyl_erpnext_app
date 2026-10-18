"""Customer-wise naming series for sales documents.

Every customer carries a short, unique Customer ID (Customer.sibyl_customer_id).
Sales documents raised against that customer are named from it, with a
separate running counter per customer per document type, e.g.

	SO-ACME-0001, SO-ACME-0002, SO-ZEN-0001, SINV-ACME-0001, CN-ACME-0001 ...

Which doctypes participate (and their prefixes) lives in the
"Sibyl Naming Settings" single, so adding another customer-bearing doctype is
a settings row, not a code change. That's why the autoname hook is wired on
"*" in hooks.py - it returns immediately for any doctype without a rule.

Documents with no resolvable customer (e.g. a Quotation to a Lead) are left
alone and fall through to their standard naming series.
"""

import re

import frappe
from frappe import _
from frappe.model.naming import getseries, make_autoname, revert_series_if_last
from frappe.utils import cint

SETTINGS = "Sibyl Naming Settings"
CUSTOMER_ID_FIELD = "sibyl_customer_id"
CUSTOMER_ID_SERIES = "SIBYL-CUSTOMER-ID"
CUSTOMER_ID_RE = re.compile(r"^[A-Z0-9]+(?:-[A-Z0-9]+)*$")
CUSTOMER_ID_MAX_LEN = 20

# doctype -> (prefix, return/refund prefix); seeded on install for doctypes that exist
DEFAULT_RULES = [
	("Quotation", "QTN", ""),
	("Sales Order", "SO", ""),
	("Delivery Note", "DN", "DNR"),
	("Sales Invoice", "SINV", "CN"),
	("POS Invoice", "POS", "POSR"),
	("Payment Entry", "RCPT", "RFND"),
	("Dunning", "DUN", ""),
	("Installation Note", "INS", ""),
]

# doctypes whose customer sits in a dynamic party field: doctype -> (party-type field, party field)
PARTY_SELECTOR_FIELDS = {
	"Quotation": ("quotation_to", "party_name"),
	"Opportunity": ("opportunity_from", "party_name"),
}

# words dropped when deriving an ID from the customer name
NAME_STOPWORDS = {
	"M", "S", "MS", "MESSRS", "THE", "AND", "OF",
	"PVT", "PRIVATE", "LTD", "LIMITED", "CO", "COMPANY", "INC", "LLC", "LLP", "SMC", "CORP", "CORPORATION",
}  # fmt: skip


# ---------------------------------------------------------------- settings


def get_settings():
	try:
		return frappe.get_cached_doc(SETTINGS)
	except frappe.DoesNotExistError:
		# app mid-install, doctype not synced yet
		return None


def get_rule(doctype):
	settings = get_settings()
	if not settings or not settings.enabled:
		return None
	for rule in settings.rules:
		if rule.enabled and rule.document_type == doctype:
			return rule
	return None


# ---------------------------------------------------------------- doc hooks (wired on "*")


def autoname(doc, method=None):
	if doc.name or doc.meta.istable:
		return
	rule = get_rule(doc.doctype)
	if not rule:
		return
	key = get_series_key(doc, rule)
	if key:
		doc.name = make_autoname(key, doc.doctype, doc)


def on_trash(doc, method=None):
	"""Give the counter back when the latest document of a customer series is deleted."""
	if doc.meta.istable:
		return
	rule = get_rule(doc.doctype)
	if not rule:
		return
	try:
		key = get_series_key(doc, rule, assign_missing=False)
		if key:
			revert_series_if_last(key, doc.name, doc)
	except Exception:
		# never block a delete over counter bookkeeping
		frappe.log_error(title=f"Sibyl App: series revert failed for {doc.doctype} {doc.name}")


# ---------------------------------------------------------------- series key


def get_customer(doc, rule, meta=None):
	"""doc may be a Document or a plain dict row (then pass meta)."""
	meta = meta or doc.meta
	if rule.customer_field:
		return doc.get(rule.customer_field)
	if meta.name in PARTY_SELECTOR_FIELDS:
		type_field, party_field = PARTY_SELECTOR_FIELDS[meta.name]
		return doc.get(party_field) if doc.get(type_field) == "Customer" else None
	if meta.has_field("party_type") and meta.has_field("party"):
		return doc.get("party") if doc.get("party_type") == "Customer" else None
	if meta.has_field("customer"):
		return doc.get("customer")
	return None


def customer_fields(rule, meta):
	"""Fields get_customer/is_return need, for reading rows without loading documents."""
	if rule.customer_field:
		fields = [rule.customer_field]
	elif meta.name in PARTY_SELECTOR_FIELDS:
		fields = list(PARTY_SELECTOR_FIELDS[meta.name])
	elif meta.has_field("party_type") and meta.has_field("party"):
		fields = ["party_type", "party"]
	else:
		fields = ["customer"]
	fields += [f for f in ("is_return", "payment_type") if meta.has_field(f)]
	return fields


def is_return(doc, doctype=None):
	if (doctype or doc.doctype) == "Payment Entry":
		return doc.get("payment_type") == "Pay"
	return bool(cint(doc.get("is_return")))


def get_series_key(doc, rule, assign_missing=True):
	customer = get_customer(doc, rule)
	if not customer:
		return None

	customer_id = frappe.db.get_value("Customer", customer, CUSTOMER_ID_FIELD)
	if not customer_id:
		if not assign_missing:
			return None
		customer_id = assign_customer_id(customer)

	prefix = (is_return(doc) and rule.return_prefix) or rule.prefix
	return build_key(get_settings().name_pattern, prefix, customer_id)


def build_key(pattern, prefix, customer_id):
	return (pattern or "{prefix}-{customer_id}-.####").replace("{prefix}", prefix).replace(
		"{customer_id}", customer_id
	)


# ---------------------------------------------------------------- customer IDs


def normalize_customer_id(value):
	return re.sub(r"\s+", "", (value or "").strip().upper())


def validate_customer_id_format(customer_id):
	if len(customer_id) > CUSTOMER_ID_MAX_LEN or not CUSTOMER_ID_RE.match(customer_id):
		frappe.throw(
			_(
				"Customer ID {0} is invalid. Use only letters A-Z, digits and single hyphens, up to {1} characters."
			).format(frappe.bold(customer_id), CUSTOMER_ID_MAX_LEN),
			title=_("Invalid Customer ID"),
		)


def customer_id_taken(customer_id, exclude_customer=None):
	filters = {CUSTOMER_ID_FIELD: customer_id}
	if exclude_customer:
		filters["name"] = ("!=", exclude_customer)
	return bool(frappe.db.exists("Customer", filters))


def generate_customer_id(customer_name, exclude_customer=None):
	settings = get_settings()
	if not settings or settings.customer_id_mode != "From Customer Name":
		return _next_numeric_id(settings, exclude_customer)

	words = re.findall(r"[A-Z0-9]+", (customer_name or "").upper())
	words = [w for w in words if w not in NAME_STOPWORDS] or words
	if not words:
		# e.g. a name entirely in a non-Latin script
		return _next_numeric_id(settings, exclude_customer)

	length = min(max(cint(settings.customer_id_length if settings else 0) or 4, 2), 12)
	base = ""
	for word in words:
		base += word
		if len(base) >= length:
			break
	base = base[:length]

	candidate, n = base, 1
	while customer_id_taken(candidate, exclude_customer):
		n += 1
		candidate = f"{base}{n}"
	return candidate


def _next_numeric_id(settings, exclude_customer=None):
	"""Optional prefix + running number, e.g. 1001, 1002 ... (or C1001 with prefix C).

	Uses its own row in tabSeries so the counter is independent of any prefix
	and safe under concurrent inserts (getseries locks the row)."""
	prefix = normalize_customer_id(settings.customer_id_prefix if settings else "")
	digits = min(max(cint(settings.customer_id_digits if settings else 0) or 4, 1), 10)
	start = max(cint(settings.customer_id_start if settings else 0) or 1001, 1)
	_ensure_counter_at_least(CUSTOMER_ID_SERIES, start - 1)
	while True:
		candidate = prefix + str(cint(getseries(CUSTOMER_ID_SERIES, 1))).zfill(digits)
		if not customer_id_taken(candidate, exclude_customer):
			return candidate


def _ensure_counter_at_least(key, value):
	current = frappe.db.get_value("Series", key, "current", order_by=None)
	if current is None:
		frappe.db.sql("insert into `tabSeries` (`name`, `current`) values (%s, %s)", (key, value))
	elif cint(current) < value:
		frappe.db.sql("update `tabSeries` set `current` = %s where `name` = %s", (value, key))


def reset_numeric_counter():
	"""Next numeric ID becomes the configured start number."""
	settings = get_settings()
	start = max(cint(settings.customer_id_start if settings else 0) or 1001, 1)
	_ensure_counter_at_least(CUSTOMER_ID_SERIES, 0)
	frappe.db.sql("update `tabSeries` set `current` = %s where `name` = %s", (start - 1, CUSTOMER_ID_SERIES))


def regenerate_all_customer_ids():
	"""Give every customer a fresh ID under the current mode, oldest customer first.
	Returns [(customer, old_id, new_id)]. Document renaming is a separate step."""
	customers = frappe.get_all(
		"Customer", fields=["name", "customer_name", CUSTOMER_ID_FIELD], order_by="creation asc, name asc"
	)
	# clear first so new IDs can't clash with old ones still in place
	frappe.db.sql(f"update `tabCustomer` set `{CUSTOMER_ID_FIELD}` = NULL")
	reset_numeric_counter()
	changes = []
	for row in customers:
		new_id = generate_customer_id(row.customer_name or row.name, exclude_customer=row.name)
		frappe.db.set_value("Customer", row.name, CUSTOMER_ID_FIELD, new_id, update_modified=False)
		changes.append((row.name, row.get(CUSTOMER_ID_FIELD), new_id))
	return changes


def assign_customer_id(customer):
	"""Lazily give an ID to a customer that doesn't have one yet (pre-existing data)."""
	settings = get_settings()
	if settings and not settings.auto_assign_customer_id:
		frappe.throw(
			_("Customer {0} has no Customer ID. Set one on the Customer before creating this document.").format(
				frappe.bold(customer)
			),
			title=_("Customer ID Missing"),
		)
	customer_name = frappe.db.get_value("Customer", customer, "customer_name")
	customer_id = generate_customer_id(customer_name or customer, exclude_customer=customer)
	frappe.db.set_value("Customer", customer, CUSTOMER_ID_FIELD, customer_id, update_modified=False)
	return customer_id


def customer_validate(doc, method=None):
	"""Customer.validate - normalise / auto-assign / enforce uniqueness of the Customer ID."""
	customer_id = normalize_customer_id(doc.get(CUSTOMER_ID_FIELD))

	if not customer_id:
		settings = get_settings()
		if settings and not settings.auto_assign_customer_id:
			return
		customer_id = generate_customer_id(doc.customer_name, exclude_customer=doc.name)

	validate_customer_id_format(customer_id)
	if customer_id_taken(customer_id, exclude_customer=doc.name):
		frappe.throw(
			_("Customer ID {0} is already used by another customer.").format(frappe.bold(customer_id)),
			title=_("Duplicate Customer ID"),
		)

	before = doc.get_doc_before_save()
	old_id = before.get(CUSTOMER_ID_FIELD) if before else None
	if old_id and old_id != customer_id:
		frappe.msgprint(
			_(
				"Customer ID changed from {0} to {1}. Existing documents keep their names; new documents will use {1}."
			).format(frappe.bold(old_id), frappe.bold(customer_id)),
			indicator="orange",
			alert=True,
		)

	doc.set(CUSTOMER_ID_FIELD, customer_id)


def backfill_customer_ids():
	"""Assign IDs to every customer that lacks one. Returns how many were assigned."""
	names = frappe.get_all(
		"Customer",
		filters=[[CUSTOMER_ID_FIELD, "in", ["", None]]],
		fields=["name", "customer_name"],
		order_by="creation asc",
	)
	for row in names:
		customer_id = generate_customer_id(row.customer_name or row.name, exclude_customer=row.name)
		frappe.db.set_value("Customer", row.name, CUSTOMER_ID_FIELD, customer_id, update_modified=False)
	return len(names)

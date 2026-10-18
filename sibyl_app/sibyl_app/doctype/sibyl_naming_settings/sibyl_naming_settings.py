import re

import frappe
from frappe import _
from frappe.model.document import Document

from sibyl_app.naming import PARTY_SELECTOR_FIELDS, backfill_customer_ids, build_key

PREFIX_RE = re.compile(r"^[A-Z0-9][A-Z0-9/-]*$")


class SibylNamingSettings(Document):
	def validate(self):
		self.validate_pattern()
		self.validate_rules()

	def validate_pattern(self):
		self.name_pattern = (self.name_pattern or "").strip()
		for token in ("{prefix}", "{customer_id}"):
			if token not in self.name_pattern:
				frappe.throw(_("Name Pattern must contain {0}.").format(frappe.bold(token)))
		if "#" not in self.name_pattern:
			frappe.throw(_("Name Pattern must contain a counter, e.g. .####"))

	def validate_rules(self):
		seen = set()
		for rule in self.rules:
			if rule.document_type in seen:
				frappe.throw(
					_("Row {0}: {1} appears more than once.").format(rule.idx, frappe.bold(rule.document_type))
				)
			seen.add(rule.document_type)

			for field in ("prefix", "return_prefix"):
				value = (rule.get(field) or "").strip().upper()
				if value and not PREFIX_RE.match(value):
					frappe.throw(
						_("Row {0}: prefix {1} may only contain A-Z, 0-9, '-' and '/'.").format(
							rule.idx, frappe.bold(value)
						)
					)
				rule.set(field, value)

			meta = frappe.get_meta(rule.document_type)
			if meta.istable or meta.issingle:
				frappe.throw(_("Row {0}: {1} cannot be named per customer.").format(rule.idx, rule.document_type))
			if not self._has_customer(meta, rule):
				frappe.throw(
					_(
						"Row {0}: could not find a Customer field on {1}. Set Customer Field to the fieldname that links to Customer."
					).format(rule.idx, frappe.bold(rule.document_type))
				)

	@staticmethod
	def _has_customer(meta, rule):
		if rule.customer_field:
			return meta.has_field(rule.customer_field)
		return (
			rule.document_type in PARTY_SELECTOR_FIELDS
			or (meta.has_field("party_type") and meta.has_field("party"))
			or meta.has_field("customer")
		)


@frappe.whitelist()
def assign_missing_customer_ids():
	frappe.only_for(("System Manager", "Sales Manager"))
	return backfill_customer_ids()


@frappe.whitelist()
def preview_existing_renames():
	frappe.only_for("System Manager")
	from sibyl_app.rename_existing import run

	return run(dry_run=True)


@frappe.whitelist()
def rename_existing_documents():
	frappe.only_for("System Manager")
	frappe.enqueue(
		"sibyl_app.rename_existing.run",
		queue="long",
		timeout=6 * 60 * 60,
		job_id="sibyl_app::rename_existing",
		deduplicate=True,
	)
	return True


@frappe.whitelist(methods=["POST"])
def regenerate_customer_ids():
	"""Re-number every customer under the current Customer ID Mode (oldest first), then
	rename their existing documents to match. Runs inline for small sites, else as a job."""
	frappe.only_for("System Manager")
	if frappe.db.count("Customer") > 300:
		frappe.enqueue(
			"sibyl_app.sibyl_app.doctype.sibyl_naming_settings.sibyl_naming_settings._regenerate",
			queue="long",
			timeout=6 * 60 * 60,
			job_id="sibyl_app::regenerate_customer_ids",
			deduplicate=True,
		)
		return {"queued": True}
	return _regenerate()


def _regenerate():
	from sibyl_app.naming import regenerate_all_customer_ids
	from sibyl_app.rename_existing import run

	changes = regenerate_all_customer_ids()
	frappe.db.commit()
	documents = run()
	return {"customers": changes, "documents": documents}


@frappe.whitelist()
def preview(name_pattern, prefix="SO", return_prefix=None):
	sample = frappe.db.get_value(
		"Customer", {"sibyl_customer_id": ("is", "set")}, ["customer_name", "sibyl_customer_id"], as_dict=True
	) or frappe._dict(customer_name="Acme Traders Pvt Ltd", sibyl_customer_id="ACME")

	def render(p):
		key = build_key(name_pattern, p, sample.sibyl_customer_id)
		# show the first number without consuming the series
		return re.sub(r"\.?(#+)", lambda m: "1".zfill(len(m.group(1))), key).replace(".", "")

	return {
		"customer": sample.customer_name,
		"customer_id": sample.sibyl_customer_id,
		"name": render(prefix),
		"return_name": render(return_prefix) if return_prefix else None,
	}

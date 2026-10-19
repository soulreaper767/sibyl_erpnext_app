"""Keep the customer's name consistent everywhere it is stored as text.

Renaming a Customer (or editing its Customer Name) only updates Link fields;
transactions also keep a *copy* of the name (customer_name / party_name) that is
what prints on documents - and it is read-only once submitted. This pushes the
current name into those copies (and into linked Contacts' company name), and
leaves one comment on the Customer recording what was updated.
"""

import frappe
from frappe import _

# doctype -> (link field, name field, extra filters)
NAME_COPIES = {
	"Quotation": ("party_name", "customer_name", {"quotation_to": "Customer"}),
	"Opportunity": ("party_name", "customer_name", {"opportunity_from": "Customer"}),
	"Sales Order": ("customer", "customer_name", {}),
	"Delivery Note": ("customer", "customer_name", {}),
	"Sales Invoice": ("customer", "customer_name", {}),
	"POS Invoice": ("customer", "customer_name", {}),
	"Dunning": ("customer", "customer_name", {}),
	"Installation Note": ("customer", "customer_name", {}),
	"Maintenance Visit": ("customer", "customer_name", {}),
	"Warranty Claim": ("customer", "customer_name", {}),
	"Payment Entry": ("party", "party_name", {"party_type": "Customer"}),
	"Payment Request": ("party", "party_name", {"party_type": "Customer"}),
}


def after_rename(doc, method=None, old=None, new=None, merge=False):
	if not merge:
		sync_customer_name(doc.name, old_name=old)


def on_update(doc, method=None):
	before = doc.get_doc_before_save()
	if before and before.customer_name != doc.customer_name:
		sync_customer_name(doc.name, old_name=before.customer_name)


def sync_customer_name(customer, old_name=None):
	name = frappe.db.get_value("Customer", customer, "customer_name")
	updated = {}
	for doctype, (link, field, extra) in NAME_COPIES.items():
		if not frappe.db.exists("DocType", doctype):
			continue
		meta = frappe.get_meta(doctype)
		if not (meta.has_field(link) and meta.has_field(field)):
			continue
		names = frappe.get_all(
			doctype, filters={link: customer, field: ["!=", name], **extra}, pluck="name"
		)
		for n in names:
			# copy of a master field on posted documents - not an accounting change
			frappe.db.set_value(doctype, n, field, name, update_modified=False)
		if names:
			updated[doctype] = len(names)

	contacts = frappe.get_all(
		"Dynamic Link",
		filters={"link_doctype": "Customer", "link_name": customer, "parenttype": "Contact"},
		pluck="parent",
	)
	for c in contacts:
		if frappe.db.get_value("Contact", c, "company_name") != name:
			frappe.db.set_value("Contact", c, "company_name", name, update_modified=False)
			updated["Contact"] = updated.get("Contact", 0) + 1

	if updated:
		frappe.get_doc("Customer", customer).add_comment(
			"Info",
			_("Customer name {0} applied to existing records{1}: {2}").format(
				frappe.bold(name),
				_(" (was {0})").format(frappe.bold(old_name)) if old_name and old_name != name else "",
				", ".join(f"{dt} {n}" for dt, n in updated.items()),
			),
		)
	return updated


@frappe.whitelist(methods=["POST"])
def resync_customer_name(customer):
	frappe.only_for(("System Manager", "Accounts Manager", "Sales Manager"))
	return sync_customer_name(customer)

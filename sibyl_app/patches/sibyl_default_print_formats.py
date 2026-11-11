import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

from sibyl_app.print_utils import SIBYL_DOCTYPES


def execute():
	"""Make "Sibyl <DocType>" the default print format for every transaction doctype it covers (runs once;
	a default changed later in Customize Form is not overridden again)."""
	for doctype in SIBYL_DOCTYPES:
		name = f"Sibyl {doctype}"
		if not frappe.db.exists("DocType", doctype):
			continue
		if not frappe.db.exists("Print Format", name):
			frappe.reload_doc("sibyl_app", "print_format", name.lower().replace(" ", "_"))
		make_property_setter(doctype, None, "default_print_format", name, "Data", for_doctype=True)

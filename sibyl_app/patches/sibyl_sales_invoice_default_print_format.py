import frappe
from frappe.custom.doctype.property_setter.property_setter import make_property_setter


def execute():
	"""Make "Sibyl Sales Invoice" (payment status section) the default Sales Invoice print format - once,
	so a default chosen later in Customize Form is never overridden by a migrate."""
	if not frappe.db.exists("Print Format", "Sibyl Sales Invoice"):
		frappe.reload_doc("sibyl_app", "print_format", "sibyl_sales_invoice")
	make_property_setter(
		"Sales Invoice", None, "default_print_format", "Sibyl Sales Invoice", "Data", for_doctype=True
	)

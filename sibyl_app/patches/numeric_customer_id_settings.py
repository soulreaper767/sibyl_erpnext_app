import frappe


def execute():
	"""'Sequential' mode became 'Numeric'; its old default prefix 'C' is now blank (plain 1001, 1002 ...)."""
	settings = "Sibyl Naming Settings"
	if frappe.db.get_single_value(settings, "customer_id_mode") == "Sequential":
		frappe.db.set_single_value(settings, "customer_id_mode", "Numeric")
	if frappe.db.get_single_value(settings, "customer_id_prefix") == "C":
		frappe.db.set_single_value(settings, "customer_id_prefix", "")
	if not frappe.db.get_single_value(settings, "customer_id_start"):
		frappe.db.set_single_value(settings, "customer_id_start", 1001)

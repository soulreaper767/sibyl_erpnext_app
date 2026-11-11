import frappe


def execute():
	"""Sibyl branding for system emails (the templates themselves live in sibyl_app/templates/emails).
	Only replaces Frappe/ERPNext defaults - anything already customised is left alone."""
	settings = frappe.get_single("System Settings")
	changed = False

	if (settings.app_name or "").strip().lower() in ("", "frappe", "erpnext", "frappe framework"):
		settings.app_name = "Sibyl ERP"
		changed = True

	if not settings.disable_standard_email_footer:
		settings.disable_standard_email_footer = 1
		changed = True

	if not (settings.email_footer_address or "").strip():
		address = company_footer_address()
		if address:
			settings.email_footer_address = address
			changed = True

	if changed:
		settings.flags.ignore_mandatory = True
		settings.save(ignore_permissions=True)


def company_footer_address():
	company = frappe.defaults.get_global_default("company")
	if not company:
		return ""
	address_name = frappe.db.get_value(
		"Dynamic Link", {"link_doctype": "Company", "link_name": company, "parenttype": "Address"}, "parent"
	)
	lines = []
	if address_name:
		a = frappe.db.get_value(
			"Address", address_name, ["address_line1", "address_line2", "city", "state", "pincode"], as_dict=True
		)
		street = ", ".join(x for x in (a.address_line1, a.address_line2) if x)
		place = ", ".join(x for x in (a.city, a.state) if x) + (f" {a.pincode}" if a.pincode else "")
		lines.append(", ".join(x for x in (street, place.strip()) if x))
	tax_id = frappe.db.get_value("Company", company, "tax_id")
	if tax_id:
		lines.append(f"NTN {tax_id}")
	return "\n".join(lines)

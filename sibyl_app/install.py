import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields
from frappe.custom.doctype.property_setter.property_setter import make_property_setter

from sibyl_app.naming import CUSTOMER_ID_FIELD, DEFAULT_RULES, SETTINGS, backfill_customer_ids


def has_app_permission():
	return frappe.has_permission("Sibyl Naming Settings", "read") or frappe.has_permission("Customer", "read")


def after_install():
	setup()


def after_migrate():
	setup()


def setup():
	"""Idempotent - runs on install and every migrate so nothing is ever manual."""
	create_customer_id_field()
	add_customer_id_to_search_fields()
	seed_naming_settings()
	if backfill_customer_ids():
		frappe.db.commit()


def create_customer_id_field():
	create_custom_fields(
		{
			"Customer": [
				{
					"fieldname": CUSTOMER_ID_FIELD,
					"label": "Customer ID",
					"fieldtype": "Data",
					"insert_after": "customer_name",
					"length": 20,
					"bold": 1,
					"in_list_view": 1,
					"in_standard_filter": 1,
					"in_global_search": 1,
					"no_copy": 1,
					"search_index": 1,
					"description": "Short unique code used in this customer's document names, e.g. SO-ACME-0001. "
					"Leave blank to auto-assign.",
				}
			]
		},
		update=True,
	)


def add_customer_id_to_search_fields():
	search_fields = [
		f.strip() for f in (frappe.get_meta("Customer").search_fields or "").split(",") if f.strip()
	]
	if CUSTOMER_ID_FIELD in search_fields:
		return
	search_fields.insert(0, CUSTOMER_ID_FIELD)
	make_property_setter(
		"Customer", None, "search_fields", ", ".join(search_fields), "Data", for_doctype=True
	)


def seed_naming_settings():
	"""Seed default rules once; afterwards the settings belong to the user."""
	settings = frappe.get_single(SETTINGS)
	if settings.rules_seeded:
		return
	existing = {r.document_type for r in settings.rules}
	for doctype, prefix, return_prefix in DEFAULT_RULES:
		if doctype in existing or not frappe.db.exists("DocType", doctype):
			continue
		settings.append(
			"rules",
			{"document_type": doctype, "prefix": prefix, "return_prefix": return_prefix, "enabled": 1},
		)
	settings.rules_seeded = 1
	settings.flags.ignore_permissions = True
	settings.save()
	frappe.db.commit()

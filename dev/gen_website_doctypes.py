"""Writes the JSON for the two website doctypes (run once from the app root; kept out of the package)."""
import json
import os

ROOT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "sibyl_app", "sibyl_app", "doctype")
TS = "2026-11-11 12:00:00.000000"


def F(fieldname, fieldtype, label=None, options=None, **kw):
	d = {"fieldname": fieldname, "fieldtype": fieldtype}
	if label:
		d["label"] = label
	if options is not None:
		d["options"] = options
	d.update(kw)
	return d


def S(fieldname, label, **kw):
	return F(fieldname, "Section Break", label, **kw)


def C(fieldname):
	return F(fieldname, "Column Break")


def perm(role, **kw):
	p = {"role": role, "read": 1, "write": 1, "create": 1, "delete": 1, "report": 1, "export": 1, "print": 1, "email": 1, "share": 1}
	p.update(kw)
	return p


FORM_TYPES = "\n".join([
	"Service Enquiry", "Sales Enquiry", "Demo Request", "Project Enquiry", "Odoo Enquiry", "Partnership Enquiry",
	"General Enquiry", "Support Request", "Careers Enquiry", "Job Application", "Newsletter",
])

DOCTYPES = {
	"Sibyl Website Settings": dict(
		issingle=1,
		description="Connects the sibyl.pk website forms to this system.",
		fields=[
			S("connection_section", "Website Connection"),
			F("enabled", "Check", "Accept website forms", default="1",
			  description="When off, the website falls back to plain email for every form."),
			F("site_url", "Data", "Website address", default="https://sibyl.pk"),
			C("column_break_conn"),
			F("site_key", "Password", "Website key",
			  description="Shared secret the website sends with every form. The same value goes into "
						  "config/secrets.php on the website server. Changing it here disconnects the website until it is updated there too."),
			F("last_submission", "Datetime", "Last submission", read_only=1),
			S("routing_section", "Who handles what"),
			F("lead_owner", "Link", "Enquiries go to", "User",
			  description="Owner of new Leads (contact, demo, project, Odoo and service enquiries)."),
			F("hr_owner", "Link", "Job applications go to", "User"),
			F("support_owner", "Link", "Support requests go to", "User"),
			C("column_break_routing"),
			F("notify_emails", "Small Text", "Also alert these addresses",
			  description="One email address per line. They get the same new-submission alert as the owners."),
			F("newsletter_group", "Link", "Newsletter list", "Email Group"),
			S("replies_section", "Automatic Replies"),
			F("auto_reply", "Check", "Send an automatic reply to the visitor", default="1"),
			F("enquiry_template", "Link", "Enquiry reply", "Email Template"),
			F("application_template", "Link", "Job application reply", "Email Template"),
			F("support_template", "Link", "Support request reply", "Email Template"),
			C("column_break_replies"),
			F("newsletter_template", "Link", "Newsletter welcome", "Email Template"),
			F("alert_template", "Link", "Staff alert", "Email Template"),
			S("contact_section", "Shown in replies"),
			F("public_email", "Data", "Public email", default="sibyltechnologiespk@gmail.com"),
			F("public_phone", "Data", "Public phone", default="+92 33 111 66 778"),
			C("column_break_contact"),
			F("whatsapp_no", "Data", "WhatsApp number", default="923311166778", description="Digits only, with country code."),
			S("limits_section", "Limits", collapsible=1),
			F("max_per_hour", "Int", "Submissions per visitor per hour", default="5"),
			F("max_file_mb", "Int", "Largest CV upload (MB)", default="5"),
		],
		permissions=[perm("System Manager", create=1, delete=0), perm("Sales Manager", create=1, delete=0)],
	),
	"Sibyl Web Submission": dict(
		autoname="WEB-.YYYY.-.#####",
		title_field="full_name",
		sort_field="creation",
		sort_order="DESC",
		description="Every form sent from the website, with the record it created.",
		fields=[
			F("form_type", "Select", "Form", FORM_TYPES, in_list_view=1, in_standard_filter=1, read_only=1),
			F("status", "Select", "Status", "Received\nProcessed\nFailed\nRejected", default="Received", in_list_view=1,
			  in_standard_filter=1, read_only=1),
			F("full_name", "Data", "Name", in_list_view=1, read_only=1),
			F("email", "Data", "Email", options="Email", in_list_view=1, in_standard_filter=1, read_only=1),
			F("phone", "Data", "Phone", read_only=1),
			F("company_name", "Data", "Company / City", read_only=1),
			C("column_break_main"),
			F("reference_doctype", "Link", "Created", "DocType", read_only=1),
			F("reference_name", "Dynamic Link", "Record", "reference_doctype", in_list_view=1, read_only=1),
			F("topic", "Data", "Topic", read_only=1),
			F("submitted_on", "Datetime", "Received on", read_only=1),
			F("auto_reply_sent", "Check", "Automatic reply sent", read_only=1),
			S("message_section", "Message"),
			F("message", "Text", "Message", read_only=1),
			S("details_section", "Technical details", collapsible=1),
			F("ip_address", "Data", "Visitor IP", read_only=1),
			F("page_url", "Data", "Sent from page", read_only=1),
			F("user_agent", "Small Text", "Browser", read_only=1),
			F("payload", "Code", "Everything sent", options="JSON", read_only=1),
			F("error", "Code", "Error", read_only=1),
		],
		permissions=[
			perm("System Manager", create=0),
			perm("Sales Manager", create=0, delete=0),
			perm("Sales User", create=0, delete=0, write=0),
			perm("HR Manager", create=0, delete=0, write=0),
			perm("Support Team", create=0, delete=0, write=0),
		],
	),
}


def scrub(name):
	return name.lower().replace(" ", "_")


for name, spec in DOCTYPES.items():
	fields = spec.pop("fields")
	perms = spec.pop("permissions")
	d = {
		"actions": [], "creation": TS, "doctype": "DocType", "engine": "InnoDB",
		"field_order": [f["fieldname"] for f in fields], "fields": fields,
		"index_web_pages_for_search": 0, "links": [], "modified": TS, "modified_by": "Administrator",
		"module": "Sibyl App", "name": name, "owner": "Administrator", "permissions": perms,
		"row_format": "Dynamic", "states": [], "track_changes": 0,
	}
	if not spec.get("issingle"):
		d.update({"sort_field": "creation", "sort_order": "DESC"})
	d.update(spec)
	folder = os.path.join(ROOT, scrub(name))
	os.makedirs(folder, exist_ok=True)
	with open(os.path.join(folder, scrub(name) + ".json"), "w") as fh:
		json.dump(d, fh, indent=1, sort_keys=True)
		fh.write("\n")
	print("wrote", name)

"""Setup for the website forms (runs on install and every migrate; never overwrites what was changed)."""
import secrets

import frappe
from frappe.custom.doctype.custom_field.custom_field import create_custom_fields

SETTINGS = "Sibyl Website Settings"
GROUP = "Sibyl Newsletter"


def setup():
	create_custom_fields({dt: f for dt, f in CUSTOM_FIELDS.items() if frappe.db.exists("DocType", dt)}, update=True)
	if not frappe.db.exists("UTM Source", "Website") and frappe.db.exists("DocType", "UTM Source"):
		frappe.get_doc({"doctype": "UTM Source", "name": "Website", "description": "sibyl.pk website forms"}).insert(ignore_permissions=True)
	if not frappe.db.exists("Email Group", GROUP):
		frappe.get_doc({"doctype": "Email Group", "title": GROUP}).insert(ignore_permissions=True)
	for name, (subject, body) in TEMPLATES.items():
		if not frappe.db.exists("Email Template", name):
			frappe.get_doc({"doctype": "Email Template", "name": name, "subject": subject, "use_html": 1,
							"response_html": body}).insert(ignore_permissions=True)
	_settings_defaults()


def _settings_defaults():
	s = frappe.get_single(SETTINGS)
	changed = False
	for field, value in (("newsletter_group", GROUP), ("enquiry_template", "Sibyl Web - Enquiry Received"),
						 ("application_template", "Sibyl Web - Application Received"),
						 ("support_template", "Sibyl Web - Support Request Received"),
						 ("newsletter_template", "Sibyl Web - Newsletter Welcome"),
						 ("alert_template", "Sibyl Web - New Submission Alert")):
		if not s.get(field):
			s.set(field, value)
			changed = True
	if not frappe.db.sql("select 1 from tabSingles where doctype=%s and field='enabled'", SETTINGS):
		s.enabled = 1
		s.auto_reply = 1
		changed = True
	for field, value in (("site_url", "https://sibyl.pk"), ("max_per_hour", 5), ("max_file_mb", 5),
						 ("public_email", "sibyltechnologiespk@gmail.com"), ("public_phone", "+92 33 111 66 778"),
						 ("whatsapp_no", "923311166778")):
		if not s.get(field):
			s.set(field, value)
			changed = True
	if not s.get_password("site_key", raise_exception=False):
		s.site_key = secrets.token_urlsafe(32)
		changed = True
	if changed:
		s.flags.ignore_permissions = True
		s.save()


def _section(dt, after, label):
	return {"fieldname": "sibyl_web_section", "label": label, "fieldtype": "Section Break", "insert_after": after, "collapsible": 1}


def _f(fieldname, label, after, fieldtype="Data", **kw):
	d = {"fieldname": fieldname, "label": label, "fieldtype": fieldtype, "insert_after": after, "read_only": 1}
	d.update(kw)
	return d


CUSTOM_FIELDS = {
	"Lead": [
		_section("Lead", "notes", "Website Enquiry"),
		_f("sibyl_web_form", "Form", "sibyl_web_section", in_standard_filter=1),
		_f("sibyl_web_topic", "Topic", "sibyl_web_form"),
		_f("sibyl_web_product", "Product of interest", "sibyl_web_topic"),
		_f("sibyl_web_col", None, "sibyl_web_product", "Column Break"),
		_f("sibyl_web_budget", "Budget", "sibyl_web_col"),
		_f("sibyl_web_timeline", "Timeline", "sibyl_web_budget"),
		_f("sibyl_web_submission", "Website submission", "sibyl_web_timeline", "Link", options="Sibyl Web Submission"),
	],
	"Job Applicant": [
		_section("Job Applicant", "upper_range", "From the website"),
		_f("sibyl_web_position", "Applied for", "sibyl_web_section", in_list_view=1, in_standard_filter=1),
		_f("sibyl_web_experience", "Experience", "sibyl_web_position"),
		_f("sibyl_web_col", None, "sibyl_web_experience", "Column Break"),
		_f("sibyl_web_location", "City / location", "sibyl_web_col"),
		_f("sibyl_web_expected_salary", "Expected salary (as written)", "sibyl_web_location"),
		_f("sibyl_web_submission", "Website submission", "sibyl_web_expected_salary", "Link", options="Sibyl Web Submission"),
	],
	"Issue": [
		_f("sibyl_web_submission", "Website submission", "via_customer_portal", "Link", options="Sibyl Web Submission"),
	],
}
for _fields in CUSTOM_FIELDS.values():
	for _d in _fields:
		if _d["fieldtype"] in ("Section Break", "Column Break"):
			_d.pop("read_only", None)
		if _d.get("label") is None:
			_d.pop("label", None)


SIGN = ('<p style="margin-top:22px;">Kind regards,<br><b>{{ company }}</b><br>'
		'<span style="color:#667085;font-size:12px;">'
		'<a href="{{ site_url }}">{{ site_url | replace("https://", "") }}</a>'
		'{% if public_phone %} &nbsp;&middot;&nbsp; {{ public_phone }}{% endif %}'
		'{% if whatsapp_url %} &nbsp;&middot;&nbsp; <a href="{{ whatsapp_url }}">WhatsApp</a>{% endif %}'
		'</span></p>')
YOURS = ('<p style="margin:18px 0 6px 0;color:#667085;font-size:12px;text-transform:uppercase;letter-spacing:.04em;">'
		 'What you sent us</p>{{ summary_html }}')

TEMPLATES = {
	"Sibyl Web - Enquiry Received": (
		"We've received your {{ form_label | lower }} - {{ company }}",
		'<p>Dear {{ first_name }},</p>'
		'<p>Thank you for contacting {{ company }}. We have received your <b>{{ form_label | lower }}</b>'
		'{% if topic %} about <b>{{ topic }}</b>{% endif %}, and a specialist will get back to you within one business day.</p>'
		'<p>If you would like to add anything, simply reply to this email - it reaches the same team.</p>'
		+ YOURS + SIGN,
	),
	"Sibyl Web - Application Received": (
		"Application received{% if topic %}: {{ topic }}{% endif %} - {{ company }}",
		'<p>Dear {{ first_name }},</p>'
		'<p>Thank you for applying{% if topic %} for <b>{{ topic }}</b>{% endif %} at {{ company }}. '
		'Your application has reached our hiring team.</p>'
		'<p>We review every application carefully and will contact you within 3-5 business days if your profile '
		'matches the role. You can reply to this email to send anything else, such as an updated CV.</p>'
		+ YOURS + SIGN,
	),
	"Sibyl Web - Support Request Received": (
		"Support ticket {{ reference }} opened - {{ company }}",
		'<p>Dear {{ first_name }},</p>'
		'<p>We have opened support ticket <b>{{ reference }}</b> for your request. Our support team will reply to you by email.</p>'
		'<p>Please keep <b>{{ reference }}</b> in the subject when you write to us about it - replying to this email does that for you.</p>'
		+ YOURS + SIGN,
	),
	"Sibyl Web - Newsletter Welcome": (
		"Welcome to the {{ company }} newsletter",
		'<p>Hello,</p>'
		'<p>Thank you for subscribing. You will now receive our insights on ERP, cloud and AI for growing businesses, '
		'along with product news from {{ company }}.</p>'
		'<p>Meanwhile, our latest articles are on <a href="{{ site_url }}/blog">{{ site_url | replace("https://", "") }}/blog</a>.</p>'
		'<p style="color:#667085;font-size:12px;">You can unsubscribe at any time from the link in any newsletter, or by replying to this email.</p>'
		+ SIGN,
	),
	"Sibyl Web - New Submission Alert": (
		"New website {{ form_label | lower }}: {{ full_name }}{% if company_name %} ({{ company_name }}){% endif %}",
		'<p>A new <b>{{ form_label | lower }}</b> has arrived from the website and is filed as '
		'<b>{{ reference_doctype }} {{ reference }}</b>.</p>'
		'{{ summary_html }}'
		'<p style="margin-top:20px;"><a class="btn btn-primary" href="{{ reference_url }}">Open {{ reference_doctype }} {{ reference }}</a></p>'
		'<p style="color:#667085;font-size:12px;">Reply from the record\'s timeline so the conversation stays with it.'
		'{% if reference_doctype != "Email Group Member" %} An automatic acknowledgement has already gone to {{ email }}.{% endif %}</p>',
	),
}

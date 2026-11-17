"""Customer support portal (portal.sibyl.pk).

Customers of the main company log in at portal.sibyl.pk and, under "Issues" (/issues), raise
support tickets (ERPNext Issue), follow their status and add replies. The same login shows their
own orders, invoices and quotations.

  * "Portal Access" button on Customer -> create_portal_user(): a Website User with the Customer
    role, tied to the customer's contact and listed in Customer > Portal Users. Nothing is emailed
    unless "send login link" is ticked (the customer then gets a set-your-password email).
    provision_customers() does the same for every real (non-demo) customer that has an email.
  * A ticket raised in the portal is filed under the default company, shown on the ticket's
    timeline as the customer's message, acknowledged to the customer, and the support owner
    (Sibyl Website Settings) gets an alert and a To Do.
  * When staff move a ticket to On Hold / Resolved / Closed, the customer gets an email with a
    link back to the ticket. Staff replies from the timeline are emailed as usual.
  * A customer's follow-up (portal comment or emailed reply) reopens the ticket and alerts support.

Demo companies/customers are never touched (their mail is blocked anyway, see demo.py)."""
import frappe
from frappe import _
from frappe.utils import cint, escape_html, get_url, get_url_to_form, validate_email_address

PORTAL_ROLE = "Customer"
STATUS_MAILS = ("On Hold", "Resolved", "Closed")
T_ACK = "Sibyl Support - Ticket Received"
T_STATUS = "Sibyl Support - Status Update"
T_STAFF = "Sibyl Support - Ticket Alert"
ISSUE_TYPES = ("Bug / Error", "How-to Question", "Change Request", "Access / Login", "Billing")
MANAGERS = ("System Manager", "Sales Manager")


# =========================================================================== portal logins
@frappe.whitelist()
def create_portal_user(customer, email=None, full_name=None, send_login_link=0):
	"""Give one customer a portal login (idempotent). Returns what was done."""
	frappe.only_for(MANAGERS)
	cust = frappe.get_doc("Customer", customer)
	if _demo_customer(cust):
		frappe.throw(_("{0} is a demo customer - demo customers don't get portal logins.").format(customer))
	email = (email or _customer_email(cust) or "").strip().lower()
	if not email:
		frappe.throw(_("{0} has no email. Enter the email of the person who will log in.").format(customer))
	validate_email_address(email, throw=True)
	contact = _contact_for(cust, email)
	name = (full_name or "").strip() or (contact and frappe.db.get_value("Contact", contact, "full_name")) or cust.customer_name
	user, created = _ensure_user(email, name)
	contact = _link_contact(cust, contact, email, user, name)
	if user not in [p.user for p in cust.get("portal_users") or []]:
		cust.append("portal_users", {"user": user})
		cust.flags.ignore_permissions = True
		cust.save()
	sent = False
	if cint(send_login_link):
		frappe.get_doc("User", user).send_welcome_mail_to_user()
		sent = True
	frappe.db.commit()
	return {"customer": customer, "user": user, "contact": contact, "created": created, "login_link_sent": sent,
			"login_url": get_url("/login"), "tickets_url": get_url("/issues")}


@frappe.whitelist()
def provision_customers(send_login_link=0):
	"""Portal logins for every enabled, non-demo customer that has an email. Returns a per-customer report."""
	frappe.only_for(MANAGERS)
	report = []
	for c in frappe.get_all("Customer", filters={"disabled": 0}, pluck="name", order_by="name"):
		cust = frappe.get_doc("Customer", c)
		if _demo_customer(cust):
			continue
		if not _customer_email(cust):
			report.append({"customer": c, "result": "no email - add a contact email, then use Portal Access"})
			continue
		try:
			r = create_portal_user(c, send_login_link=send_login_link)
			report.append({"customer": c, "result": ("created " if r["created"] else "already had ") + r["user"]})
		except Exception as e:
			frappe.db.rollback()
			report.append({"customer": c, "result": "failed: %s" % e})
	return report


@frappe.whitelist()
def portal_status(customer):
	"""For the Customer form: who can log in, and the email the button would use."""
	frappe.has_permission("Customer", "read", customer, throw=True)
	cust = frappe.get_doc("Customer", customer)
	users = [p.user for p in cust.get("portal_users") or []]
	return {"users": [{"user": u, "enabled": frappe.db.get_value("User", u, "enabled"),
					   "last_login": frappe.db.get_value("User", u, "last_login")} for u in users],
			"suggested_email": _customer_email(cust) or "", "demo": _demo_customer(cust)}


def _demo_customer(cust):
	from sibyl_app.demo import CUSTOMER_GROUP

	return cust.customer_group == CUSTOMER_GROUP


def _customer_emails(cust):
	emails = [cust.get("email_id")]
	if cust.get("customer_primary_contact"):
		emails.append(frappe.db.get_value("Contact", cust.customer_primary_contact, "email_id"))
	for contact in _contacts(cust.name):
		emails += frappe.get_all("Contact Email", filters={"parent": contact, "parenttype": "Contact"}, pluck="email_id")
	return [e.strip().lower() for e in emails if e and validate_email_address(e.strip())]


def _customer_email(cust):
	emails = _customer_emails(cust)
	return emails[0] if emails else None


def _contacts(customer):
	return frappe.get_all("Dynamic Link", filters={"parenttype": "Contact", "link_doctype": "Customer", "link_name": customer},
						  pluck="parent")


def _contact_for(cust, email):
	for contact in _contacts(cust.name):
		if frappe.db.exists("Contact Email", {"parent": contact, "parenttype": "Contact", "email_id": email}) or \
				(frappe.db.get_value("Contact", contact, "email_id") or "").lower() == email:
			return contact
	return None


def _ensure_user(email, full_name):
	if frappe.db.exists("User", email):
		u = frappe.get_doc("User", email)
		if u.user_type == "System User":
			frappe.throw(_("{0} is a staff login. Use the customer's own email for portal access.").format(email))
		if PORTAL_ROLE not in [r.role for r in u.roles]:
			u.append("roles", {"role": PORTAL_ROLE})
		u.enabled = 1
		u.flags.ignore_permissions = True
		u.save()
		return u.name, False
	first, _sp, last = full_name.partition(" ")
	u = frappe.get_doc({"doctype": "User", "email": email, "first_name": first or full_name, "last_name": last,
						"user_type": "Website User", "send_welcome_email": 0, "roles": [{"role": PORTAL_ROLE}]})
	u.flags.ignore_permissions = True
	u.insert()
	if u.user_type != "Website User":
		# only happens if someone gave the Customer role desk access - never hand customers a desk login
		frappe.throw(_("The Customer role has desk access on this site, so {0} would get a staff login. "
					   "Untick Desk Access on Role 'Customer' first.").format(email))
	return u.name, True


def _link_contact(cust, contact, email, user, full_name):
	if contact:
		c = frappe.get_doc("Contact", contact)
		if c.user != user:
			c.user = user
			c.flags.ignore_permissions = True
			c.save()
		return c.name
	first, _sp, last = full_name.partition(" ")
	c = frappe.get_doc({"doctype": "Contact", "first_name": first or full_name, "last_name": last, "user": user,
						"email_ids": [{"email_id": email, "is_primary": 1}],
						"links": [{"link_doctype": "Customer", "link_name": cust.name}]})
	c.flags.ignore_permissions = True
	c.insert()
	return c.name


# =========================================================================== tickets
def _portal_user(user=None):
	user = user or frappe.session.user
	return user not in ("Guest", "Administrator") and frappe.db.get_value("User", user, "user_type") == "Website User"


def _demo_company(company):
	from sibyl_app.demo import COMPANIES

	return company in COMPANIES


def issue_before_insert(doc, method=None):
	"""Tickets raised in the portal: who raised them, for which customer, under the main company."""
	if _portal_user():
		user = frappe.session.user
		doc.via_customer_portal = 1
		doc.raised_by = frappe.db.get_value("User", user, "email") or user
		doc.status = doc.status or "Open"
		contact = frappe.db.get_value("Contact", {"user": user}, "name")
		if contact:
			doc.contact = contact
			doc.customer = frappe.get_doc("Contact", contact).get_link_for("Customer") or doc.customer
	if not doc.company:
		doc.company = frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_default("company")


def issue_after_insert(doc, method=None):
	if not doc.via_customer_portal or _demo_company(doc.company):
		return
	ctx = _ctx(doc)
	try:
		owner = _support_owner()
		if owner:
			frappe.get_doc({"doctype": "ToDo", "allocated_to": owner, "reference_type": "Issue", "reference_name": doc.name,
							"description": "Portal ticket from %s: %s" % (escape_html(ctx["customer"] or ctx["email"]), escape_html(doc.subject)),
							"priority": "High" if doc.priority == "High" else "Medium", "assigned_by": "Administrator",
							"date": frappe.utils.add_days(frappe.utils.nowdate(), 1)}).insert(ignore_permissions=True)
		_staff_mail(ctx, "new")
	except Exception:
		frappe.log_error(title="Sibyl support portal: staff alert failed for " + doc.name)
	try:
		_customer_mail(T_ACK, ctx, doc)
	except Exception:
		frappe.log_error(title="Sibyl support portal: acknowledgement failed for " + doc.name)


def issue_on_update(doc, method=None):
	"""Status emails: On Hold / Resolved / Closed reach the customer (a staff reply is already an email)."""
	before = doc.get_doc_before_save()
	if not before or before.status == doc.status or doc.status not in STATUS_MAILS:
		return
	if _demo_company(doc.company) or doc.flags.sibyl_no_status_mail:
		return
	try:
		ctx = _ctx(doc)
		ctx["previous_status"] = before.status
		if _customer_mail(T_STATUS, ctx, doc, timeline=False):
			doc.add_comment("Info", _("Status email ({0}) sent to {1}").format(doc.status, ctx["email"]))
	except Exception:
		frappe.log_error(title="Sibyl support portal: status email failed for " + doc.name)


def comment_after_insert(doc, method=None):
	"""A customer's comment on their ticket in the portal reopens it and alerts support."""
	if doc.reference_doctype != "Issue" or doc.comment_type != "Comment" or not _portal_user():
		return
	_customer_followup(doc.reference_name, doc.content)


def communication_after_insert(doc, method=None):
	"""A customer's emailed reply on a ticket alerts support (frappe already reopens the ticket)."""
	if doc.reference_doctype != "Issue" or doc.sent_or_received != "Received" or doc.communication_type != "Communication":
		return
	issue = frappe.db.get_value("Issue", doc.reference_name, ["creation", "via_customer_portal", "sibyl_web_submission"], as_dict=True)
	if not issue or frappe.utils.time_diff_in_seconds(doc.creation, issue.creation) < 60:
		return  # the ticket's own first message, not a follow-up
	_customer_followup(doc.reference_name, doc.content, reopen=False)


def _customer_followup(issue_name, content, reopen=True):
	issue = frappe.get_doc("Issue", issue_name)
	if _demo_company(issue.company):
		return
	try:
		if reopen and issue.status != "Open":
			issue.db_set("status", "Open")
		ctx = _ctx(issue)
		ctx["followup_html"] = content or ""
		_staff_mail(ctx, "followup")
	except Exception:
		frappe.log_error(title="Sibyl support portal: follow-up alert failed for " + issue_name)


# =========================================================================== mail
def _support_owner():
	try:
		return frappe.db.get_single_value("Sibyl Website Settings", "support_owner")
	except Exception:
		return None


def _ctx(doc):
	import re

	email = (frappe.utils.parse_addr(doc.raised_by or "")[1] or "").lower()
	contact_name = doc.contact and frappe.db.get_value("Contact", doc.contact, "first_name")
	first = (contact_name or frappe.db.get_value("User", email, "first_name") or email.split("@")[0]).strip()
	try:
		s = frappe.get_cached_doc("Sibyl Website Settings")
		site = {"site_url": (s.site_url or "https://sibyl.pk").rstrip("/"), "public_phone": s.public_phone,
				"whatsapp_url": ("https://wa.me/" + re.sub(r"\D", "", s.whatsapp_no)) if s.whatsapp_no else ""}
	except Exception:
		site = {"site_url": "https://sibyl.pk", "public_phone": "", "whatsapp_url": ""}
	return site | {
		"reference": doc.name, "subject": doc.subject, "status": doc.status, "priority": doc.priority or "",
		"issue_type": doc.issue_type or "", "customer": doc.customer or "", "email": email, "first_name": first,
		"description_html": doc.description or "", "ticket_url": get_url("/issues/%s" % doc.name),
		"tickets_url": get_url("/issues"), "staff_url": get_url_to_form("Issue", doc.name),
		"company": doc.company or frappe.db.get_default("company") or "Sibyl Technologies",
		"resolution_html": doc.get("resolution_details") or "", "previous_status": "", "followup_html": "",
	}


def _render(template, ctx):
	t = frappe.get_cached_doc("Email Template", template)
	body = t.response_html if t.use_html else t.response
	return frappe.render_template(t.subject or "", ctx).strip(), frappe.render_template(body or "", ctx)


def _customer_mail(template, ctx, doc, timeline=True):
	if not ctx["email"] or not frappe.db.exists("Email Template", template):
		return False
	from sibyl_app.website_forms import _sender

	subject, body = _render(template, ctx)
	if timeline:
		# on the ticket's timeline, so the customer's reply threads back into the ticket
		# _make: the system sends this, not the logged-in customer (make() would check *their* email permission)
		from frappe.core.doctype.communication.email import _make

		status = doc.status
		_make(doctype="Issue", name=doc.name, subject=subject, content=body, recipients=ctx["email"], sender=_sender(),
			 send_email=True, communication_medium="Email", sent_or_received="Sent", print_letterhead=False)
		if frappe.db.get_value("Issue", doc.name, "status") != status:
			frappe.db.set_value("Issue", doc.name, "status", status, update_modified=False)
	else:
		frappe.sendmail(recipients=[ctx["email"]], sender=_sender(), subject=subject, message=body,
						reference_doctype="Issue", reference_name=doc.name)
	return True


def _staff_mail(ctx, kind):
	from sibyl_app.website_forms import _sender

	recipients = []
	owner = _support_owner()
	if owner:
		recipients.append(frappe.db.get_value("User", owner, "email"))
	try:
		recipients += frappe.get_single("Sibyl Website Settings").alert_addresses()
	except Exception:
		pass
	recipients = list(dict.fromkeys(r.lower() for r in recipients if r))
	if not recipients or not frappe.db.exists("Email Template", T_STAFF):
		return
	ctx = dict(ctx, alert_kind=kind, alert_title="Customer follow-up on" if kind == "followup" else "New portal ticket")
	subject, body = _render(T_STAFF, ctx)
	frappe.sendmail(recipients=recipients, sender=_sender(), subject=subject, message=body,
					reference_doctype="Issue", reference_name=ctx["reference"])


# =========================================================================== setup (migrate)
def setup():
	from sibyl_app.website_setup import SIGN

	for name, (subject, body) in _templates(SIGN).items():
		if not frappe.db.exists("Email Template", name):
			frappe.get_doc({"doctype": "Email Template", "name": name, "subject": subject, "use_html": 1,
							"response_html": body}).insert(ignore_permissions=True)
	if frappe.db.exists("DocType", "Issue Type"):
		for t in ISSUE_TYPES:
			if not frappe.db.exists("Issue Type", t):
				frappe.get_doc({"doctype": "Issue Type", "__newname": t, "name": t}).insert(ignore_permissions=True)
	_web_form()


def _web_form():
	"""Portal ticket form: ask for the type of problem too (standard form is subject/description/priority/attachment)."""
	if not frappe.db.exists("Web Form", "issues"):
		return
	# written straight to the database: saving a standard Web Form in developer mode would export it into
	# ERPNext's own files. Re-applied on every migrate, so an ERPNext update of the form can't drop it.
	rows = frappe.get_all("Web Form Field", filters={"parent": "issues", "parenttype": "Web Form"},
						  fields=["name", "fieldname", "idx"], order_by="idx")
	if "issue_type" not in [r.fieldname for r in rows]:
		at = next((r.idx for r in rows if r.fieldname == "description"), len(rows) + 1)
		for r in rows:
			if r.idx >= at:
				frappe.db.set_value("Web Form Field", r.name, "idx", r.idx + 1, update_modified=False)
		frappe.get_doc({"doctype": "Web Form Field", "parent": "issues", "parenttype": "Web Form", "parentfield": "web_form_fields",
						"idx": at, "fieldname": "issue_type", "fieldtype": "Link", "options": "Issue Type",
						"label": "Type of request", "reqd": 0, "allow_read_on_all_link_options": 1}).db_insert()
	if not frappe.db.get_value("Web Form", "issues", "introduction_text"):
		frappe.db.set_value("Web Form", "issues", {
			"introduction_text": "Describe the problem or request. Our support team is notified at once, and you will get "
								 "updates by email and here under Issues.",
			"success_message": "Thank you - your ticket is open. We have emailed you the ticket number.",
		}, update_modified=False)
	frappe.clear_cache(doctype="Web Form")


def _templates(sign):
	button = ('<p style="margin:22px 0;"><a href="{{ ticket_url }}" style="background:#14213d;color:#ffffff;padding:10px 18px;'
			  'border-radius:6px;text-decoration:none;font-weight:600;">View ticket {{ reference }}</a></p>')
	details = ('<table style="border-collapse:collapse;font-size:13px;margin:10px 0;">'
			   '<tr><td style="padding:4px 12px 4px 0;color:#667085;">Ticket</td><td><b>{{ reference }}</b></td></tr>'
			   '<tr><td style="padding:4px 12px 4px 0;color:#667085;">Subject</td><td>{{ subject }}</td></tr>'
			   '<tr><td style="padding:4px 12px 4px 0;color:#667085;">Status</td><td><b>{{ status }}</b></td></tr>'
			   '{% if priority %}<tr><td style="padding:4px 12px 4px 0;color:#667085;">Priority</td><td>{{ priority }}</td></tr>{% endif %}'
			   '{% if issue_type %}<tr><td style="padding:4px 12px 4px 0;color:#667085;">Type</td><td>{{ issue_type }}</td></tr>{% endif %}'
			   '</table>')
	return {
		T_ACK: (
			"Ticket {{ reference }} received: {{ subject }}",
			'<p>Dear {{ first_name }},</p>'
			'<p>Thank you for contacting {{ company }} support. Your ticket is open and our team has been notified.</p>'
			+ details + button +
			'<p>You can follow the ticket and add details any time from the customer portal under <b>Issues</b>, '
			'or simply reply to this email.</p>' + sign,
		),
		T_STATUS: (
			"Ticket {{ reference }} is now {{ status }}: {{ subject }}",
			'<p>Dear {{ first_name }},</p>'
			'{% if status == "Resolved" %}<p>Good news - we have resolved your ticket.</p>'
			'{% elif status == "Closed" %}<p>Your ticket has been closed.</p>'
			'{% else %}<p>Your ticket is on hold for the moment - we will update you as soon as it moves again.</p>{% endif %}'
			+ details +
			'{% if resolution_html %}<div style="margin:12px 0;padding:12px 14px;background:#f5f7fa;border-left:3px solid #14213d;">'
			'{{ resolution_html }}</div>{% endif %}'
			+ button +
			'<p>{% if status in ("Resolved", "Closed") %}If the problem is not solved, reply to this email or add a comment '
			'on the ticket and we will reopen it.{% else %}Reply to this email if you have anything to add.{% endif %}</p>' + sign,
		),
		T_STAFF: (
			"{{ alert_title }} {{ reference }}: {{ subject }}{% if customer %} ({{ customer }}){% endif %}",
			'{% if alert_kind == "followup" %}<p><b>{{ customer or email }}</b> added to ticket <b>{{ reference }}</b> '
			'and it is open again.</p>'
			'<div style="margin:12px 0;padding:12px 14px;background:#f5f7fa;border-left:3px solid #14213d;">{{ followup_html }}</div>'
			'{% else %}<p><b>{{ customer or email }}</b> raised a ticket in the customer portal.</p>' + details +
			'<div style="margin:12px 0;padding:12px 14px;background:#f5f7fa;border-left:3px solid #14213d;">{{ description_html }}</div>'
			'{% endif %}'
			'<p style="margin-top:20px;"><a class="btn btn-primary" href="{{ staff_url }}">Open {{ reference }}</a></p>'
			'<p style="color:#667085;font-size:12px;">Reply from the ticket\'s timeline (it emails {{ email }}), and set the status - '
			'On Hold, Resolved and Closed are emailed to the customer automatically.</p>',
		),
	}

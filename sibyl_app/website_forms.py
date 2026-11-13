"""Website forms (sibyl.pk) -> ERPNext.

The website's PHP form handlers post every submission here, server to server, with the shared
website key (Sibyl Website Settings). Each one becomes the right record:

    contact / service / demo / project / Odoo / partnership enquiries  -> Lead
    support requests                                                     -> Issue
    job applications and careers enquiries (with the CV)                 -> Job Applicant
    newsletter sign-ups                                                  -> Email Group Member

What the visitor wrote is filed as a received email on that record's timeline, the automatic
reply goes out from the default outgoing account (autobot@sibyl.pk) as a sent email on the same
timeline, so replying from the record and the visitor's answers stay in one thread. The owner gets
a To Do and an alert. Everything is logged in Sibyl Web Submission.

If anything fails, the submission is still logged (Failed) and the website is told, so it falls
back to plain email and nothing is lost."""
import base64
import hmac
import json
import re
from email.utils import formataddr

import frappe
from frappe import _
from frappe.rate_limiter import rate_limit
from frappe.utils import cint, escape_html, get_url_to_form, now_datetime, validate_email_address

SETTINGS = "Sibyl Website Settings"
LOG = "Sibyl Web Submission"

# (form, kind) -> (label in ERPNext, target)
ROUTES = {
	("contact", "demo"): ("Demo Request", "Lead"),
	("contact", "sales"): ("Sales Enquiry", "Lead"),
	("contact", "support"): ("Support Request", "Issue"),
	("contact", "partnership"): ("Partnership Enquiry", "Lead"),
	("contact", "odoo"): ("Odoo Enquiry", "Lead"),
	("contact", "careers"): ("Careers Enquiry", "Job Applicant"),
	("contact", "other"): ("General Enquiry", "Lead"),
	("inquiry", "inquiry"): ("Service Enquiry", "Lead"),
	("inquiry", "demo"): ("Demo Request", "Lead"),
	("inquiry", "project"): ("Project Enquiry", "Lead"),
	("inquiry", "odoo"): ("Odoo Enquiry", "Lead"),
	("inquiry", "support"): ("Support Request", "Issue"),
	("inquiry", "apply"): ("Job Application", "Job Applicant"),
	("career", ""): ("Job Application", "Job Applicant"),
	("newsletter", ""): ("Newsletter", "Email Group Member"),
}
PRODUCT_ENQUIRY = {"Demo Request", "Sales Enquiry", "Odoo Enquiry"}
CV_TYPES = {"pdf", "doc", "docx", "odt", "rtf", "txt"}
MAX_TEXT = 5000


class Rejected(Exception):
	"""A submission refused on purpose (bad input, too many) - told to the visitor as is."""


# --------------------------------------------------------------------------- entry point
@frappe.whitelist(allow_guest=True, methods=["POST"])
@rate_limit(limit=300, seconds=3600)
def submit(form=None, kind=None, fields=None, files=None, meta=None):
	"""Called by the website. Returns {ok, message, reference} - ok False means "fall back to email"."""
	settings = frappe.get_cached_doc(SETTINGS)
	if not settings.enabled:
		return {"ok": False, "message": "disabled"}
	key = settings.get_password("site_key", raise_exception=False) or ""
	sent = frappe.get_request_header("X-Sibyl-Key") or ""
	if not key or not hmac.compare_digest(key.encode(), sent.encode()):
		frappe.local.response.http_status_code = 403
		return {"ok": False, "message": "forbidden"}

	fields = _as_dict(fields)
	meta = _as_dict(meta)
	files = files if isinstance(files, list) else (json.loads(files) if isinstance(files, str) and files else [])
	form = (form or "").strip().lower()
	kind = (kind or "").strip().lower()
	route = ROUTES.get((form, kind)) or ROUTES.get((form, ""))
	if not route and form in ("contact", "inquiry"):
		route = ("General Enquiry", "Lead")

	user = frappe.session.user
	frappe.set_user("Administrator")
	try:
		return _handle(settings, route, form, kind, fields, files, meta)
	finally:
		frappe.set_user(user)


def _handle(settings, route, form, kind, fields, files, meta):
	log = frappe.get_doc({
		"doctype": LOG, "status": "Received", "submitted_on": now_datetime(),
		"form_type": route[0] if route else None,
		"full_name": _clip(fields.get("name"), 140), "email": _clip(fields.get("email"), 140),
		"phone": _clip(fields.get("phone"), 40), "company_name": _clip(fields.get("company"), 140),
		"topic": _clip(fields.get("topic") or fields.get("position") or fields.get("product"), 140),
		"message": _clip(fields.get("message"), MAX_TEXT),
		"ip_address": _clip(meta.get("ip"), 60), "page_url": _clip(meta.get("page"), 140),
		"user_agent": _clip(meta.get("user_agent"), 500),
		"payload": json.dumps({"form": form, "kind": kind, "fields": fields,
							   "files": [{"name": f.get("name"), "size": len(f.get("content") or "")} for f in files]},
							  indent=1, ensure_ascii=False)[:20000],
	})
	log.insert(ignore_permissions=True)
	frappe.db.set_single_value(SETTINGS, "last_submission", log.submitted_on, update_modified=False)
	frappe.db.commit()  # the log survives whatever happens next

	try:
		if not route:
			raise Rejected(_("Unknown form."))
		_check_input(settings, fields, meta, route)
		ref_dt, ref_name, message = HANDLERS[route[1]](settings, route[0], fields, files, log)
		log.db_set({"status": "Processed", "reference_doctype": ref_dt, "reference_name": ref_name}, update_modified=False)
		frappe.db.commit()
	except (Rejected, frappe.ValidationError) as e:
		# something the visitor can fix (too long, missing, invalid, closed position...): tell them what, keep nothing half-made
		frappe.db.rollback()  # back to the committed log
		frappe.clear_messages()
		visitor_msg = str(e) if isinstance(e, Rejected) else _visitor_message(e)
		log.reload()
		log.db_set({"status": "Rejected", "error": visitor_msg + ("" if isinstance(e, Rejected) else "\n\n" + frappe.get_traceback()[-4000:])},
				   update_modified=False)
		frappe.db.commit()
		return {"ok": True, "rejected": True, "message": visitor_msg}
	except Exception:
		frappe.db.rollback()
		log.reload()
		log.db_set({"status": "Failed", "error": frappe.get_traceback()[-8000:]}, update_modified=False)
		frappe.db.commit()
		frappe.log_error(title="Sibyl website form failed: " + log.name)
		_alert_failure(settings, log)
		return {"ok": False, "message": "failed", "reference": log.name}

	# side effects after the records are safely committed - never undo the submission
	_after(settings, route, fields, log, ref_dt, ref_name)
	return {"ok": True, "message": message, "reference": ref_name}


# --------------------------------------------------------------------------- checks
# what each website field is called on the form, and the most ERPNext can store
LIMITS = {
	"name": ("Full Name", 140), "email": ("Email Address", 140), "phone": ("Phone Number", 40),
	"company": ("Company / City", 140), "location": ("City / Location", 140), "topic": ("Topic", 140),
	"position": ("Position", 140), "product": ("Product of Interest", 140), "budget": ("Budget", 140),
	"timeline": ("Timeline", 140), "experience": ("Years of Experience", 140), "salary": ("Expected Salary", 140),
	"salary_expectation": ("Expected Salary", 140), "linkedin": ("LinkedIn / Portfolio URL", 1000),
	"resume_note": ("LinkedIn / Portfolio URL", 1000), "message": ("Message", MAX_TEXT),
}
# ERPNext field labels -> what the visitor sees on the website form
SITE_LABELS = {"Link": "LinkedIn / Portfolio URL", "Applicant Name": "Full Name", "Phone Number": "Phone Number",
			   "Email Address": "Email Address", "Mobile No": "Phone Number", "Organization Name": "Company",
			   "Company Name": "Company", "Subject": "Message subject", "First Name": "Full Name", "Last Name": "Full Name"}


def _too_long(label, n, limit):
	return _("Your {0} is too long ({1} characters, the most we can take is {2}). Please shorten it and send the form again.").format(
		label, n, limit)


def _visitor_message(e):
	"""Turn an ERPNext validation error into a plain sentence the visitor can act on."""
	text = frappe.utils.strip_html(str(e) or "").strip()
	label = re.search(r"<strong>(.*?)</strong>", str(e))
	label = SITE_LABELS.get(label.group(1), label.group(1)) if label else None
	if isinstance(e, frappe.CharacterLengthExceededError) or "will get truncated" in text:
		limit = re.search(r"allowed is (\d+)", text)
		return _("Your {0} is too long (the most we can take is {1} characters). Please shorten it and send the form again.").format(
			label or _("entry"), limit.group(1) if limit else 140)
	if isinstance(e, frappe.MandatoryError):
		return _("Please fill in {0} and send the form again.").format(label or _("all required fields"))
	if isinstance(e, frappe.InvalidEmailAddressError):
		return _("Please enter a valid email address and send the form again.")
	if "closed Job Opening" in text:
		return _("Sorry, this position is no longer open. You can still send us a general application from the Careers page.")
	if "already applied" in text.lower():
		return _("You have already applied for this position - thank you. We will be in touch; there is no need to apply again.")
	text = re.sub(r"^[\w ]+ [^:]{1,80}: ", "", text)  # drop the "Job Applicant x@y.z: " prefix
	return _("We couldn't accept your form: {0} Please correct it and send again, or email us if this keeps happening.").format(
		text.rstrip(".") + "." if text else "")


def _check_input(settings, fields, meta, route):
	for key, (label, limit) in LIMITS.items():
		value = (fields.get(key) or "").strip()
		if len(value) > limit:
			raise Rejected(_too_long(label, len(value), limit))
	name, email = (fields.get("name") or "").strip(), (fields.get("email") or "").strip()
	if route[1] != "Email Group Member" and not name:
		raise Rejected(_("Please enter your name."))
	if not email or not validate_email_address(email):
		raise Rejected(_("Please enter a valid email address."))
	if route[1] not in ("Email Group Member",) and not (fields.get("message") or "").strip():
		raise Rejected(_("Please enter a message."))
	ip = (meta.get("ip") or "").strip()
	if ip:
		key = "sibyl_web_rl:%s:%s" % (ip, now_datetime().strftime("%Y%m%d%H"))
		hits = frappe.cache.incr(key)
		if hits == 1:
			frappe.cache.expire(key, 3700)
		if hits > cint(settings.max_per_hour or 5):
			raise Rejected(_("Too many submissions from your connection. Please try again in an hour."))


# --------------------------------------------------------------------------- records
def _lead(settings, label, fields, files, log):
	email = fields["email"].strip().lower()
	name = frappe.db.get_value("Lead", {"email_id": email}, "name", order_by="creation desc")
	lead = frappe.get_doc("Lead", name) if name else frappe.new_doc("Lead")
	if lead.is_new():
		first, _sp, last = _clip(fields.get("name"), 140).partition(" ")
		lead.update({
			"first_name": first, "last_name": last, "email_id": email, "status": "Lead", "type": "Client",
			"company": frappe.db.get_default("company"),
		})
		if frappe.db.exists("UTM Source", "Website"):
			lead.utm_source = "Website"
		if settings.lead_owner:
			lead.lead_owner = settings.lead_owner
	for field, value in (("mobile_no", fields.get("phone")), ("company_name", fields.get("company"))):
		if value and not lead.get(field):
			lead.set(field, _clip(value, 140))
	lead.request_type = "Product Enquiry" if label in PRODUCT_ENQUIRY else "Request for Information"
	lead.update({
		"sibyl_web_form": label, "sibyl_web_topic": _clip(fields.get("topic"), 140),
		"sibyl_web_product": _clip(fields.get("product"), 140), "sibyl_web_budget": _clip(fields.get("budget"), 140),
		"sibyl_web_timeline": _clip(fields.get("timeline"), 140), "sibyl_web_page": _clip(fields.get("page"), 140),
		"sibyl_web_submission": log.name,
	})
	lead.flags.ignore_permissions = True
	lead.flags.ignore_mandatory = True
	lead.save()
	_received(lead.doctype, lead.name, label, fields, log)
	return lead.doctype, lead.name, _("Thank you. A specialist will contact you within 24 hours. Please check your inbox for our confirmation.")


def _issue(settings, label, fields, files, log):
	email = fields["email"].strip().lower()
	topic = fields.get("topic") or fields.get("product")
	issue = frappe.new_doc("Issue")
	issue.update({
		"subject": _clip("%s%s - %s" % (label, (" (%s)" % topic) if topic else "", fields.get("company") or fields.get("name")), 140),
		"raised_by": email, "description": _summary_html(label, fields), "company": frappe.db.get_default("company"),
		"status": "Open", "sibyl_web_submission": log.name,
	})
	contact = frappe.db.get_value("Contact Email", {"email_id": email, "parenttype": "Contact"}, "parent")
	if contact:
		issue.contact = contact
		customer = frappe.db.get_value("Dynamic Link", {"parenttype": "Contact", "parent": contact, "link_doctype": "Customer"}, "link_name")
		if customer:
			issue.customer = customer
	lead = frappe.db.get_value("Lead", {"email_id": email}, "name")
	if lead:
		issue.lead = lead
	issue.flags.ignore_permissions = True
	issue.flags.ignore_mandatory = True
	issue.insert()
	_received(issue.doctype, issue.name, label, fields, log)
	return issue.doctype, issue.name, _("Thank you. Your support ticket {0} is open and our team will reply by email.").format(issue.name)


def _applicant(settings, label, fields, files, log):
	email = fields["email"].strip().lower()
	position = (fields.get("position") or fields.get("topic") or "").strip()
	if position.lower() in ("", "general application", "general inquiry", "careers"):
		position = ""
	opening = _job_opening(position) if position else None
	links = (fields.get("linkedin") or fields.get("resume_note") or "").strip()
	letter = _clip(fields.get("message"), MAX_TEXT)
	if links and len(_url(links)) != len(links):  # several links / too long for the 140-character link field
		letter = (letter + "\n\nLinks: " + links).strip()[:MAX_TEXT + 600]
	app = frappe.new_doc("Job Applicant")
	app.update({
		"applicant_name": _clip(fields.get("name"), 140), "email_id": email, "phone_number": _clip(fields.get("phone"), 40),
		"job_title": opening, "designation": frappe.db.get_value("Job Opening", opening, "designation") if opening else None,
		"status": "Open", "cover_letter": letter,
		"resume_link": _url(links),
		"sibyl_web_position": position or _("General application"),
		"sibyl_web_experience": _clip(fields.get("experience"), 140),
		"sibyl_web_location": _clip(fields.get("company") or fields.get("location"), 140),
		"sibyl_web_expected_salary": _clip(fields.get("salary") or fields.get("salary_expectation"), 140),
		"sibyl_web_submission": log.name,
	})
	if frappe.db.exists("Job Applicant Source", "Website Listing"):
		app.source = "Website Listing"
	salary = _amount(fields.get("salary") or fields.get("salary_expectation"))
	if salary:
		app.currency = frappe.db.get_value("Company", frappe.db.get_default("company"), "default_currency") or "PKR"
		app.lower_range = app.upper_range = salary
	app.flags.ignore_permissions = True
	app.flags.ignore_mandatory = True
	app.insert()
	cv = next((f for f in files if f.get("field") in ("cv", "resume")), None) or (files[0] if files else None)
	if cv:
		frappe.db.savepoint("sibyl_cv")
		try:
			url = _save_file(settings, cv, app.doctype, app.name)
		except Rejected:
			raise
		except Exception:
			# a damaged file (e.g. a PDF Frappe can't read) must never cost us the application
			frappe.db.rollback(save_point="sibyl_cv")
			frappe.local.message_log = []
			url = None
			app.add_comment("Comment", _("The CV uploaded on the website ({0}) could not be stored - the file looks damaged. "
										 "Please ask the applicant to send it again by replying to them.").format(escape_html(cv.get("name") or "")))
		if url:
			app.db_set("resume_attachment", url, update_modified=False)
	_received(app.doctype, app.name, label, fields, log)
	return app.doctype, app.name, _("Application received. Our hiring team will review it and contact you within 3-5 business days.")


def _subscriber(settings, label, fields, files, log):
	email = fields["email"].strip().lower()
	group = settings.newsletter_group or "Sibyl Newsletter"
	if not frappe.db.exists("Email Group", group):
		frappe.get_doc({"doctype": "Email Group", "title": group}).insert(ignore_permissions=True)
	existing = frappe.db.get_value("Email Group Member", {"email_group": group, "email": email}, ["name", "unsubscribed"], as_dict=True)
	if existing:
		if existing.unsubscribed:
			frappe.db.set_value("Email Group Member", existing.name, "unsubscribed", 0)
			log.flags.welcome = True
			return "Email Group Member", existing.name, _("Welcome back! You're subscribed again.")
		log.flags.welcome = False
		return "Email Group Member", existing.name, _("You're already subscribed. Thank you!")
	member = frappe.get_doc({"doctype": "Email Group Member", "email_group": group, "email": email})
	member.insert(ignore_permissions=True)
	log.flags.welcome = True
	return member.doctype, member.name, _("Subscribed! Welcome to the Sibyl community.")


HANDLERS = {"Lead": _lead, "Issue": _issue, "Job Applicant": _applicant, "Email Group Member": _subscriber}


def _job_opening(title):
	"""The open Job Opening for a position on the website - created the first time someone applies."""
	name = frappe.db.get_value("Job Opening", {"job_title": title, "status": "Open"}, "name")
	if name:
		return name
	if frappe.db.get_value("Job Opening", {"job_title": title}, "name"):
		return None  # closed on purpose: keep the application, just not against the closed opening
	designation = title if frappe.db.exists("Designation", title) else None
	if not designation:
		frappe.get_doc({"doctype": "Designation", "designation_name": title}).insert(ignore_permissions=True)
		designation = title
	opening = frappe.get_doc({
		"doctype": "Job Opening", "job_title": title, "designation": designation, "status": "Open",
		"company": frappe.db.get_default("company"), "publish": 0,
		"description": _("Created from the website careers page."),
	})
	opening.flags.ignore_mandatory = True
	opening.insert(ignore_permissions=True)
	return opening.name


def _save_file(settings, f, doctype, name):
	fname = re.sub(r"[^\w.\- ]+", "_", (f.get("name") or "cv").strip())[:120] or "cv"
	ext = fname.rsplit(".", 1)[-1].lower() if "." in fname else ""
	if ext not in CV_TYPES:
		raise Rejected(_("Please upload your CV as PDF, Word, ODT, RTF or text."))
	try:
		content = base64.b64decode(f.get("content") or "", validate=True)
	except Exception:
		raise Rejected(_("The CV upload was damaged. Please try again."))
	if not content:
		return None
	if len(content) > cint(settings.max_file_mb or 5) * 1024 * 1024:
		raise Rejected(_("Your CV is larger than {0} MB.").format(cint(settings.max_file_mb or 5)))
	doc = frappe.get_doc({
		"doctype": "File", "file_name": fname, "content": content, "is_private": 1,
		"attached_to_doctype": doctype, "attached_to_name": name, "attached_to_field": "resume_attachment",
	})
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.file_url


# --------------------------------------------------------------------------- timeline + emails
def _received(doctype, name, label, fields, log):
	"""What the visitor wrote, filed as an email received on the record (reply from there)."""
	account = _account()
	comm = frappe.get_doc({
		"doctype": "Communication", "communication_type": "Communication", "communication_medium": "Email",
		"sent_or_received": "Received", "status": "Open", "seen": 0,
		"subject": _subject(label, fields), "content": _summary_html(label, fields),
		"sender": fields["email"].strip().lower(), "sender_full_name": _clip(fields.get("name"), 140) or fields["email"],
		"recipients": account.email_id if account else None, "email_account": account.name if account else None,
		"reference_doctype": doctype, "reference_name": name,
	})
	comm.flags.ignore_permissions = True
	comm.insert()
	log.flags.received_comm = comm.name


def _after(settings, route, fields, log, ref_dt, ref_name):
	label, target = route
	ctx = _context(settings, label, fields, ref_dt, ref_name, log)
	try:
		owner = {"Lead": settings.lead_owner, "Issue": settings.support_owner, "Job Applicant": settings.hr_owner}.get(target)
		if owner and target != "Email Group Member" and not frappe.db.exists(
			"ToDo", {"allocated_to": owner, "reference_type": ref_dt, "reference_name": ref_name, "status": "Open"}):
			frappe.get_doc({
				"doctype": "ToDo", "allocated_to": owner, "reference_type": ref_dt, "reference_name": ref_name,
				"description": "%s from %s - reply from the record's timeline." % (label, escape_html(ctx["full_name"])),
				"priority": "High" if target == "Issue" else "Medium", "assigned_by": "Administrator",
				"date": frappe.utils.add_days(frappe.utils.nowdate(), 1),
			}).insert(ignore_permissions=True)
		_staff_alert(settings, ctx, owner)
	except Exception:
		frappe.log_error(title="Sibyl website form: staff alert failed for " + log.name)
	if settings.auto_reply and not (target == "Email Group Member" and not log.flags.welcome):
		try:
			template = {"Lead": settings.enquiry_template, "Issue": settings.support_template,
						"Job Applicant": settings.application_template, "Email Group Member": settings.newsletter_template}.get(target)
			if template and _reply(template, ctx, fields["email"].strip().lower(), ref_dt, ref_name, target):
				log.db_set("auto_reply_sent", 1, update_modified=False)
		except Exception:
			frappe.log_error(title="Sibyl website form: automatic reply failed for " + log.name)
	frappe.db.commit()


def _reply(template, ctx, to, ref_dt, ref_name, target):
	subject, body = _render(template, ctx)
	if not body:
		return False
	sender = _sender()
	if target == "Email Group Member":
		frappe.sendmail(recipients=[to], sender=sender, subject=subject, message=body,
						reference_doctype="Email Group", reference_name=ctx["newsletter_group"])
		return True
	from frappe.core.doctype.communication.email import make

	make(doctype=ref_dt, name=ref_name, subject=subject, content=body, recipients=to, sender=sender,
		 send_email=True, communication_medium="Email", sent_or_received="Sent", print_letterhead=False)
	return True


def _staff_alert(settings, ctx, owner):
	recipients = []
	if owner:
		email = frappe.db.get_value("User", owner, "email")
		if email:
			recipients.append(email)
	recipients += settings.alert_addresses()
	recipients = list(dict.fromkeys(r.lower() for r in recipients if r))
	if not recipients or not settings.alert_template:
		return
	subject, body = _render(settings.alert_template, ctx)
	frappe.sendmail(recipients=recipients, sender=_sender(), subject=subject, message=body,
					reference_doctype=ctx["reference_doctype"], reference_name=ctx["reference"])


def _alert_failure(settings, log):
	try:
		recipients = [frappe.db.get_value("User", u, "email") for u in (settings.lead_owner, settings.hr_owner, settings.support_owner) if u]
		recipients = list(dict.fromkeys([r for r in recipients + settings.alert_addresses() if r]))
		if recipients:
			frappe.sendmail(recipients=recipients, sender=_sender(),
							subject="Website form could not be filed: %s (%s)" % (log.full_name or log.email, log.name),
							message="<p>A website submission could not be turned into a record. It is saved in "
									"<a href='%s'>%s</a> with the error, and the website emailed it to the public inbox instead.</p>"
									% (get_url_to_form(LOG, log.name), log.name),
							reference_doctype=LOG, reference_name=log.name)
			frappe.db.commit()
	except Exception:
		frappe.log_error(title="Sibyl website form: failure alert failed")


def _render(template, ctx):
	t = frappe.get_cached_doc("Email Template", template)
	body = t.response_html if t.use_html else t.response
	return frappe.render_template(t.subject or "", ctx).strip(), frappe.render_template(body or "", ctx)


def _context(settings, label, fields, ref_dt, ref_name, log):
	name = _clip(fields.get("name"), 140) or (fields.get("email") or "").split("@")[0]
	wa = re.sub(r"\D", "", settings.whatsapp_no or "")
	return {
		"form_label": label, "full_name": name, "first_name": name.split(" ")[0] if name else "",
		"email": fields.get("email"), "phone": fields.get("phone"), "company_name": fields.get("company"),
		"topic": fields.get("topic") or fields.get("position") or fields.get("product") or "",
		"reference": ref_name, "reference_doctype": ref_dt, "reference_url": get_url_to_form(ref_dt, ref_name),
		"submission": log.name, "summary_html": _summary_html(label, fields),
		"company": frappe.db.get_default("company") or "Sibyl Technologies",
		"site_url": (settings.site_url or "https://sibyl.pk").rstrip("/"), "public_email": settings.public_email,
		"public_phone": settings.public_phone, "whatsapp_url": ("https://wa.me/" + wa) if wa else "",
		"newsletter_group": settings.newsletter_group or "Sibyl Newsletter",
	}


ROWS = (("name", "Name"), ("email", "Email"), ("phone", "Phone"), ("company", "Company / City"), ("topic", "Topic"),
		("position", "Position"), ("product", "Product"), ("budget", "Budget"), ("timeline", "Timeline"),
		("experience", "Experience"), ("salary", "Expected salary"), ("salary_expectation", "Expected salary"),
		("linkedin", "LinkedIn / portfolio"), ("resume_note", "LinkedIn / portfolio"))


def _summary_html(label, fields):
	rows, seen = [], set()
	for key, title in ROWS:
		value = (fields.get(key) or "").strip()
		if not value or title in seen:
			continue
		seen.add(title)
		rows.append('<tr><td style="padding:5px 12px 5px 0;color:#667085;width:150px;vertical-align:top;">%s</td>'
					'<td style="padding:5px 0;color:#1d2433;">%s</td></tr>' % (title, escape_html(_clip(value, 500))))
	msg = escape_html(_clip(fields.get("message"), MAX_TEXT)).replace("\n", "<br>")
	return ('<p style="margin:0 0 8px 0;"><b>%s</b></p><table style="border-collapse:collapse;font-size:13px;">%s</table>' % (label, "".join(rows))
			+ ('<div style="margin:12px 0 22px 0;padding:12px 14px;background:#f5f7fa;border-left:3px solid #14213d;">%s</div>' % msg if msg else ""))


def _subject(label, fields):
	topic = fields.get("topic") or fields.get("position") or fields.get("product")
	who = fields.get("company") or fields.get("name") or fields.get("email")
	return _clip("%s%s - %s" % (label, (": %s" % topic) if topic else "", who), 140)


# --------------------------------------------------------------------------- helpers
def _account():
	from frappe.email.doctype.email_account.email_account import EmailAccount

	try:
		return EmailAccount.find_outgoing(_raise_error=False)
	except Exception:
		return None


def _sender():
	account = _account()
	if not account or not account.email_id:
		return None
	return formataddr((frappe.db.get_default("company") or "Sibyl Technologies", account.email_id))


def _as_dict(value):
	if isinstance(value, dict):
		return {k: (v if isinstance(v, str) else ("" if v is None else str(v))) for k, v in value.items()}
	if isinstance(value, str) and value.strip():
		try:
			return _as_dict(json.loads(value))
		except ValueError:
			return {}
	return {}


def _clip(value, n):
	return (value or "").strip()[:n]


def _url(value):
	"""The first http(s) link, if it fits ERPNext's 140-character link fields (else "")."""
	first = (value or "").strip().split()[0] if (value or "").strip() else ""
	return first if re.match(r"^https?://", first, re.I) and len(first) <= 140 else ""


def _amount(value):
	digits = re.sub(r"[^\d.]", "", (value or "").split("-")[0])
	try:
		return float(digits) if digits else 0
	except ValueError:
		return 0

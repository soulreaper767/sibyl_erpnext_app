"""Public demo on this system.

Visitors log in as one demo user (credentials published on sibyl.pk and on /login?demo=1) and try the
system on four demo companies (trading, manufacturing, services, retail) filled with a few months of
realistic data across selling, buying, stock, accounts, manufacturing, projects, CRM, support and HR.

The demo user is fenced off from the real companies:
- User Permissions: only the demo companies, the "Demo Customers / Suppliers / Items" groups and the
  demo price lists (so customers, suppliers, items, prices and every company-linked document).
- query_conditions / has_permission below: records with no company field (contacts, addresses, emails,
  files, comments, applicants, stock bins, users, website submissions, newsletters) are filtered
  in code, both in lists and when opened directly.
- The demo user can't delete, cancel or amend anything, or change settings.
- Nothing a demo user or a demo company triggers ever leaves as email (Email Queue guard).
- The password is reset every hour, so nobody can lock the next visitor out.
"""
import random

import frappe
from frappe import _
from frappe.utils import add_days, add_months, flt, get_first_day, getdate, now_datetime, nowdate

SETTINGS = "Sibyl Demo Settings"
ROLE = "Sibyl Demo"
DEMO_USER = "demo@sibyl.pk"
DEFAULT_PASSWORD = "SibylDemo#2026"
CUSTOMER_GROUP, SUPPLIER_GROUP, ITEM_GROUP = "Demo Customers", "Demo Suppliers", "Demo Items"
SELLING, BUYING = "Demo Selling", "Demo Buying"
WORK_ROLES = ["Sales User", "Sales Master Manager", "Purchase User", "Purchase Master Manager", "Stock User", "Item Manager",
			  "Accounts User", "HR User", "Projects User", "Manufacturing User", "Support Team", ROLE]

INDUSTRIES = [
	dict(company="Demo Trading Co (Pvt) Ltd", abbr="DTRD", industry="Distribution & Trading", group="Demo Trading Goods",
		 items=[("DTRD-RICE25", "Basmati Rice 25 kg bag", "Nos", 1, 6200, 7150), ("DTRD-OIL5L", "Cooking Oil 5 litre", "Nos", 1, 2650, 2990),
				("DTRD-SUGAR50", "Sugar 50 kg bag", "Nos", 1, 7300, 7900), ("DTRD-ATTA20", "Wheat Flour 20 kg", "Nos", 1, 2300, 2580),
				("DTRD-TEA900", "Tea 900 g carton", "Nos", 1, 1850, 2150)],
		 customers=["Al-Noor Stores", "City Wholesale Mart", "Karachi Food Distributors", "Prime Cash & Carry", "Rehman Traders"],
		 suppliers=["Punjab Rice Mills", "Sunrise Edible Oils", "National Sugar Industries"]),
	dict(company="Demo Textile Mills Ltd", abbr="DTXM", industry="Manufacturing (Textile)", group="Demo Textile",
		 items=[("DTXM-COTTON", "Raw Cotton", "Kg", 1, 520, 0), ("DTXM-PSF", "Polyester Staple Fibre", "Kg", 1, 410, 0),
				("DTXM-CONE", "Paper Cone", "Nos", 1, 18, 0), ("DTXM-Y30C", "Cotton Yarn 30s Combed", "Kg", 1, 0, 865),
				("DTXM-Y40PC", "PC Yarn 40s (52/48)", "Kg", 1, 0, 790)],
		 boms={"DTXM-Y30C": [("DTXM-COTTON", 1.18), ("DTXM-CONE", 0.5)], "DTXM-Y40PC": [("DTXM-COTTON", 0.62), ("DTXM-PSF", 0.57), ("DTXM-CONE", 0.5)]},
		 customers=["Lahore Weaving Co", "Faisalabad Denim Ltd", "Sialkot Knits", "Export Fabrics International"],
		 suppliers=["Multan Cotton Ginners", "Fibre Tech Pakistan", "Cone & Tube Industries"]),
	dict(company="Demo IT Services (Pvt) Ltd", abbr="DITS", industry="Professional & IT Services", group="Demo Services",
		 items=[("DITS-IMPL", "ERP Implementation (per day)", "Nos", 0, 0, 45000), ("DITS-SUPPORT", "Monthly Support Retainer", "Nos", 0, 0, 75000),
				("DITS-CLOUD", "Cloud Hosting (per month)", "Nos", 0, 9500, 18000), ("DITS-TRAIN", "User Training Session", "Nos", 0, 0, 25000)],
		 customers=["Bright Pharma", "EduSmart Schools", "Metro Logistics", "GreenField Agri"],
		 suppliers=["CloudHost Pakistan", "Office Space Rentals"]),
	dict(company="Demo Mart (Retail & FMCG)", abbr="DMRT", industry="Retail & FMCG", group="Demo Retail",
		 items=[("DMRT-SHAMP", "Shampoo 400 ml", "Nos", 1, 640, 780), ("DMRT-PASTE", "Toothpaste 150 g", "Nos", 1, 260, 330),
				("DMRT-DETER", "Detergent 1 kg", "Nos", 1, 520, 640), ("DMRT-BISC", "Biscuits family pack", "Nos", 1, 190, 250),
				("DMRT-COLA", "Soft Drink 1.5 litre", "Nos", 1, 155, 200)],
		 customers=["Walk-in Customer (Demo Mart)", "Corporate Gifts Co", "Hostel Mess Services", "Neighbourhood Pharmacy"],
		 suppliers=["Unique FMCG Distributors", "Royal Beverages", "Home Care Supplies"]),
]
COMPANIES = [d["company"] for d in INDUSTRIES]


# =========================================================================== fence
def is_demo(user=None):
	user = user or frappe.session.user
	if user in ("Administrator", "Guest"):
		return False
	return ROLE in frappe.get_roles(user)


def _q(values):
	return ", ".join(frappe.db.escape(v) for v in values) or "''"


def _belongs(table, user):
	"""SQL: a Contact / Address that belongs to demo customers, suppliers, companies or leads (or the user made it)."""
	u = frappe.db.escape(user)
	return (f"(`tab{table}`.owner = {u} or exists (select 1 from `tabDynamic Link` dl where dl.parenttype = '{table}' "
			f"and dl.parent = `tab{table}`.name and ("
			f"(dl.link_doctype = 'Customer' and dl.link_name in (select name from tabCustomer where customer_group = {frappe.db.escape(CUSTOMER_GROUP)})) "
			f"or (dl.link_doctype = 'Supplier' and dl.link_name in (select name from tabSupplier where supplier_group = {frappe.db.escape(SUPPLIER_GROUP)})) "
			f"or (dl.link_doctype = 'Company' and dl.link_name in ({_q(COMPANIES)})) "
			f"or (dl.link_doctype = 'Lead' and dl.link_name in (select name from tabLead where company in ({_q(COMPANIES)}))))))")


def _conditions(doctype, user):
	u = frappe.db.escape(user)
	companies = _q(COMPANIES)
	owner_only = f"`tab{doctype}`.owner = {u}"
	rules = {
		"Contact": lambda: _belongs("Contact", user),
		"Address": lambda: _belongs("Address", user),
		"Communication": lambda: owner_only,
		"Comment": lambda: owner_only,
		"File": lambda: owner_only,
		"Event": lambda: owner_only,
		"Note": lambda: owner_only,
		"User": lambda: f"`tabUser`.name = {u}",
		"Job Applicant": lambda: (f"(`tabJob Applicant`.owner = {u} or `tabJob Applicant`.job_title in "
								  f"(select name from `tabJob Opening` where company in ({companies})))"),
		"Lead": lambda: f"`tabLead`.company in ({companies})",
		"Issue": lambda: f"`tabIssue`.company in ({companies})",
		"Customer": lambda: f"`tabCustomer`.customer_group = {frappe.db.escape(CUSTOMER_GROUP)}",
		"Supplier": lambda: f"`tabSupplier`.supplier_group = {frappe.db.escape(SUPPLIER_GROUP)}",
		"Bin": lambda: f"`tabBin`.warehouse in (select name from tabWarehouse where company in ({companies}))",
		"Sibyl Web Submission": lambda: "1=0",
		"Email Group": lambda: "1=0",
		"Email Group Member": lambda: "1=0",
		"Newsletter": lambda: "1=0",
		"Email Account": lambda: "1=0",
	}
	rule = rules.get(doctype)
	return rule() if rule else None


def query_conditions(user=None, doctype=None):
	"""permission_query_conditions for every doctype (hooked on "*"): only fences the demo user."""
	user = user or frappe.session.user
	if not doctype or not is_demo(user):
		return ""
	return _conditions(doctype, user) or ""


NO_GO = {"delete", "cancel", "amend", "share", "import"}
OWN_DELETABLE = {"ToDo", "Note", "Event", "Comment", "File", "Notification Log"}


def has_permission(doc, ptype=None, user=None, debug=False):
	"""has_permission for every doctype (hooked on "*"). Must return True to allow - None denies."""
	user = user or frappe.session.user
	if not is_demo(user):
		return True
	doctype = doc.doctype if not isinstance(doc, str) else doc
	if ptype in NO_GO and not (ptype == "delete" and doctype in OWN_DELETABLE):
		return False
	meta = frappe.get_meta(doctype)
	if meta.issingle and ptype not in (None, "read", "select", "print"):
		return False
	if doctype == "User" and ptype not in (None, "read", "select"):
		return False
	if isinstance(doc, str) or not doc.get("name") or (hasattr(doc, "is_new") and doc.is_new()):
		return True  # lists are fenced by query_conditions; new records by User Permissions
	cond = _conditions(doctype, user)
	if cond:
		return bool(frappe.db.sql(f"select name from `tab{doctype}` where name = %s and {cond}", doc.name))
	return True


def block_email(doc, method=None):
	"""Email Queue.before_insert: nothing from the demo user or about a demo company's records is sent."""
	reason = None
	if is_demo(frappe.session.user):
		reason = "sent by the demo user"
	elif any((r.recipient or "").strip().lower() == DEMO_USER for r in doc.get("recipients") or []):
		reason = "addressed to the shared demo login (e.g. a password-reset or login-link request)"
	elif doc.reference_doctype and doc.reference_name and _demo_record(doc.reference_doctype, doc.reference_name):
		reason = "about a demo company's record"
	if reason:
		doc.status = "Error"
		doc.error = "Not sent: %s (Sibyl public demo - demo emails never leave this system)." % reason


def _demo_record(doctype, name):
	try:
		meta = frappe.get_meta(doctype)
	except Exception:
		return False
	if meta.has_field("company"):
		return frappe.db.get_value(doctype, name, "company") in COMPANIES
	if doctype == "Customer":
		return frappe.db.get_value("Customer", name, "customer_group") == CUSTOMER_GROUP
	if doctype == "Supplier":
		return frappe.db.get_value("Supplier", name, "supplier_group") == SUPPLIER_GROUP
	return False


# =========================================================================== public bits
@frappe.whitelist(allow_guest=True)
def public_info():
	"""For the login page and the website's Try Demo page."""
	if not frappe.db.exists("DocType", SETTINGS):
		return {"enabled": False}
	s = frappe.get_cached_doc(SETTINGS)
	if not s.enabled or not frappe.db.get_value("User", s.demo_user or DEMO_USER, "enabled"):
		return {"enabled": False}
	return {"enabled": True, "user": s.demo_user or DEMO_USER, "password": s.demo_password or DEFAULT_PASSWORD,
			"companies": [{"company": d["company"], "industry": d["industry"]} for d in INDUSTRIES]}


def hourly():
	"""Keep the demo login working: password back to the published one, user enabled / disabled per settings."""
	if not frappe.db.exists("DocType", SETTINGS) or not frappe.db.exists("User", DEMO_USER):
		return
	s = frappe.get_single(SETTINGS)
	from frappe.utils.password import update_password

	frappe.db.set_value("User", DEMO_USER, "enabled", 1 if s.enabled else 0, update_modified=False)
	for up in frappe.get_all("User Permission", filters={"user": DEMO_USER, "allow": "Company", "for_value": ["not in", COMPANIES]}, pluck="name"):
		frappe.delete_doc("User Permission", up, ignore_permissions=True, force=True)  # belt and braces, hourly
	if s.enabled:
		update_password(DEMO_USER, s.demo_password or DEFAULT_PASSWORD)
	frappe.db.commit()


def protect_demo_user(doc, method=None):
	"""User.before_validate (User.validate itself clears new_password): visitors can't change the demo account."""
	if doc.name != DEMO_USER or frappe.session.user != DEMO_USER:
		return
	if doc.new_password:
		frappe.throw(_("The demo account's password can't be changed."))
	before = doc.get_doc_before_save()
	if before and (before.email != doc.email or before.enabled != doc.enabled):
		frappe.throw(_("The demo account can't be changed."))


def setup_basics():
	"""Install / migrate: the marker role and settings defaults only - no data (that's build())."""
	if not frappe.db.exists("Role", ROLE):
		frappe.get_doc({"doctype": "Role", "role_name": ROLE, "desk_access": 1,
						"description": "Public demo user: fenced to the demo companies (sibyl_app.demo)"}).insert(ignore_permissions=True)
	if frappe.db.exists("DocType", SETTINGS):
		s = frappe.get_single(SETTINGS)
		changed = False
		if not s.demo_user:
			s.demo_user, changed = DEMO_USER, True
		if not s.demo_password:
			s.demo_password, changed = DEFAULT_PASSWORD, True
		if changed:
			if not frappe.db.sql("select 1 from tabSingles where doctype=%s and field='enabled'", SETTINGS):
				s.enabled = 1
			s.flags.ignore_permissions = True
			s.save()


# =========================================================================== build
@frappe.whitelist()
def build():
	"""Settings button: build / top up the demo (background job)."""
	frappe.only_for("System Manager")
	frappe.enqueue("sibyl_app.demo.build_now", queue="long", timeout=3600, job_id="sibyl_demo_build", deduplicate=True)
	_status(_("Queued - building the demo companies and data in the background (a few minutes)."))
	return _("Building the demo in the background. This takes a few minutes; refresh to see the status.")


def build_now():
	user = frappe.session.user
	frappe.set_user("Administrator")
	try:
		setup_basics()
		_masters()
		for spec in INDUSTRIES:
			_status(_("Building {0}...").format(spec["company"]))
			_company(spec)
			frappe.db.commit()
			if not frappe.db.exists("Sales Invoice", {"company": spec["company"], "docstatus": 1}):
				_seed(spec)
				frappe.db.commit()
		_demo_user()
		frappe.db.set_single_value(SETTINGS, "last_built", now_datetime())
		_status(_("Ready: {0} demo companies, login {1}.").format(len(INDUSTRIES), DEMO_USER))
		frappe.db.commit()
	except Exception:
		frappe.db.rollback()
		frappe.log_error(title="Sibyl demo build failed")
		_status(_("Failed - see Error Log ({0}). Press Build again to continue where it stopped.").format(frappe.utils.now()))
		frappe.db.commit()
		raise
	finally:
		frappe.set_user(user)


def _status(text):
	if frappe.db.exists("DocType", SETTINGS):
		frappe.db.set_single_value(SETTINGS, "build_status", text)
		frappe.db.commit()


def _ensure(doctype, name, values):
	if frappe.db.exists(doctype, name):
		return name
	doc = frappe.get_doc(dict(doctype=doctype, **values))
	doc.flags.ignore_permissions = True
	doc.insert()
	return doc.name


def _masters():
	_ensure("Customer Group", CUSTOMER_GROUP, {"customer_group_name": CUSTOMER_GROUP, "parent_customer_group": "All Customer Groups", "is_group": 0})
	_ensure("Supplier Group", SUPPLIER_GROUP, {"supplier_group_name": SUPPLIER_GROUP, "parent_supplier_group": "All Supplier Groups", "is_group": 0})
	_ensure("Item Group", ITEM_GROUP, {"item_group_name": ITEM_GROUP, "parent_item_group": "All Item Groups", "is_group": 1})
	for spec in INDUSTRIES:
		_ensure("Item Group", spec["group"], {"item_group_name": spec["group"], "parent_item_group": ITEM_GROUP, "is_group": 0})
	currency = frappe.db.get_default("currency") or "PKR"
	_ensure("Price List", SELLING, {"price_list_name": SELLING, "selling": 1, "buying": 0, "currency": currency, "enabled": 1})
	_ensure("Price List", BUYING, {"price_list_name": BUYING, "selling": 0, "buying": 1, "currency": currency, "enabled": 1})
	_ensure("Activity Type", "Implementation", {"activity_type": "Implementation", "billing_rate": 6000, "costing_rate": 2500})
	for d in _dates():
		_fiscal_year(d)
	_holidays()


def _dates():
	start = getdate(add_days(nowdate(), -120))
	return [start, getdate(nowdate())]


def _fiscal_year(d):
	if frappe.db.sql("select name from `tabFiscal Year` where %s between year_start_date and year_end_date and disabled = 0", d):
		return
	start = getdate("%s-07-01" % (d.year if d.month >= 7 else d.year - 1))
	end = add_days(add_months(start, 12), -1)
	_ensure("Fiscal Year", "%s-%s" % (start.year, start.year + 1), {"year": "%s-%s" % (start.year, start.year + 1),
																	 "year_start_date": start, "year_end_date": end})


HOLIDAYS = "Demo Holidays (Sundays)"


def _holidays():
	if frappe.db.exists("Holiday List", HOLIDAYS):
		return
	start, end = getdate(add_days(nowdate(), -200)), getdate(add_days(nowdate(), 400))
	hl = frappe.get_doc({"doctype": "Holiday List", "holiday_list_name": HOLIDAYS, "from_date": start, "to_date": end})
	d = start
	while d <= end:
		if d.weekday() == 6:
			hl.append("holidays", {"holiday_date": d, "description": "Sunday", "weekly_off": 1})
		d = add_days(d, 1)
	hl.insert(ignore_permissions=True)


def _company(spec):
	name = spec["company"]
	if not frappe.db.exists("Company", name):
		c = frappe.get_doc({
			"doctype": "Company", "company_name": name, "abbr": spec["abbr"], "default_currency": frappe.db.get_default("currency") or "PKR",
			"country": frappe.db.get_default("country") or "Pakistan", "create_chart_of_accounts_based_on": "Standard Template",
			"chart_of_accounts": "Standard",
		})
		c.flags.ignore_permissions = True
		c.insert()
	frappe.db.set_value("Company", name, "default_holiday_list", HOLIDAYS)
	_brand(spec)
	territory = "Pakistan" if frappe.db.exists("Territory", "Pakistan") else frappe.db.get_value("Territory", {"is_group": 0})
	wh = _wh(spec, "Stores")
	for code, item_name, uom, stock, buy, sell in spec["items"]:
		if not frappe.db.exists("Item", code):
			frappe.get_doc({
				"doctype": "Item", "item_code": code, "item_name": item_name, "item_group": spec["group"], "stock_uom": uom,
				"is_stock_item": stock, "include_item_in_manufacturing": 1, "valuation_rate": buy or sell * 0.6 or 1,
				"is_sales_item": 1 if sell else 0, "is_purchase_item": 1 if buy else 0,
				"item_defaults": [{"company": name, "default_warehouse": wh}],
			}).insert(ignore_permissions=True, set_name=code)  # keep the code as the name even when items use a naming series
		for price_list, rate in ((SELLING, sell), (BUYING, buy)):
			if rate and not frappe.db.exists("Item Price", {"item_code": code, "price_list": price_list}):
				frappe.get_doc({"doctype": "Item Price", "item_code": code, "price_list": price_list, "price_list_rate": rate}).insert(ignore_permissions=True)
	for i, cust in enumerate(spec["customers"]):
		if not frappe.db.exists("Customer", cust):
			frappe.get_doc({"doctype": "Customer", "customer_name": cust, "customer_type": "Company", "customer_group": CUSTOMER_GROUP,
							"territory": territory, "default_price_list": SELLING}).insert(ignore_permissions=True)
			_contact(cust, "Customer", cust, i)
	for i, sup in enumerate(spec["suppliers"]):
		if not frappe.db.exists("Supplier", sup):
			frappe.get_doc({"doctype": "Supplier", "supplier_name": sup, "supplier_group": SUPPLIER_GROUP,
							"default_price_list": BUYING}).insert(ignore_permissions=True)
			_contact(sup, "Supplier", sup, i)


BRANDS = {
	"DTRD": ("DT", "Demo Trading", "#0f766e", "Plot 14, Badami Bagh Market", "Lahore", "Punjab", "54000", "+92 42 3700 1401"),
	"DTXM": ("TM", "Demo Textile Mills", "#7c2d12", "Sargodha Road, Industrial Estate", "Faisalabad", "Punjab", "38000", "+92 41 8700 2202"),
	"DITS": ("IT", "Demo IT Services", "#1d4ed8", "Office 9, Arfa Software Technology Park", "Lahore", "Punjab", "54000", "+92 42 3500 3303"),
	"DMRT": ("DM", "Demo Mart", "#b45309", "Shop 3, Tariq Road", "Karachi", "Sindh", "75400", "+92 21 3400 4404"),
}


def _logo_svg(initials, label, colour):
	return ('<svg xmlns="http://www.w3.org/2000/svg" width="360" height="80" viewBox="0 0 360 80">'
			f'<rect x="2" y="2" width="76" height="76" rx="16" fill="{colour}"/>'
			f'<text x="40" y="52" text-anchor="middle" font-family="DejaVu Sans, Arial, sans-serif" font-size="32" font-weight="700" fill="#ffffff">{initials}</text>'
			f'<text x="94" y="50" font-family="DejaVu Sans, Arial, sans-serif" font-size="26" font-weight="700" fill="#14213d">{label}</text>'
			'</svg>')


def _brand(spec):
	"""Each demo company prints as itself: its own logo, address and a clearly-demo NTN."""
	company = spec["company"]
	initials, label, colour, line1, city, state, pin, phone = BRANDS[spec["abbr"]]
	if not frappe.db.get_value("Company", company, "company_logo"):
		f = frappe.get_doc({"doctype": "File", "file_name": "demo-logo-%s.svg" % spec["abbr"].lower(), "is_private": 0,
							"content": _logo_svg(initials, label, colour), "attached_to_doctype": "Company",
							"attached_to_name": company, "attached_to_field": "company_logo"})
		f.flags.ignore_permissions = True
		f.insert()
		frappe.db.set_value("Company", company, "company_logo", f.file_url)
	if not frappe.db.get_value("Company", company, "tax_id"):
		frappe.db.set_value("Company", company, "tax_id", "DEMO-%s" % spec["abbr"])
	if not frappe.db.get_value("Dynamic Link", {"link_doctype": "Company", "link_name": company, "parenttype": "Address"}):
		a = frappe.get_doc({"doctype": "Address", "address_title": company, "address_type": "Office", "address_line1": line1,
							"city": city, "state": state, "pincode": pin, "country": frappe.db.get_default("country") or "Pakistan",
							"phone": phone, "is_your_company_address": 1, "links": [{"link_doctype": "Company", "link_name": company}]})
		a.flags.ignore_permissions = True
		a.insert()


FIRST = ["Ahmed","Sana", "Bilal", "Ayesha", "Usman", "Fatima", "Hamza", "Zainab", "Imran", "Hira"]
LAST = ["Khan", "Malik", "Qureshi", "Siddiqui", "Butt", "Raza", "Sheikh", "Chaudhry"]


def _contact(party, doctype, name, i):
	slug = "".join(ch for ch in name.lower() if ch.isalnum())[:20]
	first, last = FIRST[(len(name) + i) % len(FIRST)], LAST[(len(name) * 3 + i) % len(LAST)]
	c = frappe.get_doc({"doctype": "Contact", "first_name": first, "last_name": last, "is_primary_contact": 1,
						"email_ids": [{"email_id": "%s.%s@%s.example.com" % (first.lower(), last.lower(), slug), "is_primary": 1}],
						"phone_nos": [{"phone": "+92 3%02d %07d" % (random.randint(0, 49), random.randint(0, 9999999)), "is_primary_mobile_no": 1}],
						"links": [{"link_doctype": doctype, "link_name": party}]})
	c.insert(ignore_permissions=True)


def _wh(spec, label):
	return frappe.db.get_value("Warehouse", {"warehouse_name": label, "company": spec["company"]}) or frappe.db.get_value(
		"Warehouse", {"company": spec["company"], "is_group": 0})


def _d(days_ago):
	return getdate(add_days(nowdate(), -days_ago))


def _submit(doc):
	doc.flags.ignore_permissions = True
	if doc.is_new():
		doc.insert()
	doc.submit()
	return doc


# --------------------------------------------------------------------------- transactions
def _seed(spec):
	random.seed(spec["abbr"])
	company, stores = spec["company"], _wh(spec, "Stores")
	stock_items = [i for i in spec["items"] if i[3] and i[4]]
	sell_items = [i for i in spec["items"] if i[5]]

	# opening stock + purchases
	if stock_items:
		se = frappe.get_doc({"doctype": "Stock Entry", "stock_entry_type": "Material Receipt", "company": company,
							 "posting_date": _d(118), "set_posting_time": 1, "remarks": "Opening stock (demo)",
							 "items": [{"item_code": c, "qty": 1500 if spec.get("boms") else 150, "t_warehouse": stores, "basic_rate": b}
									   for c, _n, u, _s, b, _p in stock_items]})
		_submit(se)
	purchase_items = [i for i in spec["items"] if i[4]]
	for n, sup in enumerate(spec["suppliers"]):
		rows = random.sample(purchase_items, min(2, len(purchase_items))) if purchase_items else []
		if not rows:
			continue
		po = _submit(frappe.get_doc({"doctype": "Purchase Order", "supplier": sup, "company": company, "transaction_date": _d(100 - n * 20),
									  "schedule_date": _d(95 - n * 20), "set_warehouse": stores if rows[0][3] else None,
									  "buying_price_list": BUYING,
									  "items": [{"item_code": c, "qty": 200 if u == "Kg" else 40, "rate": b, "schedule_date": _d(95 - n * 20)}
												for c, _x, u, _s, b, _p in rows]}))
		from erpnext.buying.doctype.purchase_order.purchase_order import make_purchase_invoice

		pi = frappe.get_doc(make_purchase_invoice(po.name))
		pi.update({"posting_date": _d(94 - n * 20), "set_posting_time": 1, "bill_no": "INV-%s-%03d" % (spec["abbr"], n + 1),
				   "bill_date": _d(94 - n * 20), "update_stock": 1 if rows[0][3] else 0})
		if pi.update_stock:
			for it in pi.items:
				it.warehouse = stores
		_submit(pi)
		if n % 2 == 0:
			_pay("Purchase Invoice", pi.name, _d(80 - n * 20))

	# manufacturing: BOMs + a finished work order
	for fg, rm in (spec.get("boms") or {}).items():
		_manufacture(spec, fg, rm)

	# CRM: leads -> opportunity -> quotations
	for n, cust in enumerate(spec["customers"][:3]):
		first, last = FIRST[n + 3], LAST[n + 2]
		lead = frappe.get_doc({"doctype": "Lead", "first_name": first, "last_name": last, "company_name": "%s Prospect %d" % (spec["abbr"], n + 1),
							   "email_id": "%s.%s@prospect%d-%s.example.com" % (first.lower(), last.lower(), n + 1, spec["abbr"].lower()),
							   "status": ["Lead", "Open", "Interested"][n], "company": company, "source": None})
		lead.flags.ignore_permissions = True
		lead.insert()
		if n == 0:
			opp = frappe.get_doc({"doctype": "Opportunity", "opportunity_from": "Lead", "party_name": lead.name, "company": company,
								  "opportunity_amount": 450000, "transaction_date": _d(30), "status": "Open"})
			opp.flags.ignore_permissions = True
			opp.flags.ignore_mandatory = True
			opp.insert()
	for n, cust in enumerate(spec["customers"][:2]):
		rows = sell_items[n:n + 2] or sell_items[:1]
		q = frappe.get_doc({"doctype": "Quotation", "quotation_to": "Customer", "party_name": cust, "company": company,
							"transaction_date": _d(25 - n * 5), "valid_till": _d(-20), "selling_price_list": SELLING,
							"items": [{"item_code": c, "qty": 10 + n * 5, "rate": p} for c, _x, _u, _s, _b, p in rows]})
		q.flags.ignore_permissions = True
		q.insert()
		if n == 0:
			q.submit()

	# sales orders -> invoices -> payments (some paid, some partly, some open for the aging)
	from erpnext.selling.doctype.sales_order.sales_order import make_sales_invoice

	for n in range(6):
		cust = spec["customers"][n % len(spec["customers"])]
		rows = random.sample(sell_items, min(len(sell_items), 1 + n % 3))
		day = 90 - n * 15
		so = _submit(frappe.get_doc({
			"doctype": "Sales Order", "customer": cust, "company": company, "transaction_date": _d(day), "delivery_date": _d(day - 7),
			"selling_price_list": SELLING, "set_warehouse": stores if any(r[3] for r in rows) else None,
			"items": [{"item_code": c, "qty": random.randint(20, 60) if u == "Kg" else random.randint(2, 12), "rate": p,
					   "delivery_date": _d(day - 7)} for c, _x, u, _s, _b, p in rows]}))
		if n == 5:
			continue  # one order left to deliver / bill
		si = frappe.get_doc(make_sales_invoice(so.name))
		stocked = {r[0] for r in spec["items"] if r[3]}
		si.update({"posting_date": _d(day - 5), "set_posting_time": 1, "due_date": _d(day - 5 - 30),
				   "update_stock": 1 if any(it.item_code in stocked for it in si.items) else 0})
		if si.update_stock:
			for it in si.items:
				it.warehouse = stores
		si.payment_schedule = []
		_submit(si)
		if n in (0, 1):
			_pay("Sales Invoice", si.name, _d(day - 20))
		elif n == 2:
			_pay("Sales Invoice", si.name, _d(day - 25), part=0.5)

	# a monthly expense
	_expense(spec)
	# support tickets
	for n, cust in enumerate(spec["customers"][:2]):
		issue = frappe.get_doc({"doctype": "Issue", "subject": ["Delivery delayed on last order", "Request for updated price list"][n],
								"customer": cust, "company": company, "status": ["Open", "Replied"][n], "raised_by": "support@%s.example.com" % spec["abbr"].lower(),
								"description": "Raised by the customer (demo data)."})
		issue.flags.ignore_permissions = True
		issue.flags.ignore_mandatory = True
		issue.insert()
	# people + attendance (+ a project for the services company)
	employees = _employees(spec)
	if spec["abbr"] == "DITS":
		_project(spec, employees)


def _pay(doctype, name, date, part=1.0):
	from erpnext.accounts.doctype.payment_entry.payment_entry import get_payment_entry

	pe = get_payment_entry(doctype, name)
	pe.update({"posting_date": date, "reference_no": "DEMO-%s" % name[-8:], "reference_date": date, "mode_of_payment": None})
	if part < 1:
		amt = flt(pe.paid_amount * part, 0)
		pe.paid_amount = pe.received_amount = amt
		pe.references[0].allocated_amount = amt
		pe.set_amounts()
	_submit(pe)


def _manufacture(spec, fg, rm):
	company = spec["company"]
	bom_name = frappe.db.get_value("BOM", {"item": fg, "is_default": 1, "docstatus": 1})
	if not bom_name:
		bom = _submit(frappe.get_doc({"doctype": "BOM", "item": fg, "quantity": 1, "company": company, "is_default": 1, "is_active": 1,
									  "rm_cost_as_per": "Valuation Rate", "items": [{"item_code": c, "qty": q} for c, q in rm]}))
		bom_name = bom.name
	from erpnext.manufacturing.doctype.work_order.work_order import make_stock_entry

	# produced before the sales dates, so the yarn sold in the demo invoices is in stock
	qty, made_on = 600, _d(112)
	wo = _submit(frappe.get_doc({"doctype": "Work Order", "production_item": fg, "bom_no": bom_name, "qty": qty, "company": company,
								 "source_warehouse": _wh(spec, "Stores"), "wip_warehouse": _wh(spec, "Work In Progress"),
								 "fg_warehouse": _wh(spec, "Finished Goods"), "skip_transfer": 1,
								 "planned_start_date": "%s 08:00:00" % made_on}))
	se = frappe.get_doc(make_stock_entry(wo.name, "Manufacture", qty))
	se.update({"posting_date": made_on, "posting_time": "18:00:00", "set_posting_time": 1})
	_submit(se)
	# the finished yarn is sold from Stores, so move it there
	_submit(frappe.get_doc({"doctype": "Stock Entry", "stock_entry_type": "Material Transfer", "company": company,
							"posting_date": made_on, "posting_time": "19:00:00", "set_posting_time": 1,
							"items": [{"item_code": fg, "qty": qty, "s_warehouse": _wh(spec, "Finished Goods"), "t_warehouse": _wh(spec, "Stores")}]}))


def _expense(spec):
	company = spec["company"]
	cash = frappe.get_cached_value("Company", company, "default_cash_account")
	expense = (frappe.db.get_value("Account", {"company": company, "is_group": 0, "account_name": ["like", "%Rent%"]})
			   or frappe.db.get_value("Account", {"company": company, "is_group": 0, "root_type": "Expense"}))
	cost_center = frappe.get_cached_value("Company", company, "cost_center")
	for m in (3, 2, 1):
		date = get_first_day(add_months(nowdate(), -m + 1)) if m > 1 else get_first_day(nowdate())
		_submit(frappe.get_doc({"doctype": "Journal Entry", "voucher_type": "Journal Entry", "company": company, "posting_date": date,
								"user_remark": "Office rent (demo)", "accounts": [
									{"account": expense, "debit_in_account_currency": 120000, "cost_center": cost_center},
									{"account": cash, "credit_in_account_currency": 120000}]}))


def _employees(spec):
	company = spec["company"]
	titles = [d for d in ("Manager", "Accountant", "Sales Representative", "Engineer", "Software Developer", "Consultant")
			  if frappe.db.exists("Designation", d)]
	out = []
	for n in range(4):
		first, last = FIRST[(n * 3 + len(company)) % len(FIRST)], LAST[(n + len(company)) % len(LAST)]
		emp = frappe.get_doc({"doctype": "Employee", "first_name": first, "last_name": last, "gender": "Female" if first in ("Sana", "Ayesha", "Fatima", "Zainab", "Hira") else "Male",
							  "date_of_birth": "1990-0%d-1%d" % (n + 1, n), "date_of_joining": _d(400 + n * 30), "company": company,
							  "designation": titles[n % len(titles)] if titles else None, "status": "Active", "holiday_list": HOLIDAYS})
		emp.flags.ignore_permissions = True
		emp.insert()
		out.append(emp.name)
	day, marked = 1, 0
	while marked < 12:
		date = _d(day)
		day += 1
		if date.weekday() == 6:
			continue
		marked += 1
		for k, emp in enumerate(out):
			status = "Absent" if (k + marked) % 11 == 0 else ("Half Day" if (k + marked) % 7 == 0 else "Present")
			att = frappe.get_doc({"doctype": "Attendance", "employee": emp, "attendance_date": date, "status": status, "company": company})
			try:
				_submit(att)
			except Exception:
				frappe.clear_messages()
	return out


def _project(spec, employees):
	company = spec["company"]
	cust = spec["customers"][0]
	proj = frappe.get_doc({"doctype": "Project", "project_name": "ERP Rollout - %s" % cust, "company": company, "customer": cust,
						   "status": "Open", "expected_start_date": _d(60), "expected_end_date": _d(-45), "estimated_costing": 900000})
	proj.insert(ignore_permissions=True)
	tasks = []
	for n, (subject, status) in enumerate((("Requirement workshops", "Completed"), ("Chart of accounts & masters", "Completed"),
										  ("Data migration", "Working"), ("User training", "Open"), ("Go-live support", "Open"))):
		t = frappe.get_doc({"doctype": "Task", "subject": subject, "project": proj.name, "status": status,
							"exp_start_date": _d(60 - n * 12), "exp_end_date": _d(50 - n * 12)})
		t.insert(ignore_permissions=True)
		tasks.append(t.name)
	if employees:
		ts = frappe.get_doc({"doctype": "Timesheet", "employee": employees[0], "company": company, "time_logs": [
			{"activity_type": "Implementation", "from_time": "%s 10:00:00" % _d(40 - n * 3), "hours": 6, "project": proj.name, "task": tasks[n % 3],
			 "is_billable": 1} for n in range(6)]})
		_submit(ts)


# --------------------------------------------------------------------------- the demo user
def _demo_user():
	s = frappe.get_single(SETTINGS)
	password = s.demo_password or DEFAULT_PASSWORD
	if not frappe.db.exists("User", DEMO_USER):
		u = frappe.get_doc({"doctype": "User", "email": DEMO_USER, "first_name": "Demo", "last_name": "Visitor", "user_type": "System User",
							"send_welcome_email": 0, "enabled": 1})
		u.flags.ignore_permissions = True
		u.flags.no_welcome_mail = True
		u.insert()
	u = frappe.get_doc("User", DEMO_USER)
	have = {r.role for r in u.roles}
	for role in WORK_ROLES:
		if role not in have and frappe.db.exists("Role", role):
			u.append("roles", {"role": role})
	u.simultaneous_sessions = 500
	u.enabled = 1 if s.enabled else 0
	u.flags.ignore_permissions = True
	u.save()
	from frappe.utils.password import update_password

	update_password(DEMO_USER, password)
	if frappe.db.exists("Notification Settings", DEMO_USER):
		frappe.db.set_value("Notification Settings", DEMO_USER, "enabled", 0)
	wanted = [("Company", c, i == 0) for i, c in enumerate(COMPANIES)] + [
		("Customer Group", CUSTOMER_GROUP, True), ("Supplier Group", SUPPLIER_GROUP, True), ("Item Group", ITEM_GROUP, True),
		("Price List", SELLING, False), ("Price List", BUYING, False)]
	# never any real company for the demo login, whatever added it
	for up in frappe.get_all("User Permission", filters={"user": DEMO_USER, "allow": "Company", "for_value": ["not in", COMPANIES]}, pluck="name"):
		frappe.delete_doc("User Permission", up, ignore_permissions=True, force=True)
	for allow, value, default in wanted:
		if not frappe.db.exists("User Permission", {"user": DEMO_USER, "allow": allow, "for_value": value}):
			frappe.get_doc({"doctype": "User Permission", "user": DEMO_USER, "allow": allow, "for_value": value,
							"apply_to_all_doctypes": 1, "is_default": 1 if default else 0}).insert(ignore_permissions=True)
	frappe.clear_cache(user=DEMO_USER)

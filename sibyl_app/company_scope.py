"""Keep every real user on their own company, so demo (or any other) companies never mix into their work.

Each enabled System User - except Administrator and public-demo users - who has no Company restriction yet
gets a User Permission for the site's default company (Global Defaults), marked as their default. That
scopes their lists, reports and new documents to it, and Yapie (which runs reports as the asker, for
their default company) follows. Users who already have Company permissions are left exactly as they are,
so giving someone more companies later is done the normal way (User Permissions).

Runs on every migrate and whenever a user is saved."""
import frappe

SKIP_USERS = ("Administrator", "Guest")


def default_company():
	return frappe.db.get_single_value("Global Defaults", "default_company") or frappe.db.get_default("company")


def _is_demo(user):
	from sibyl_app.demo import DEMO_USER, ROLE

	# the demo login by name too: it exists for a moment before it gets the demo role
	return user == DEMO_USER or ROLE in frappe.get_roles(user)


def scope_user(user, company=None):
	"""Give `user` the default company if they have no Company restriction. Returns True when added."""
	company = company or default_company()
	if not company or user in SKIP_USERS:
		return False
	u = frappe.db.get_value("User", user, ["enabled", "user_type"], as_dict=True)
	if not u or not u.enabled or u.user_type != "System User" or _is_demo(user):
		return False
	if frappe.db.exists("User Permission", {"user": user, "allow": "Company"}):
		return False
	frappe.get_doc({"doctype": "User Permission", "user": user, "allow": "Company", "for_value": company,
					"apply_to_all_doctypes": 1, "is_default": 1}).insert(ignore_permissions=True)
	frappe.clear_cache(user=user)
	return True


def scope_all_users():
	company = default_company()
	if not company:
		return []
	added = [u for u in frappe.get_all("User", filters={"enabled": 1, "user_type": "System User", "name": ["not in", SKIP_USERS]}, pluck="name")
			 if scope_user(u, company)]
	if added:
		print("Sibyl App: tied %d user(s) to %s: %s" % (len(added), company, ", ".join(added)))
	return added


def on_user_update(doc, method=None):
	"""User.on_update: new / re-enabled staff land on the default company straight away."""
	if doc.name in SKIP_USERS or not doc.enabled or doc.user_type != "System User":
		return
	try:
		scope_user(doc.name)
	except Exception:
		frappe.log_error(title="Sibyl App: could not tie %s to the default company" % doc.name)

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import validate_email_address


class SibylWebsiteSettings(Document):
	def validate(self):
		bad = [e for e in self.alert_addresses() if not validate_email_address(e)]
		if bad:
			frappe.throw(_("Not a valid email address: {0}").format(", ".join(bad)))
		if (self.max_per_hour or 0) < 1:
			self.max_per_hour = 5
		if (self.max_file_mb or 0) < 1:
			self.max_file_mb = 5

	def alert_addresses(self):
		return [line.strip() for line in (self.notify_emails or "").replace(",", "\n").splitlines() if line.strip()]

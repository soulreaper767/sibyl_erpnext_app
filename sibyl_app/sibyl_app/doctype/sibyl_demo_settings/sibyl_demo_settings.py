from frappe.model.document import Document


class SibylDemoSettings(Document):
	def on_update(self):
		# enabling / disabling or a new password takes effect at once (not only on the hourly reset)
		from sibyl_app.demo import hourly

		hourly()

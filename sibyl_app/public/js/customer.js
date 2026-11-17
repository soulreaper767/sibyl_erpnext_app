// Customer -> "Portal Access": give the customer a login to portal.sibyl.pk (tickets, orders, invoices).
// See sibyl_app/support_portal.py.
frappe.ui.form.on("Customer", {
	refresh(frm) {
		if (frm.is_new() || !frappe.user.has_role(["System Manager", "Sales Manager"])) return;
		frm.add_custom_button(__("Portal Access"), () => sibyl_portal_access(frm), __("Actions"));
	},
});

function sibyl_portal_access(frm) {
	frappe.call("sibyl_app.support_portal.portal_status", { customer: frm.doc.name }).then(({ message: st }) => {
		if (st.demo) {
			frappe.msgprint(__("Demo customers don't get portal logins."));
			return;
		}
		const users = (st.users || [])
			.map((u) => `<li><b>${frappe.utils.escape_html(u.user)}</b> - ${u.enabled ? __("active") : __("disabled")}${u.last_login ? ", " + __("last login {0}", [frappe.datetime.str_to_user(u.last_login)]) : ", " + __("never logged in")}</li>`)
			.join("");
		const d = new frappe.ui.Dialog({
			title: __("Customer Portal Access"),
			fields: [
				{
					fieldtype: "HTML",
					options: `<p class="text-muted">${__("The customer logs in at {0} to raise support tickets and see their orders and invoices.", [`<a href="/issues" target="_blank">${location.host}/issues</a>`])}</p>` +
						(users ? `<p>${__("Can already log in:")}</p><ul>${users}</ul>` : `<p>${__("Nobody from this customer can log in yet.")}</p>`),
				},
				{ fieldname: "email", fieldtype: "Data", options: "Email", label: __("Email of the person who will log in"), reqd: 1, default: st.suggested_email },
				{ fieldname: "full_name", fieldtype: "Data", label: __("Their name") },
				{ fieldname: "send_login_link", fieldtype: "Check", label: __("Email them a link to set their password now"), default: 0 },
			],
			primary_action_label: __("Give Access"),
			primary_action(v) {
				frappe.call({ method: "sibyl_app.support_portal.create_portal_user", args: { customer: frm.doc.name, ...v }, freeze: true }).then(({ message: r }) => {
					d.hide();
					frappe.msgprint({
						title: __("Portal access ready"),
						indicator: "green",
						message: `<p>${__("{0} can log in at {1}.", [`<b>${frappe.utils.escape_html(r.user)}</b>`, `<a href="${r.login_url}">${r.login_url}</a>`])}</p>` +
							`<p>${r.login_link_sent ? __("A set-your-password email has been sent.") : __("No email was sent. They can use “Forgot Password” on the login page, or open Portal Access again and tick the email option.")}</p>`,
					});
					frm.reload_doc();
				});
			},
		});
		d.show();
	});
}

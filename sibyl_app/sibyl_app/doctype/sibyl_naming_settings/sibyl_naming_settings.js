const METHOD = "sibyl_app.sibyl_app.doctype.sibyl_naming_settings.sibyl_naming_settings";

frappe.ui.form.on("Sibyl Naming Settings", {
	refresh(frm) {
		frm.add_custom_button(__("Assign Missing Customer IDs"), () => {
			frappe.call({
				method: `${METHOD}.assign_missing_customer_ids`,
				freeze: true,
				callback: (r) =>
					frappe.msgprint(__("Customer IDs assigned to {0} customer(s).", [r.message || 0])),
			});
		});
		frm.add_custom_button(__("Customers"), () => frappe.set_route("List", "Customer"));
		frm.trigger("render_preview");
	},
	name_pattern(frm) {
		frm.trigger("render_preview");
	},
	render_preview(frm) {
		const wrapper = frm.get_field("preview").$wrapper;
		if (!frm.doc.name_pattern) {
			wrapper.empty();
			return;
		}
		const rule = (frm.doc.rules || []).find((r) => r.return_prefix) || { prefix: "SO" };
		frappe.call({
			method: `${METHOD}.preview`,
			args: {
				name_pattern: frm.doc.name_pattern,
				prefix: rule.prefix,
				return_prefix: rule.return_prefix,
			},
			callback: ({ message: p }) => {
				if (!p) return;
				wrapper.html(`
					<div class="text-muted small">${__("Example for")} <b>${frappe.utils.escape_html(
						p.customer
					)}</b> (${frappe.utils.escape_html(p.customer_id)})</div>
					<div class="h5" style="margin-top:6px">${frappe.utils.escape_html(p.name)}</div>
					${
						p.return_name
							? `<div class="text-muted small">${__("Return / refund")}: <b>${frappe.utils.escape_html(
									p.return_name
							  )}</b></div>`
							: ""
					}
				`);
			},
		});
	},
});

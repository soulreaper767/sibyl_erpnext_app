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
		if (frappe.user.has_role("System Manager")) {
			frm.add_custom_button(__("Rename Existing Documents"), () => frm.trigger("rename_existing"));
			frm.add_custom_button(__("Regenerate All Customer IDs"), () => frm.trigger("regenerate_ids"));
		}
		frm.trigger("render_preview");
	},
	regenerate_ids(frm) {
		if (frm.is_dirty()) {
			frappe.msgprint(__("Save the settings first."));
			return;
		}
		frappe.confirm(
			__(
				"Every customer gets a new Customer ID under the current mode ({0}), oldest customer first, and all their existing documents are renamed to match. This cannot be undone automatically - take a backup first. Continue?",
				[__(frm.doc.customer_id_mode)]
			),
			() =>
				frappe.call({
					method: `${METHOD}.regenerate_customer_ids`,
					freeze: true,
					freeze_message: __("Re-numbering customers and documents..."),
					callback: ({ message: r }) => {
						if (r.queued) {
							frappe.msgprint(__("Started in the background. Check Background Jobs for progress."));
							return;
						}
						const esc = frappe.utils.escape_html;
						const renamed = Object.values(r.documents || {}).reduce((n, s) => n + s.to_rename, 0);
						frappe.msgprint(
							`<p>${__("{0} customer(s) re-numbered, {1} document(s) renamed.", [r.customers.length, renamed])}</p>` +
								r.customers
									.slice(0, 20)
									.map(([c, o, n]) => `${esc(c)}: ${esc(o || "-")} &rarr; <b>${esc(n)}</b>`)
									.join("<br>")
						);
						frm.reload_doc();
					},
				})
		);
	},
	rename_existing(frm) {
		if (frm.is_dirty()) {
			frappe.msgprint(__("Save the settings first."));
			return;
		}
		frappe.call({
			method: `${METHOD}.preview_existing_renames`,
			freeze: true,
			freeze_message: __("Checking existing documents..."),
			callback: ({ message: summary }) => {
				const rows = Object.entries(summary || {});
				const total = rows.reduce((n, [, s]) => n + s.to_rename, 0);
				if (!total) {
					frappe.msgprint(__("All existing documents already follow customer-wise naming."));
					return;
				}
				const esc = frappe.utils.escape_html;
				const table = rows
					.filter(([, s]) => s.to_rename)
					.map(
						([dt, s]) => `<tr><td>${esc(__(dt))}</td><td class="text-right">${s.to_rename}</td>
						<td class="text-muted small">${s.examples.map(([o, n]) => `${esc(o)} &rarr; ${esc(n)}`).join("<br>")}</td></tr>`
					)
					.join("");
				frappe.confirm(
					`<p>${__("{0} existing document(s) will be renamed and renumbered per customer, oldest first. All links (ledgers, payments, references) are updated. This cannot be undone automatically - take a backup first.", [total])}</p>
					<table class="table table-bordered small"><tr><th>${__("Document")}</th><th>${__("Count")}</th><th>${__("Examples")}</th></tr>${table}</table>`,
					() =>
						frappe.call({
							method: `${METHOD}.rename_existing_documents`,
							callback: () =>
								frappe.msgprint(__("Renaming started in the background. Check Background Jobs for progress.")),
						})
				);
			},
		});
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

frappe.ui.form.on("Sibyl Demo Settings", {
	build_demo(frm) {
		frappe.confirm(
			__("Create the demo companies and their data (only what's missing is added)? It runs in the background for a few minutes."),
			() => frappe.call("sibyl_app.demo.build").then((r) => {
				frappe.show_alert({ message: r.message, indicator: "blue" });
				frm.reload_doc();
			})
		);
	},
	refresh(frm) {
		if (frm.doc.enabled) {
			frm.set_intro(__("Website link for visitors: {0}", [`<a href="/login?demo=1" target="_blank">/login?demo=1</a>`]), "blue");
		}
	},
});

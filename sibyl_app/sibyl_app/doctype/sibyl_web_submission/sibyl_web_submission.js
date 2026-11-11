frappe.ui.form.on("Sibyl Web Submission", {
	refresh(frm) {
		frm.disable_save();
		if (frm.doc.reference_doctype && frm.doc.reference_name) {
			frm.add_custom_button(__("Open {0}", [__(frm.doc.reference_doctype)]), () =>
				frappe.set_route("Form", frm.doc.reference_doctype, frm.doc.reference_name)
			);
		}
	},
});

// Payment Status panel on submitted Sales Invoices: status as on today, every receipt
// date-wise with running balance, and the balance receivable. Same data as the
// "Sibyl Sales Invoice" print format (sibyl_app.invoice_payments).
frappe.ui.form.on("Sales Invoice", {
	refresh(frm) {
		if (frm.doc.docstatus !== 1 || frm.doc.is_return) return;
		frappe.call({
			method: "sibyl_app.invoice_payments.get_invoice_payment_status",
			args: { invoice: frm.doc.name },
			callback: ({ message: pay }) => pay && sibyl_render_payment_status(frm, pay),
		});
	},
});

function sibyl_render_payment_status(frm, pay) {
	const esc = frappe.utils.escape_html;
	const money = (v) => format_currency(v, frm.doc.currency);
	const colour = { paid: "green", due: "blue", overdue: "red" }[pay.tone] || "blue";
	const badge = pay.overdue_days ? `${pay.title} · ${pay.overdue_days} ${__("day(s) overdue")}` : pay.title;

	frm.dashboard.set_headline_alert(
		`<span class="indicator ${colour}">${esc(badge)}</span> &nbsp;${esc(pay.label)}`
	);

	const rows = pay.rows.length
		? pay.rows
				.map(
					(p, i) => `<tr>
					<td>${i + 1}</td>
					<td>${frappe.datetime.str_to_user(p.date)}</td>
					<td>${frappe.utils.get_form_link(p.voucher_type, p.voucher_no, true)}</td>
					<td>${esc(p.mode || "")}</td>
					<td>${esc(p.reference || "—")}</td>
					<td class="text-right">${money(p.amount)}</td>
					<td class="text-right">${money(p.balance)}</td>
				</tr>`
				)
				.join("")
		: `<tr><td colspan="7" class="text-muted text-center">${__("No payment received against this invoice yet.")}</td></tr>`;

	const html = `
		<div class="small text-muted" style="margin-bottom:6px">${__("As on")} ${frappe.datetime.str_to_user(pay.as_on)}</div>
		<table class="table table-bordered table-sm" style="margin-bottom:8px">
			<thead><tr>
				<th style="width:4%">#</th><th>${__("Date")}</th><th>${__("Receipt No.")}</th><th>${__("Mode")}</th>
				<th>${__("Reference")}</th><th class="text-right">${__("Received")}</th><th class="text-right">${__("Balance")}</th>
			</tr></thead>
			<tbody>
				<tr class="text-muted"><td></td><td>${frappe.datetime.str_to_user(frm.doc.posting_date)}</td>
					<td colspan="3">${__("Invoice amount")}</td><td></td><td class="text-right">${money(pay.invoice_amount)}</td></tr>
				${rows}
			</tbody>
		</table>
		<div class="text-right">
			${__("Total Received")}: <b>${money(pay.received)}</b> &nbsp;&nbsp;
			${__("Balance Receivable")}: <b class="text-${colour === "blue" ? "primary" : colour === "green" ? "success" : "danger"}">${money(pay.balance)}</b>
		</div>`;

	frm.dashboard.add_section(html, __("Payment Status"));
	frm.dashboard.show();
}

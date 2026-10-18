"""Payment status of a Sales Invoice as on a given day, with every receipt against it.

Built on the Payment Ledger (the same source ERPNext uses for outstanding amounts),
so receipts from Payment Entries, Journal Entries and credit notes all show up, and
cancelled / unreconciled ones (delinked) never do. Used by the "Sibyl Sales Invoice"
print format (as a jinja method) and by the Sales Invoice form.
"""

import frappe
from frappe import _
from frappe.utils import date_diff, flt, formatdate, getdate, nowdate


@frappe.whitelist()
def get_invoice_payment_status(invoice, as_on=None):
	si = frappe.get_doc("Sales Invoice", invoice) if isinstance(invoice, str) else invoice
	if isinstance(invoice, str):
		si.check_permission("read")
	as_on = getdate(as_on or nowdate())
	precision = si.precision("outstanding_amount")

	ple = frappe.qb.DocType("Payment Ledger Entry")
	entries = (
		frappe.qb.from_(ple)
		.select(ple.voucher_type, ple.voucher_no, ple.posting_date, ple.amount, ple.creation)
		.where(
			(ple.against_voucher_type == "Sales Invoice")
			& (ple.against_voucher_no == si.name)
			& (ple.delinked == 0)
		)
		.orderby(ple.posting_date)
		.orderby(ple.creation)
		.run(as_dict=True)
	)

	invoice_amount = flt(sum(e.amount for e in entries if e.voucher_no == si.name), precision)
	if not entries:  # draft / not yet posted
		invoice_amount = flt(si.rounded_total or si.grand_total, precision)

	rows, balance = [], invoice_amount
	for e in entries:
		if e.voucher_no == si.name or getdate(e.posting_date) > as_on:
			continue
		received = flt(-e.amount, precision)
		balance = flt(balance - received, precision)
		rows.append(
			frappe._dict(
				date=e.posting_date,
				voucher_type=e.voucher_type,
				voucher_no=e.voucher_no,
				amount=received,
				balance=balance,
				**_voucher_details(e.voucher_type, e.voucher_no),
			)
		)

	received_total = flt(sum(r.amount for r in rows), precision)
	return frappe._dict(
		as_on=as_on,
		invoice_amount=invoice_amount,
		received=received_total,
		balance=balance,
		rows=rows,
		**_status(si, as_on, balance, received_total, rows),
	)


def _voucher_details(voucher_type, voucher_no):
	if voucher_type == "Payment Entry":
		d = frappe.db.get_value(
			"Payment Entry", voucher_no, ["mode_of_payment", "reference_no", "reference_date"], as_dict=True
		)
		return {"mode": d.mode_of_payment or _("Payment"), "reference": d.reference_no or ""}
	if voucher_type == "Journal Entry":
		d = frappe.db.get_value("Journal Entry", voucher_no, ["voucher_type", "cheque_no"], as_dict=True)
		return {"mode": d.voucher_type or _("Journal Entry"), "reference": d.cheque_no or ""}
	if voucher_type == "Sales Invoice":
		return {"mode": _("Credit Note"), "reference": ""}
	return {"mode": _(voucher_type), "reference": ""}


def _status(si, as_on, balance, received, rows):
	"""status: paid | partly_paid | unpaid ; tone: paid | due | overdue - plus a one-line label."""
	due = getdate(si.due_date or si.posting_date)
	if balance <= 0:
		last = rows[-1].date if rows else si.posting_date
		days = date_diff(last, si.posting_date)
		when = _("on the invoice date") if days == 0 else _("{0} day(s) after the invoice date").format(days)
		return {
			"status": "paid",
			"tone": "paid",
			"title": _("Paid in Full"),
			"label": _("Settled on {0}, {1}.").format(formatdate(last), when),
		}

	status = "partly_paid" if received > 0 else "unpaid"
	title = _("Partly Paid") if received > 0 else _("Unpaid")
	overdue_days = date_diff(as_on, due)
	if overdue_days > 0:
		return {
			"status": status,
			"tone": "overdue",
			"title": title,
			"overdue_days": overdue_days,
			"label": _("Overdue by {0} day(s) - was due on {1}.").format(overdue_days, formatdate(due)),
		}
	return {
		"status": status,
		"tone": "due",
		"title": title,
		"label": _("Due today ({0}).").format(formatdate(due))
		if overdue_days == 0
		else _("Due in {0} day(s), on {1}.").format(-overdue_days, formatdate(due)),
	}

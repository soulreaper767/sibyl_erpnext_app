"""Context for the shared Sibyl document print template (templates/print/sibyl_document.html).

One layout for every transaction type: the template only draws; what to draw - title,
reference rows, which party, which columns, signature captions - is decided here per
doctype. Exposed to print formats as the jinja method `sibyl_print_context(doc)`.
"""

import frappe
from frappe.utils import cint, flt, formatdate, getdate

from sibyl_app.invoice_payments import get_invoice_payment_status

LOGO = "https://portal.sibyl.pk/files/logo-full-500.png"

# documents sent to the other party ("Original for recipient"); the rest are internal vouchers
OUTWARD = {"Quotation", "Sales Order", "Delivery Note", "Sales Invoice", "POS Invoice", "Payment Entry",
	"Request for Quotation", "Purchase Order"}

# doctypes that get a "Sibyl <doctype>" print format and become the default
SIBYL_DOCTYPES = [
	"Quotation",
	"Sales Order",
	"Delivery Note",
	"Sales Invoice",
	"POS Invoice",
	"Payment Entry",
	"Journal Entry",
	"Request for Quotation",
	"Supplier Quotation",
	"Material Request",
	"Purchase Order",
	"Purchase Receipt",
	"Purchase Invoice",
]


def sibyl_print_context(doc):
	ctx = frappe._dict(
		logo=frappe.db.get_single_value("Website Settings", "app_logo") or LOGO,
		company=doc.get("company") or frappe.db.get_default("company"),
		layout="items",  # items | payment | journal
		show_prices=True,
		meta=[],
		account=[],
		party=None,
		contact=None,
		pay=None,
		sign=("Received by", "For {0}"),
		subtitle=None,
		notes=_strip(doc.get("terms")),
	)
	ctx.update(_company(ctx.company))
	builder = BUILDERS.get(doc.doctype)
	if builder:
		builder(doc, ctx)
	ctx.sign = (ctx.sign[0], ctx.sign[1].format(ctx.company))
	ctx.footer_label = f"{ctx.title.title()} {doc.name}"
	if ctx.subtitle is None and doc.doctype in OUTWARD:
		ctx.subtitle = "Original for recipient"
	if ctx.layout == "items":
		ctx.has_discount = any(flt(r.get("discount_percentage")) for r in doc.get("items") or [])
		ctx.has_adjustments = bool(
			flt(doc.get("discount_amount")) or flt(doc.get("total_taxes_and_charges")) or flt(doc.get("rounding_adjustment"))
		)
	return ctx


# ---------------------------------------------------------------- per doctype


def _quotation(doc, ctx):
	ctx.title = "QUOTATION"
	_meta(ctx, ("Quotation No.", doc.name), ("Date", _d(doc.transaction_date)), ("Valid Till", _d(doc.valid_till)))
	if doc.quotation_to == "Customer":
		_customer_party(doc, ctx, doc.party_name, "Quotation For")
	else:
		ctx.party = _party_block("Quotation For", doc.customer_name or doc.party_name, doc.customer_address, None)
		ctx.contact = _contact(doc.contact_person)
	_acct(ctx, ("Terms", _terms(doc)), ("Currency", doc.currency))
	ctx.sign = ("Accepted by (customer)", "For {0}")


def _sales_order(doc, ctx):
	ctx.title = "SALES ORDER"
	_meta(ctx, ("Order No.", doc.name), ("Order Date", _d(doc.transaction_date)), ("Delivery Date", _d(doc.delivery_date)),
		("Customer PO", doc.po_no))
	_customer_party(doc, ctx, doc.customer, "Customer")
	_acct(ctx, ("Quotation", _refs(doc, "prevdoc_docname")), ("Terms", _terms(doc)), ("Currency", doc.currency))
	ctx.sign = ("Accepted by (customer)", "For {0}")


def _delivery_note(doc, ctx):
	ctx.title = "RETURN NOTE" if doc.is_return else "DELIVERY NOTE"
	ctx.show_prices = False
	_meta(ctx, ("Delivery No.", doc.name), ("Date", _d(doc.posting_date)), ("Customer PO", doc.po_no),
		("Vehicle No.", doc.get("vehicle_no")), ("LR No.", doc.get("lr_no")))
	_customer_party(doc, ctx, doc.customer, "Deliver To", address=doc.shipping_address_name or doc.customer_address)
	_acct(ctx, ("Sales Order", _refs(doc, "against_sales_order")), ("Transporter", doc.get("transporter_name")))
	ctx.sign = ("Received in good condition by", "For {0}")


def _sales_invoice(doc, ctx):
	ctx.title = "CREDIT NOTE" if doc.is_return else "SALES INVOICE"
	_meta(ctx, ("Invoice No.", doc.name), ("Invoice Date", _d(doc.posting_date)), ("Due Date", _d(doc.due_date)),
		("PO / Reference", doc.po_no), ("Against Invoice", doc.return_against if doc.is_return else None))
	_customer_party(doc, ctx, doc.customer, "Bill To")
	_acct(ctx, ("Sales Order", _refs(doc, "sales_order")), ("Terms", _due_note(doc)), ("Currency", doc.currency))
	if doc.docstatus == 1 and not doc.is_return:
		ctx.pay = get_invoice_payment_status(doc)
	ctx.sign = ("Received by (customer)", "For {0}")


def _purchase_invoice(doc, ctx):
	ctx.title = "DEBIT NOTE" if doc.is_return else "PURCHASE INVOICE"
	_meta(ctx, ("Voucher No.", doc.name), ("Posting Date", _d(doc.posting_date)), ("Supplier Invoice", doc.bill_no),
		("Supplier Inv. Date", _d(doc.bill_date)), ("Due Date", _d(doc.due_date)),
		("Against Invoice", doc.return_against if doc.is_return else None))
	_supplier_party(doc, ctx, "Supplier")
	_acct(ctx, ("Purchase Order", _refs(doc, "purchase_order")), ("Receipt", _refs(doc, "purchase_receipt")),
		("Currency", doc.currency))
	if doc.docstatus == 1 and not doc.is_return:
		ctx.pay = get_invoice_payment_status(doc)
	ctx.sign = ("Prepared by", "Approved for {0}")


def _purchase_order(doc, ctx):
	ctx.title = "PURCHASE ORDER"
	_meta(ctx, ("PO No.", doc.name), ("Order Date", _d(doc.transaction_date)), ("Required By", _d(doc.schedule_date)))
	_supplier_party(doc, ctx, "Supplier")
	_acct(ctx, ("Material Request", _refs(doc, "material_request")), ("Supplier Quotation", _refs(doc, "supplier_quotation")),
		("Terms", _terms(doc)), ("Currency", doc.currency))
	ctx.sign = ("Supplier acceptance", "Authorised signatory, {0}")


def _purchase_receipt(doc, ctx):
	ctx.title = "PURCHASE RETURN" if doc.is_return else "GOODS RECEIPT NOTE"
	ctx.show_prices = False
	_meta(ctx, ("GRN No.", doc.name), ("Date", _d(doc.posting_date)), ("Supplier DN", doc.get("supplier_delivery_note")))
	_supplier_party(doc, ctx, "Received From")
	_acct(ctx, ("Purchase Order", _refs(doc, "purchase_order")), ("Warehouse", doc.get("set_warehouse")))
	ctx.sign = ("Received by (store)", "Checked by, {0}")


def _supplier_quotation(doc, ctx):
	ctx.title = "SUPPLIER QUOTATION"
	_meta(ctx, ("Reference No.", doc.name), ("Date", _d(doc.transaction_date)), ("Valid Till", _d(doc.get("valid_till"))))
	_supplier_party(doc, ctx, "Supplier")
	_acct(ctx, ("RFQ", _refs(doc, "request_for_quotation")), ("Currency", doc.currency))
	ctx.sign = ("Prepared by", "Approved for {0}")


def _rfq(doc, ctx):
	ctx.title = "REQUEST FOR QUOTATION"
	ctx.show_prices = False
	_meta(ctx, ("RFQ No.", doc.name), ("Date", _d(doc.transaction_date)), ("Quote By", _d(doc.get("schedule_date"))))
	names = [s.supplier_name or s.supplier for s in doc.get("suppliers") or []]
	ctx.party = frappe._dict(label="Suppliers", name=", ".join(names) or "—", lines=[], tax_id=None)
	ctx.notes = _strip(doc.get("message_for_supplier")) or ctx.notes
	_acct(ctx, ("Material Request", _refs(doc, "material_request")))
	ctx.sign = ("Prepared by", "For {0}")


def _material_request(doc, ctx):
	ctx.title = f"MATERIAL REQUEST"
	ctx.show_prices = False
	_meta(ctx, ("Request No.", doc.name), ("Date", _d(doc.transaction_date)), ("Required By", _d(doc.schedule_date)))
	ctx.party = frappe._dict(label="Request Type", name=doc.material_request_type,
		lines=[f"Warehouse: {doc.set_warehouse}"] if doc.get("set_warehouse") else [], tax_id=None)
	_acct(ctx, ("Requested By", frappe.db.get_value("User", doc.owner, "full_name")), ("Status", doc.status))
	ctx.sign = ("Requested by", "Approved for {0}")


def _payment_entry(doc, ctx):
	ctx.layout = "payment"
	ctx.title = {"Receive": "PAYMENT RECEIPT", "Pay": "PAYMENT VOUCHER"}.get(doc.payment_type, "INTERNAL TRANSFER")
	_meta(ctx, ("Voucher No.", doc.name), ("Date", _d(doc.posting_date)), ("Mode", doc.mode_of_payment),
		("Reference No.", doc.reference_no), ("Reference Date", _d(doc.reference_date)))
	if doc.party_type == "Customer":
		_customer_party(doc, ctx, doc.party, "Received From" if doc.payment_type == "Receive" else "Paid To", address=doc.get("party_address"))
	elif doc.party_type == "Supplier":
		ctx.party = _party_block("Paid To" if doc.payment_type == "Pay" else "Received From", doc.party_name,
			doc.get("party_address") or _linked("Supplier", doc.party, "Address"), frappe.db.get_value("Supplier", doc.party, "tax_id"))
		ctx.contact = _contact(doc.get("contact_person") or _linked("Supplier", doc.party, "Contact"))
	elif doc.party:
		ctx.party = frappe._dict(label=doc.party_type, name=doc.party_name or doc.party, lines=[], tax_id=None)
	_acct(ctx, ("From Account", _acc(doc.paid_from)), ("To Account", _acc(doc.paid_to)), ("Currency", doc.paid_to_account_currency))
	ctx.amount = doc.received_amount if doc.payment_type == "Receive" else doc.paid_amount
	ctx.amount_label = "Amount Received" if doc.payment_type == "Receive" else "Amount Paid"
	ctx.words = frappe.utils.money_in_words(ctx.amount, doc.paid_to_account_currency or doc.paid_from_account_currency)
	ctx.notes = _strip(doc.get("remarks"))
	ctx.sign = ("Received by", "For {0}") if doc.payment_type == "Pay" else ("Paid by (customer)", "Received for {0}")


def _journal_entry(doc, ctx):
	ctx.layout = "journal"
	ctx.title = {
		"Bank Entry": "BANK VOUCHER", "Cash Entry": "CASH VOUCHER", "Credit Note": "CREDIT NOTE",
		"Debit Note": "DEBIT NOTE", "Contra Entry": "CONTRA VOUCHER", "Opening Entry": "OPENING VOUCHER",
	}.get(doc.voucher_type, "JOURNAL VOUCHER")
	_meta(ctx, ("Voucher No.", doc.name), ("Date", _d(doc.posting_date)), ("Cheque / Ref.", doc.get("cheque_no")),
		("Ref. Date", _d(doc.get("cheque_date"))))
	ctx.words = doc.get("total_amount_in_words")
	ctx.notes = _strip(doc.get("user_remark")) or _strip(doc.get("remark"))
	ctx.sign = ("Prepared by", "Approved for {0}")


BUILDERS = {
	"Quotation": _quotation,
	"Sales Order": _sales_order,
	"Delivery Note": _delivery_note,
	"Sales Invoice": _sales_invoice,
	"POS Invoice": _sales_invoice,
	"Payment Entry": _payment_entry,
	"Journal Entry": _journal_entry,
	"Request for Quotation": _rfq,
	"Supplier Quotation": _supplier_quotation,
	"Material Request": _material_request,
	"Purchase Order": _purchase_order,
	"Purchase Receipt": _purchase_receipt,
	"Purchase Invoice": _purchase_invoice,
}


# ---------------------------------------------------------------- helpers


def _company(company):
	tax_id = frappe.db.get_value("Company", company, "tax_id") if company else None
	addr = None
	name = _linked("Company", company, "Address") if company else None
	if name:
		addr = frappe.db.get_value("Address", name, ["address_line1", "address_line2", "city", "state", "pincode", "phone", "email_id"], as_dict=True)
	line = ""
	if addr:
		street = ", ".join(x for x in (addr.address_line1, addr.address_line2) if x)
		place = ", ".join(x for x in (addr.city, addr.state) if x) + (f" {addr.pincode}" if addr.pincode else "")
		line = ", ".join(x for x in (street, place.strip()) if x)
	extra = [x for x in (f"NTN {tax_id}" if tax_id else None, addr and addr.phone, addr and addr.email_id) if x]
	return {"company_address": line, "company_extra": " · ".join(extra), "company_tax_id": tax_id}


def _linked(link_doctype, link_name, parenttype):
	return frappe.db.get_value("Dynamic Link", {"link_doctype": link_doctype, "link_name": link_name, "parenttype": parenttype}, "parent")


def _address_lines(name):
	if not name:
		return []
	a = frappe.db.get_value("Address", name, ["address_line1", "address_line2", "city", "state", "pincode", "country"], as_dict=True)
	if not a:
		return []
	l1 = ", ".join(x for x in (a.address_line1, a.address_line2) if x)
	l2 = ", ".join(x for x in (a.city, a.state) if x) + (f" {a.pincode}" if a.pincode else "") + (f", {a.country}" if a.country else "")
	return [x.strip(", ") for x in (l1, l2) if x and x.strip(", ")]


def _party_block(label, name, address_name, tax_id):
	return frappe._dict(label=label, name=name, lines=_address_lines(address_name), tax_id=tax_id)


def _contact(name):
	if not name:
		return None
	c = frappe.db.get_value("Contact", name, ["first_name", "last_name", "mobile_no", "phone", "email_id"], as_dict=True)
	if not c:
		return None
	c.full_name = " ".join(x for x in (c.first_name, c.last_name) if x)
	return c


def _customer_party(doc, ctx, customer, label, address=None):
	address = address or doc.get("customer_address") or _linked("Customer", customer, "Address")
	tax_id = doc.get("tax_id") or frappe.db.get_value("Customer", customer, "tax_id")
	ctx.party = _party_block(label, doc.get("customer_name") or doc.get("party_name") or customer, address, tax_id)
	ctx.contact = _contact(doc.get("contact_person") or _linked("Customer", customer, "Contact"))
	cid = frappe.db.get_value("Customer", customer, "sibyl_customer_id")
	if cid:
		ctx.account.insert(0, ("Customer ID", cid))


def _supplier_party(doc, ctx, label):
	address = doc.get("supplier_address") or _linked("Supplier", doc.supplier, "Address")
	tax_id = doc.get("tax_id") or frappe.db.get_value("Supplier", doc.supplier, "tax_id")
	ctx.party = _party_block(label, doc.get("supplier_name") or doc.supplier, address, tax_id)
	ctx.contact = _contact(doc.get("contact_person") or _linked("Supplier", doc.supplier, "Contact"))


def _meta(ctx, *rows):
	ctx.meta += [(k, v) for k, v in rows if v]


def _acct(ctx, *rows):
	ctx.account += [(k, v) for k, v in rows if v]


def _refs(doc, field):
	seen = []
	for row in doc.get("items") or []:
		v = row.get(field)
		if v and v not in seen:
			seen.append(v)
	return ", ".join(seen)


def _d(value):
	return formatdate(value) if value else None


def _strip(html):
	text = frappe.utils.strip_html(html or "").strip()
	return text or None


def _acc(account):
	return frappe.db.get_value("Account", account, "account_name") if account else None


def _terms(doc):
	return doc.get("payment_terms_template")


def _due_note(doc):
	if doc.get("due_date") and getdate(doc.due_date) == getdate(doc.posting_date):
		return "Advance"
	return f"Due {formatdate(doc.due_date)}" if doc.get("due_date") else None

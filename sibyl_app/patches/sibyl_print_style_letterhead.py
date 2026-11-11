import frappe

from sibyl_app.print_utils import LOGO, _company

STYLE = "Sibyl"
LETTER_HEAD = "Sibyl Letterhead"


def execute():
	"""Sibyl look for every document printed with Frappe's generic layout: a "Sibyl" Print Style
	(set system-wide) and a default "Sibyl Letterhead". Re-runnable: both are rebuilt from the app's
	files and the company's current details."""
	css = frappe.render_template(
		'{% include "sibyl_app/templates/print/inter_fonts.css" %}\n'
		'{% include "sibyl_app/templates/print/sibyl_print_style.css" %}',
		{},
	)
	style = frappe.get_doc("Print Style", STYLE) if frappe.db.exists("Print Style", STYLE) else frappe.new_doc("Print Style")
	style.update({"print_style_name": STYLE, "css": css, "disabled": 0, "standard": 0})
	style.save(ignore_permissions=True)

	company = frappe.db.get_default("company")
	info = _company(company) if company else {}
	logo = frappe.db.get_single_value("Website Settings", "app_logo") or LOGO
	content = f"""
<table style="width:100%; border-collapse:collapse;"><tr>
  <td style="vertical-align:bottom; padding:0 !important;">
    <img src="{logo}" style="height:28px; margin-bottom:4px;">
    <div style="font-size:10.5pt; font-weight:700; color:#14213d;">{company or ""}</div>
    <div style="font-size:7.2pt; color:#667085; line-height:1.45;">{info.get("company_address", "")}<br>{info.get("company_extra", "")}</div>
  </td>
</tr></table>
<div style="border-top:1.5px solid #14213d; margin:8px 0 2px 0;"></div>
"""
	footer = f"""
<div style="border-top:1px solid #d0d5dd; padding-top:3px; font-size:6.6pt; color:#98a2b3;">
  {company or ""}{(" &middot; " + "NTN " + info["company_tax_id"]) if info.get("company_tax_id") else ""}
</div>
"""
	lh = frappe.get_doc("Letter Head", LETTER_HEAD) if frappe.db.exists("Letter Head", LETTER_HEAD) else frappe.new_doc("Letter Head")
	lh.update({"letter_head_name": LETTER_HEAD, "source": "HTML", "content": content, "footer_source": "HTML",
		"footer": footer, "is_default": 1, "disabled": 0})
	lh.save(ignore_permissions=True)

	settings = frappe.get_single("Print Settings")
	settings.print_style = STYLE
	settings.save(ignore_permissions=True)

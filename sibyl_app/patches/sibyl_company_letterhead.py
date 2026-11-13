import frappe

LETTER_HEAD = "Sibyl Letterhead"

# Rendered by Frappe for every print with {"doc": ...}: the header and footer follow the company of the
# document being printed (its logo, address, NTN) instead of always showing the default company.
CONTENT = """{%- set b = sibyl_company_brand(doc) -%}
<table style="width:100%; border-collapse:collapse;"><tr>
  <td style="vertical-align:bottom; padding:0 !important;">
    <img src="{{ b.logo }}" style="height:28px; margin-bottom:4px;">
    <div style="font-size:10.5pt; font-weight:700; color:#14213d;">{{ b.company }}</div>
    <div style="font-size:7.2pt; color:#667085; line-height:1.45;">{{ b.company_address or "" }}{% if b.company_extra %}<br>{{ b.company_extra }}{% endif %}</div>
  </td>
</tr></table>
<div style="border-top:1.5px solid #14213d; margin:8px 0 2px 0;"></div>
"""

FOOTER = """{%- set b = sibyl_company_brand(doc) -%}
<div style="border-top:1px solid #d0d5dd; padding-top:3px; font-size:6.6pt; color:#98a2b3;">
  {{ b.company }}{% if b.company_tax_id %} &middot; NTN {{ b.company_tax_id }}{% endif %}
</div>
"""


def execute():
	if not frappe.db.exists("Letter Head", LETTER_HEAD):
		from sibyl_app.patches.sibyl_print_style_letterhead import execute as build

		build()
	lh = frappe.get_doc("Letter Head", LETTER_HEAD)
	lh.update({"source": "HTML", "content": CONTENT, "footer_source": "HTML", "footer": FOOTER, "disabled": 0})
	lh.save(ignore_permissions=True)

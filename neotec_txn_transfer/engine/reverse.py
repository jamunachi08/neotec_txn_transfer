"""Optional: cancel migrated documents in the source company (same-site mode only)."""

import frappe
from frappe import _

from .constants import LEDGER, SETUP, SI
from .progress import heartbeat, job, set_state


def _guards(setup):
	out = []
	for line in (setup.zatca_guard or "").splitlines():
		parts = [p.strip() for p in line.split(":")]
		if parts[0] == "field" and len(parts) == 2:
			out.append(("field", parts[1], None))
		elif parts[0] == "link" and len(parts) == 3:
			out.append(("link", parts[1], parts[2]))
	return out


def is_protected(doc, guards):
	if doc.doctype != SI:
		return False
	for kind, a, b in guards:
		if kind == "field" and doc.meta.has_field(a) and doc.get(a):
			return True
		if kind == "link" and frappe.db.exists("DocType", a) and frappe.db.exists(a, {b: doc.name}):
			return True
	return False


@job("Reverse source")
def reverse_job():
	setup = frappe.get_single(SETUP)
	if setup.source_mode != "Same Site":
		frappe.throw(_("Reversing the source is only supported in Same Site mode"))
	if setup.phase != "Verified":
		frappe.throw(_("Verify must pass before reversing the source"))
	guards = _guards(setup)
	rows = frappe.get_all(LEDGER, filters={"status": "Done", "reversed": 0},
		fields=["name", "source_doctype", "source_name"], order_by="seq desc", limit_page_length=0)
	skipped = failed = 0
	for i, r in enumerate(rows, 1):
		try:
			doc = frappe.get_doc(r.source_doctype, r.source_name)
			if doc.docstatus != 1:
				frappe.db.set_value(LEDGER, r.name, {"reversed": 1, "reverse_note": _("already not submitted")})
			elif is_protected(doc, guards):
				skipped += 1
				frappe.db.set_value(LEDGER, r.name, "reverse_note",
					_("ZATCA-reported: not cancelled, issue a credit note"))
			else:
				doc.flags.ignore_permissions = True
				doc.cancel()
				frappe.db.set_value(LEDGER, r.name, {"reversed": 1, "reverse_note": _("cancelled")})
			frappe.db.commit()
		except Exception as e:
			frappe.db.rollback()
			failed += 1
			frappe.db.set_value(LEDGER, r.name, "reverse_note", frappe.utils.strip_html(str(e))[:1000])
			frappe.db.commit()
		heartbeat(_("Reverse: {0}/{1}").format(i, len(rows)), done=i, total=len(rows))
	set_state(phase="Reversed",
		progress=_("Source reversal: {0} cancelled, {1} ZATCA-protected, {2} failed").format(
			len(rows) - skipped - failed, skipped, failed))

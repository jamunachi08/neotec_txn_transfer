"""Compare every migrated document against the snapshot taken from the source at scan time."""

import json

import frappe
from frappe import _
from frappe.utils import flt

from .constants import AMOUNT_TOL, LEDGER, PE, SETUP
from .progress import heartbeat, job, set_state
from .target import make_target


def _off(a, b):
	return abs(flt(a) - flt(b)) > AMOUNT_TOL


@job("Verify")
def verify_job():
	setup = frappe.get_single(SETUP)
	tgt = make_target(setup)
	rows = frappe.get_all(
		LEDGER, filters={"status": "Done"},
		fields=["name", "source_doctype", "source_name", "target_name", "snapshot"],
		order_by="seq asc", limit_page_length=0,
	)
	if not rows:
		frappe.throw(_("Nothing to verify yet"))
	bad = 0
	for i, r in enumerate(rows, 1):
		snap = json.loads(r.snapshot or "{}")
		dt, t = r.source_doctype, r.target_name
		issues = []
		total = tgt.get_value(dt, t, "paid_amount" if dt == PE else "grand_total")
		if _off(total, snap.get("total")):
			issues.append(_("total {0} vs source {1}").format(flt(total, 2), flt(snap.get("total"), 2)))
		if "outstanding" in snap:
			o = tgt.get_value(dt, t, "outstanding_amount")
			if _off(o, snap["outstanding"]):
				issues.append(_("outstanding {0} vs source {1}").format(flt(o, 2), flt(snap["outstanding"], 2)))
		gl = tgt.gl_debit(dt, t)
		if _off(gl, snap.get("gl_debit")):
			issues.append(_("GL debit {0} vs source {1}").format(flt(gl, 2), flt(snap.get("gl_debit"), 2)))
		if "stock" in snap:
			ts, ss = tgt.stock_by_item(dt, t), snap["stock"] or {}
			for item in sorted(set(ts) | set(ss)):
				if _off(ts.get(item), ss.get(item)):
					issues.append(_("stock {0}: {1} vs source {2}").format(item, flt(ts.get(item), 3), flt(ss.get(item), 3)))
		bad += bool(issues)
		frappe.db.set_value(LEDGER, r.name, {"verify_status": "Mismatch" if issues else "OK",
			"verify_note": "; ".join(issues)[:1500]}, update_modified=False)
		if i % 50 == 0:
			heartbeat(_("Verify: {0}/{1}").format(i, len(rows)), done=i, total=len(rows))
	frappe.db.commit()
	pending = frappe.db.count(LEDGER, {"status": ["in", ["Pending", "Failed"]]})
	set_state(
		phase="Verified" if not bad else "Verify Mismatch",
		progress=_("Verify: {0} OK, {1} mismatched, {2} not yet migrated").format(len(rows) - bad, bad, pending),
	)

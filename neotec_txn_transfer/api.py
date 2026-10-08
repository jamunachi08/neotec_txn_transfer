"""Whitelisted endpoints for the Transfer Setup form."""

import csv
import io

import frappe
from frappe import _
from frappe.utils import cint
from frappe.utils.background_jobs import is_job_enqueued

from .engine import mapping
from .engine.constants import APP, LEDGER, SETUP
from .engine.purge import purge

_JOBS = {
	"scan": "neotec_txn_transfer.engine.scan.scan_job",
	"dry_run": "neotec_txn_transfer.engine.runner.dry_run_job",
	"run": "neotec_txn_transfer.engine.runner.run_job",
	"verify": "neotec_txn_transfer.engine.verify.verify_job",
	"reverse": "neotec_txn_transfer.engine.reverse.reverse_job",
}


def _guard():
	frappe.only_for("System Manager")


def _alive():
	"""True while any transfer job is queued or running in the worker."""
	return any(is_job_enqueued(f"{APP}::{a}") for a in _JOBS)


def _heal_lock():
	"""Clear a lock left behind by a job the worker killed (timeout, restart, deploy)."""
	if cint(frappe.db.get_single_value(SETUP, "job_running")) and not _alive():
		frappe.db.set_single_value(SETUP, {"job_running": 0,
			"progress": _("The previous job stopped without finishing (worker restart, deploy or timeout). Start it again.")})
		frappe.db.commit()
		return True
	return False


@frappe.whitelist()
def start(action):
	_guard()
	if action not in _JOBS:
		frappe.throw(_("Unknown action"))
	_heal_lock()
	if cint(frappe.db.get_single_value(SETUP, "job_running")):
		frappe.throw(_("A job is already running. Wait for it to finish."))
	frappe.db.set_single_value(SETUP, {"job_running": 1, "progress": _("{0} queued").format(action)})
	frappe.enqueue(
		_JOBS[action], queue="long", timeout=6 * 3600, job_id=f"{APP}::{action}", deduplicate=True,
		enqueue_after_commit=True, ntt_user=frappe.session.user,
	)
	return True


@frappe.whitelist()
def job_status():
	_guard()
	healed = _heal_lock()
	return {"running": cint(frappe.db.get_single_value(SETUP, "job_running")), "alive": _alive(), "healed": healed}


@frappe.whitelist()
def resolve_uncertain(ledger, target_name=None):
	"""After checking the target by hand: record the document as created (with its name) or not created."""
	_guard()
	if frappe.db.get_value(LEDGER, ledger, "status") != "Uncertain":
		frappe.throw(_("Only Uncertain rows can be resolved"))
	if target_name:
		frappe.db.set_value(LEDGER, ledger, {"status": "Done", "target_name": target_name.strip(),
			"message": _("Confirmed created on target by {0}").format(frappe.session.user)})
	else:
		frappe.db.set_value(LEDGER, ledger, {"status": "Pending",
			"message": _("Confirmed not created on target by {0}").format(frappe.session.user)})
	return True


@frappe.whitelist()
def reset_job_lock():
	_guard()
	frappe.db.set_single_value(SETUP, "job_running", 0)
	return True


@frappe.whitelist()
def clear_unmapped():
	_guard()
	mapping.clear_unmapped_non_core()
	return mapping.unmapped_count()


@frappe.whitelist()
def status_counts():
	_guard()
	rows = frappe.db.sql(
		f"select source_doctype, status, count(*) from `tab{LEDGER}` group by source_doctype, status", as_list=True
	)
	return {"rows": rows, "unmapped": mapping.unmapped_count()}


@frappe.whitelist()
def reconciliation_csv():
	"""Returned to the browser only; never stored as a File on the site."""
	_guard()
	rows = frappe.get_all(
		LEDGER,
		fields=["seq", "source_doctype", "source_name", "target_name", "status", "verify_status",
			"verify_note", "reversed", "reverse_note", "message"],
		order_by="seq asc", limit_page_length=0,
	)
	setup = frappe.get_single(SETUP)
	buf = io.StringIO()
	w = csv.writer(buf)
	w.writerow(["Source company", setup.source_company, "Target company", setup.target_company,
		"Range", f"{setup.from_date} to {setup.to_date}", "Mode", setup.source_mode])
	w.writerow(["Seq", "DocType", "Source", "Target", "Status", "Verify", "Verify note", "Reversed",
		"Reverse note", "Message"])
	for r in rows:
		w.writerow([r.seq, r.source_doctype, r.source_name, r.target_name or "", r.status, r.verify_status or "",
			r.verify_note or "", r.reversed, r.reverse_note or "", r.message or ""])
	return buf.getvalue()


@frappe.whitelist()
def finalize(confirm):
	_guard()
	if cint(frappe.db.get_single_value(SETUP, "job_running")):
		frappe.throw(_("A job is running"))
	target = frappe.db.get_single_value(SETUP, "target_company")
	abbr = frappe.db.get_value("Company", target, "abbr") if target else None
	if not abbr or (confirm or "").strip() != abbr:
		frappe.throw(_("Type the target company abbreviation ({0}) to confirm").format(abbr or "?"))
	purge()
	return _("All transfer data removed. Uninstall the app from the site now.")

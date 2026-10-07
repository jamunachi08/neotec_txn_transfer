"""Dry run and real run. Each real document commits on its own; a failure never leaves half a document."""

import json
import traceback

import frappe
from frappe import _
from frappe.utils import cint

from .builder import BuildContext, build
from .constants import LEDGER, SETUP, SI, doc_key
from .mapping import MapError, load_maps, unmapped_count
from .progress import heartbeat, job, publish, set_state
from .scan import prefixes_of
from .walker import make_skip

RUNNABLE_PHASES = ("Scanned", "Dry Run Done", "Run Partial")


def _gate(setup):
	if setup.phase not in RUNNABLE_PHASES:
		frappe.throw(_("Run Scan first (current phase: {0})").format(setup.phase))
	summary = json.loads(setup.summary_json or "{}")
	if summary.get("global_blockers"):
		frappe.throw(_("Resolve blockers first: {0}").format("; ".join(summary["global_blockers"])))
	n = unmapped_count()
	if n:
		frappe.throw(_("{0} mapping row(s) are unmapped. Map them or set them to Clear.").format(n))
	if frappe.db.count(LEDGER, {"status": ["in", ["Pending", "Failed"]], "source_doctype": SI}) and not cint(
		setup.zatca_ack
	):
		frappe.throw(_("Confirm that ZATCA submission is disabled for the target company during the run."))


def _context(setup):
	docmap, rowmap = {}, {}
	for r in frappe.get_all(
		LEDGER, filters={"status": "Done"}, fields=["source_doctype", "source_name", "target_name", "row_map"],
		limit_page_length=0,
	):
		docmap[doc_key(r.source_doctype, r.source_name)] = r.target_name
		rowmap.update(json.loads(r.row_map or "{}"))
	prefixes = prefixes_of(setup)
	return BuildContext(
		load_maps(), docmap, rowmap, setup.source_mode == "Remote Site", setup.target_company,
		make_skip(prefixes), prefixes,
	)


def _rows(limit=0):
	return frappe.get_all(
		LEDGER, filters={"status": ["in", ["Pending", "Failed"]]},
		fields=["name", "seq", "source_doctype", "source_name", "deps"],
		order_by="seq asc", limit_page_length=limit or 0,
	)


def _create(r, ctx, preserve_name):
	src_doc = json.loads(frappe.db.get_value(LEDGER, r.name, "src_doc"))
	out, row_sources, notes = build(src_doc, r.source_doctype, ctx)
	doc = frappe.get_doc(out)
	doc.flags.ignore_permissions = True
	if preserve_name:
		doc.insert(set_name=r.source_name)
	else:
		doc.insert()
	doc.submit()
	rm = {}
	for table, srcs in row_sources.items():
		new_rows = doc.get(table) or []
		if len(new_rows) == len(srcs):
			for s, n in zip(srcs, new_rows):
				if s:
					rm[s] = n.name
	ctx.docmap[doc_key(r.source_doctype, r.source_name)] = doc.name
	ctx.rowmap.update(rm)
	return doc.name, rm, notes


def _missing_deps(r, ctx):
	return [d for d in json.loads(r.deps or "[]") if d not in ctx.docmap]


def _err(e):
	if isinstance(e, MapError):
		return str(e)
	msg = frappe.utils.strip_html(str(e)) or e.__class__.__name__
	return (msg + "\n" + traceback.format_exc(limit=2)[-800:])[:1500]


@job("Run")
def run_job():
	setup = frappe.get_single(SETUP)
	_gate(setup)
	ctx = _context(setup)
	preserve = cint(setup.preserve_names) and setup.source_mode == "Remote Site"
	rows = _rows()
	set_state(progress=_("Running {0} documents").format(len(rows)))
	failed = 0
	for i, r in enumerate(rows, 1):
		missing = _missing_deps(r, ctx)
		if missing:
			frappe.db.set_value(LEDGER, r.name, {"status": "Failed",
				"message": _("waiting for: {0}").format(", ".join(missing[:5]))}, update_modified=False)
			frappe.db.commit()
			failed += 1
			continue
		try:
			name, rm, notes = _create(r, ctx, preserve)
			frappe.db.set_value(LEDGER, r.name, {"status": "Done", "target_name": name,
				"row_map": json.dumps(rm), "message": "; ".join(notes)[:1000]}, update_modified=False)
			frappe.db.commit()
		except Exception as e:
			frappe.db.rollback()
			frappe.db.set_value(LEDGER, r.name, {"status": "Failed", "message": _err(e)}, update_modified=False)
			frappe.db.commit()
			failed += 1
		heartbeat(_("Run: {0}/{1} ({2} failed)").format(i, len(rows), failed), done=i, total=len(rows))
	set_state(phase="Run Partial" if failed else "Run Done",
		progress=_("Run finished: {0} processed, {1} failed").format(len(rows), failed))


@job("Dry run")
def dry_run_job():
	setup = frappe.get_single(SETUP)
	_gate(setup)
	ctx = _context(setup)
	preserve = cint(setup.preserve_names) and setup.source_mode == "Remote Site"
	rows = _rows(cint(setup.dry_run_limit))
	set_state(progress=_("Dry run on {0} documents (progress shows only while this form is open)").format(len(rows)))

	results = {}
	real_commit = frappe.db.commit
	frappe.db.commit = lambda *a, **k: None  # nothing in the dry run may persist
	try:
		for i, r in enumerate(rows, 1):
			missing = _missing_deps(r, ctx)
			if missing:
				results[r.name] = ("Failed", _("depends on failed: {0}").format(", ".join(missing[:5])))
				continue
			sp = f"ntt_{i}"
			frappe.db.savepoint(sp)
			try:
				_name, _rm, notes = _create(r, ctx, preserve)
				results[r.name] = ("OK", "; ".join(notes))
			except Exception as e:
				frappe.db.rollback(save_point=sp)
				results[r.name] = ("Failed", _err(e))
			publish(_("Dry run: {0}/{1}").format(i, len(rows)), done=i, total=len(rows))
	finally:
		frappe.db.rollback()
		frappe.db.commit = real_commit

	bad = 0
	for name, (status, note) in results.items():
		bad += status == "Failed"
		frappe.db.set_value(LEDGER, name, {"dry_status": status, "dry_note": (note or "")[:1500]},
			update_modified=False)
	frappe.db.commit()
	set_state(phase="Dry Run Done",
		progress=_("Dry run: {0} OK, {1} failed (nothing was saved)").format(len(results) - bad, bad))

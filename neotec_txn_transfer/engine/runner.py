"""Dry run and real run. Each real document commits on its own; a failure never leaves half a document."""

import json
import traceback

import frappe
from frappe import _
from frappe.utils import cint

from .builder import BuildContext, build
from .target import is_cross_site, make_target
from .source import UncertainError
from .walker import dt_info
from .constants import KEEP_AS_IS, LEDGER, SETUP, SI, TRANSFER_DOCTYPES, doc_key
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
		load_maps(), docmap, rowmap, is_cross_site(setup), setup.target_company,
		make_skip(prefixes), prefixes, make_target(setup),
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
	name, new_rows = ctx.target.create(out, r.source_name if preserve_name else None)
	rm = {}
	for table, srcs in row_sources.items():
		created = new_rows.get(table) or []
		if len(created) == len(srcs):
			for s, n in zip(srcs, created):
				if s and n:
					rm[s] = n
	ctx.docmap[doc_key(r.source_doctype, r.source_name)] = name
	ctx.rowmap.update(rm)
	return name, rm, notes


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
		except UncertainError as e:
			frappe.db.rollback()
			frappe.db.set_value(LEDGER, r.name, {"status": "Uncertain", "message": _(
				"{0}. Check the target for this document before continuing, then mark this ledger row "
				"as created or not created.").format(e)}, update_modified=False)
			frappe.db.commit()
			set_state(phase="Run Partial", progress=_("Run paused: the target did not answer for {0} {1}").format(
				r.source_doctype, r.source_name))
			return
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
	if ctx.target.is_remote:
		return _preflight(rows, ctx)
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


def _target_links(out, doctype):
	"""(link doctype, value) pairs a built document needs on the target."""
	meta = frappe.get_meta(doctype)
	pairs = set()

	def scan(row, m):
		for df in m.fields:
			if df.fieldtype != "Link" or not row.get(df.fieldname):
				continue
			ld = df.options
			if ld in TRANSFER_DOCTYPES or ld in KEEP_AS_IS or not dt_info(ld)[0]:
				continue
			pairs.add((ld, row[df.fieldname]))

	scan(out, meta)
	for tf in meta.get_table_fields():
		cm = frappe.get_meta(tf.options)
		for row in out.get(tf.fieldname) or []:
			scan(row, cm)
	return pairs


def _preflight(rows, ctx):
	"""Push mode: a remote site cannot be rolled back, so check without writing anything to it.
	Builds every document (all mappings must resolve) and confirms every linked master exists on the target."""
	results, owners = {}, {}
	for i, r in enumerate(rows, 1):
		try:
			src_doc = json.loads(frappe.db.get_value(LEDGER, r.name, "src_doc"))
			out, _rs, _notes = build(src_doc, r.source_doctype, ctx)
			results[r.name] = ["OK", []]
			for pair in _target_links(out, r.source_doctype):
				owners.setdefault(pair, []).append(r.name)
		except Exception as e:
			results[r.name] = ["Failed", [_err(e)]]
		if i % 50 == 0 or i == len(rows):
			heartbeat(_("Pre-flight: built {0}/{1}").format(i, len(rows)), done=i, total=len(rows))
	needs = {}
	for ld, val in owners:
		needs.setdefault(ld, set()).add(val)
	heartbeat(_("Pre-flight: checking {0} linked records on the target").format(len(owners)))
	for ld, val in sorted(ctx.target.missing(needs)):
		for rn in owners[(ld, val)]:
			results[rn][0] = "Failed"
			results[rn][1].append(_("missing on target: {0} {1}").format(ld, val))
	bad = 0
	for name, (status, notes) in results.items():
		bad += status == "Failed"
		frappe.db.set_value(LEDGER, name, {"dry_status": status, "dry_note": "; ".join(notes)[:1500]},
			update_modified=False)
	frappe.db.commit()
	set_state(phase="Dry Run Done", progress=_(
		"Pre-flight: {0} OK, {1} with problems. Nothing was sent to the target; "
		"document validations run at Run time, one document per request.").format(len(results) - bad, bad))

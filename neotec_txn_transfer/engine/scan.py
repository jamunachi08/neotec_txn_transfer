"""Scan: collect source documents, resolve dependencies, order them, prepare mappings."""

import heapq
import json
from concurrent.futures import ThreadPoolExecutor

import frappe
from frappe import _
from frappe.utils import cint, flt

from . import mapping
from .constants import (
	ADDR_MAP, COMPANY_ADDRESS_FIELDS, K_CLEAR, K_DOC, K_GLOBAL, K_SCOPED, KEEP_AS_IS, LEDGER,
	PE, SERIES_PREFIX, SETUP, STOCK_ALWAYS, STOCK_IF_UPDATE, TRANSFER_DOCTYPES, doc_key,
)
from .progress import heartbeat, job, set_state
from .source import make_source
from .walker import classify, iter_refs, is_pe_reference, make_skip, prepare


def prefixes_of(setup):
	return [p.strip() for p in (setup.strip_field_prefixes or "").splitlines() if p.strip()]


def enabled_doctypes(setup):
	return [dt for dt, (chk, _r, _d) in TRANSFER_DOCTYPES.items() if cint(setup.get(chk))]


def topo_sort(nodes, deps, sortkey):
	indeg = {n: 0 for n in nodes}
	children = {n: [] for n in nodes}
	for n in nodes:
		for d in deps.get(n, ()):
			if d in indeg:
				indeg[n] += 1
				children[d].append(n)
	heap = [(sortkey(n), n) for n in nodes if indeg[n] == 0]
	heapq.heapify(heap)
	order = []
	while heap:
		_k, n = heapq.heappop(heap)
		order.append(n)
		for c in children[n]:
			indeg[c] -= 1
			if indeg[c] == 0:
				heapq.heappush(heap, (sortkey(c), c))
	done = set(order)
	return order, [n for n in nodes if n not in done]


def propagate_exclusion(nodes, deps, excluded):
	excluded = set(excluded)
	changed = True
	while changed:
		changed = False
		for n in nodes:
			if n not in excluded and deps.get(n, set()) & excluded:
				excluded.add(n)
				changed = True
	return excluded


def _enrich_bundles(doc, doctype, src, key, doc_blockers):
	meta = frappe.get_meta(doctype)
	for tf in meta.get_table_fields():
		for row in doc.get(tf.fieldname) or []:
			for f, tag in (("serial_and_batch_bundle", "__sbb"), ("rejected_serial_and_batch_bundle", "__rsbb")):
				b = row.get(f)
				if not b:
					continue
				entries = src.bundle_entries(b)
				serials = [e.get("serial_no") for e in entries if e.get("serial_no")]
				batches = {}
				for e in entries:
					if e.get("batch_no"):
						batches[e["batch_no"]] = batches.get(e["batch_no"], 0) + abs(flt(e.get("qty")))
				row[tag] = {"serials": serials, "batches": batches}
				if len(batches) > 1:
					doc_blockers.setdefault(key, []).append(
						_("row {0} ({1}) uses {2} batches in one row; split it in the source").format(
							row.get("idx"), row.get("item_code"), len(batches)
						)
					)


def _fetch(src, doctype, name):
	"""Network-only work (safe in a thread): the document and its source-side snapshot."""
	doc = src.get_doc(doctype, name)
	return doc, _snapshot(doc, doctype, src)


def _fetch_all(src, items):
	if src.is_remote:
		with ThreadPoolExecutor(max_workers=8) as ex:
			yield from zip(items, ex.map(lambda it: _fetch(src, *it), items))
	else:
		for it in items:
			yield it, _fetch(src, *it)


def _snapshot(doc, doctype, src):
	snap = {"total": flt(doc.get("paid_amount") if doctype == PE else doc.get("grand_total"))}
	if "outstanding_amount" in doc and doctype != PE:
		snap["outstanding"] = flt(doc.get("outstanding_amount"))
	snap["gl_debit"] = src.gl_debit(doctype, doc["name"])
	if doctype in STOCK_ALWAYS or (doctype in STOCK_IF_UPDATE and cint(doc.get("update_stock"))):
		snap["stock"] = src.stock_by_item(doctype, doc["name"])
	return snap


@job("Scan")
def scan_job():
	setup = frappe.get_single(SETUP)
	if frappe.db.count(LEDGER, {"status": "Done"}):
		frappe.throw(_("Transfer already started; rescan is not allowed."))

	src = make_source(setup)
	s_info = src.company_info()
	t_info = frappe.db.get_value(
		"Company", setup.target_company, ["name", "abbr", "default_currency"], as_dict=True
	)
	global_blockers = []
	if not s_info or not s_info.get("name"):
		frappe.throw(_("Source company not found"))
	if s_info.default_currency != t_info.default_currency:
		global_blockers.append(
			_("Currency mismatch: source {0}, target {1}").format(s_info.default_currency, t_info.default_currency)
		)

	prefixes = prefixes_of(setup)
	skip = make_skip(prefixes)
	doctypes = enabled_doctypes(setup)

	# 1. list
	items = []
	for dt in doctypes:
		names = src.list_names(dt, TRANSFER_DOCTYPES[dt][2], setup.from_date, setup.to_date)
		items.extend((dt, n) for n in names)
		heartbeat(_("Scan: listed {0} {1}").format(len(names), dt))
	if not items:
		frappe.throw(_("No submitted documents found in the source for this company and date range"))

	# 2. fetch (parallel for remote sites)
	docs, snaps, doc_blockers = {}, {}, {}
	for i, ((dt, name), (raw, snap)) in enumerate(_fetch_all(src, items), 1):
		k = doc_key(dt, name)
		d = prepare(raw, dt)
		_enrich_bundles(d, dt, src, k, doc_blockers)
		docs[k], snaps[k] = d, snap
		if i % 25 == 0 or i == len(items):
			heartbeat(_("Scan: fetched {0}/{1} documents").format(i, len(items)), done=i, total=len(items))

	# 2. analyse
	keys = set(docs)
	deps = {k: set() for k in docs}
	broken = {k: [] for k in docs}
	needs = {}
	for k, d in docs.items():
		dt = k.split("::", 1)[0]
		caddr = COMPANY_ADDRESS_FIELDS.get(dt, {})
		for ref in iter_refs(d, dt, skip):
			if ref.table is None and ref.fieldname in caddr:
				needs[(ADDR_MAP, ref.value)] = needs.get((ADDR_MAP, ref.value), 0) + 1
				continue
			kind = classify(ref.link_doctype, ref.fieldname)
			if kind == K_DOC:
				rk = doc_key(ref.link_doctype, ref.value)
				if rk == k:
					continue
				if rk in keys:
					deps[k].add(rk)
				else:
					broken[k].append(rk)
			elif kind == K_CLEAR and is_pe_reference(dt, ref):
				broken[k].append(doc_key(ref.link_doctype, ref.value))
			elif kind == K_SCOPED or (kind == K_GLOBAL and src.is_remote and ref.link_doctype not in KEEP_AS_IS):
				key = (ref.link_doctype, ref.value)
				needs[key] = needs.get(key, 0) + 1
		if d.get("naming_series"):
			key = (SERIES_PREFIX + dt, d["naming_series"])
			needs[key] = needs.get(key, 0) + 1

	# 3. exclusions and order
	nodes = list(docs)
	blocked = set(doc_blockers)
	if setup.broken_chain_policy == "Skip Document":
		excluded = propagate_exclusion(nodes, deps, blocked | {k for k in nodes if broken[k]})
	else:
		excluded = set(blocked)  # links to blocked documents are cleared at build time
	remaining = [n for n in nodes if n not in excluded]

	def sortkey(n):
		dt = n.split("::", 1)[0]
		d = docs[n]
		return (str(d.get(TRANSFER_DOCTYPES[dt][2]) or ""), TRANSFER_DOCTYPES[dt][1], str(d.get("creation") or ""), n)

	order, cyclic = topo_sort(remaining, deps, sortkey)

	# 4. mappings
	ctx = mapping.MapContext(src, s_info.name, setup.target_company, s_info.abbr, t_info.abbr)
	mapping.sync(needs, ctx)

	# 5. ledger
	frappe.db.delete(LEDGER)
	seq = 0
	order_set = set(order)
	for i, k in enumerate(order, 1):
		dt, name = k.split("::", 1)
		seq += 1
		_ledger(seq, dt, name, "Pending", docs[k], sorted(deps[k] & order_set), snaps[k],
			"; ".join(f"cleared link to {b}" for b in broken[k][:10]))
	for k in nodes:
		if k in order:
			continue
		dt, name = k.split("::", 1)
		if k in blocked:
			status, msg = "Blocked", "; ".join(doc_blockers[k])
		elif k in cyclic:
			status, msg = "Blocked", _("circular dependency")
		elif broken[k]:
			status, msg = "Skipped", _("broken chain: {0}").format(", ".join(broken[k][:10]))
		else:
			status, msg = "Skipped", _("depends on a blocked or skipped document")
		seq += 1
		_ledger(seq, dt, name, status, docs[k], sorted(deps[k]), {}, msg)

	# 6. summary
	counts = {}
	for k in nodes:
		dt = k.split("::", 1)[0]
		c = counts.setdefault(dt, {"found": 0, "pending": 0, "excluded": 0})
		c["found"] += 1
		c["pending" if k in order else "excluded"] += 1
	summary = {
		"source": s_info.name,
		"target": setup.target_company,
		"mode": setup.source_mode,
		"counts": counts,
		"broken_links": sum(1 for k in order if broken[k]),
		"unmapped": mapping.unmapped_count(),
		"global_blockers": global_blockers,
		"blocked": sorted(blocked | set(cyclic))[:50],
	}
	frappe.db.commit()
	set_state(phase="Scanned", progress=_("Scan complete: {0} documents queued").format(len(order)),
		summary_json=json.dumps(summary))


def _ledger(seq, dt, name, status, src_doc, deps, snapshot, message):
	frappe.get_doc(
		doctype=LEDGER, seq=seq, source_doctype=dt, source_name=name, status=status,
		src_doc=frappe.as_json(src_doc), deps=json.dumps(deps), snapshot=json.dumps(snapshot),
		message=(message or "")[:1000],
	).insert(ignore_permissions=True)

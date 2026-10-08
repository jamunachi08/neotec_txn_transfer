"""Builds a target-company document dict from a source document snapshot."""

import copy

import frappe
from frappe.model import no_value_fields, table_fields
from frappe.utils import flt

from .constants import (
	ADDR_MAP, COMPANY_ADDRESS_FIELDS, K_CLEAR, K_COMPANY, K_DOC, K_GLOBAL, K_SCOPED,
	KEEP_AS_IS, KNOWN_ROW_REF, PE, SERIES_PREFIX, STRIP_CHILD, STRIP_CHILD_BY_TABLE,
	STRIP_COMMON, STRIP_PARENT, ZERO_CHILD, doc_key,
)
from .mapping import resolve
from .walker import classify, iter_refs, prepare


class BuildContext:
	def __init__(self, maps, docmap, rowmap, cross_site, target_company, skip, prefixes, target):
		self.maps = maps
		self.docmap = docmap  # source key -> target name
		self.rowmap = rowmap  # source row name -> target row name
		self.cross_site = cross_site  # source and target are different sites
		self.target = target
		self.target_company = target_company
		self.skip = skip
		self.prefixes = tuple(p for p in prefixes if p)


def build(src_doc, doctype, ctx):
	d = prepare(copy.deepcopy(src_doc), doctype)
	notes = []
	meta = frappe.get_meta(doctype)
	caddr = COMPANY_ADDRESS_FIELDS.get(doctype, {})

	for ref in list(iter_refs(d, doctype, ctx.skip)):
		row, f, ld, val = ref.row, ref.fieldname, ref.link_doctype, ref.value
		if ref.table is None and f in caddr:
			new = resolve(ctx.maps, ADDR_MAP, val)
			row[f] = new
			row[caddr[f]] = ctx.target.address_display(new)
			continue
		kind = classify(ld, f)
		if kind == K_COMPANY:
			row[f] = ctx.target_company
		elif kind == K_DOC:
			new = ctx.docmap.get(doc_key(ld, val))
			if not new:
				notes.append(f"cleared {f}: {ld} {val} not migrated")
			row[f] = new
		elif kind == K_SCOPED:
			row[f] = resolve(ctx.maps, ld, val)
		elif kind == K_GLOBAL:
			if ctx.cross_site and ld not in KEEP_AS_IS:
				row[f] = resolve(ctx.maps, ld, val)
		elif kind == K_CLEAR:
			row[f] = None

	if doctype == PE:
		refs = d.get("references") or []
		kept = [r for r in refs if r.get("reference_name")]
		if len(kept) != len(refs):
			notes.append(f"dropped {len(refs) - len(kept)} payment reference row(s) to documents not migrated")
		d["references"] = kept

	# child-row references (so_detail, dn_detail, ...)
	for tf in meta.get_table_fields():
		cmeta = frappe.get_meta(tf.options)
		data_fields = [df.fieldname for df in cmeta.fields if df.fieldtype == "Data"]
		for row in d.get(tf.fieldname) or []:
			for f in data_fields:
				v = row.get(f)
				if not v or not (f in KNOWN_ROW_REF or f.endswith("_detail")):
					continue
				if v in ctx.rowmap:
					row[f] = ctx.rowmap[v]
				elif f in KNOWN_ROW_REF:
					row[f] = None

	for row in d.get("payment_schedule") or []:
		row["paid_amount"] = row["base_paid_amount"] = row["discounted_amount"] = 0
		row["outstanding"] = flt(row.get("payment_amount"))
		row["base_outstanding"] = flt(row.get("base_payment_amount"))

	out = _only_target_fields(_clean(d, meta, STRIP_PARENT, ctx.prefixes), doctype, ctx)
	row_sources = {}
	for tf in meta.get_table_fields():
		cmeta = frappe.get_meta(tf.options)
		strip = STRIP_CHILD | STRIP_CHILD_BY_TABLE.get((doctype, tf.fieldname), set())
		rows, srcs = [], []
		for row in d.get(tf.fieldname) or []:
			srcs.append(row.get("name"))
			rows.append(_only_target_fields(_clean_child(row, cmeta, strip, ctx.prefixes), tf.options, ctx))
		out[tf.fieldname] = rows
		row_sources[tf.fieldname] = srcs

	allowed = ctx.target.fields(doctype)
	if allowed is not None:
		for table in [t for t in row_sources if t not in allowed]:
			out.pop(table, None)
			row_sources.pop(table)

	out["doctype"] = doctype
	out["company"] = ctx.target_company
	out["docstatus"] = 0
	if meta.has_field("set_posting_time"):
		out["set_posting_time"] = 1
	if meta.has_field("ignore_pricing_rule"):
		out["ignore_pricing_rule"] = 1
	if out.get("naming_series"):
		out["naming_series"] = resolve(ctx.maps, SERIES_PREFIX + doctype, out["naming_series"]) or out["naming_series"]
	return out, row_sources, notes


def _only_target_fields(row, doctype, ctx):
	allowed = ctx.target.fields(doctype)
	if allowed is None:
		return row
	return {k: v for k, v in row.items() if k in allowed}


def _clean(row, meta, extra_strip, prefixes):
	out = {}
	for df in meta.fields:
		f = df.fieldname
		if df.fieldtype in table_fields or df.fieldtype in no_value_fields:
			continue
		if f in STRIP_COMMON or f in extra_strip:
			continue
		if prefixes and f.startswith(prefixes):
			continue
		if f in row:
			out[f] = row[f]
	return out


def _clean_child(row, cmeta, strip, prefixes):
	out = _clean(row, cmeta, strip, prefixes)
	for f in ZERO_CHILD:
		if f in out:
			out[f] = 0
	sbb = row.get("__sbb")
	if sbb:
		if sbb.get("serials"):
			out["serial_no"] = "\n".join(sbb["serials"])
		batches = sbb.get("batches") or {}
		if len(batches) == 1:
			out["batch_no"] = next(iter(batches))
		if cmeta.has_field("use_serial_batch_fields"):
			out["use_serial_batch_fields"] = 1
	rsbb = row.get("__rsbb")
	if rsbb and rsbb.get("serials"):
		out["rejected_serial_no"] = "\n".join(rsbb["serials"])
	return out

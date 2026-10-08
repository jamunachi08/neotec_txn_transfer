"""Metadata-driven traversal and classification of every link in a document."""

import frappe

from .constants import (
	K_CLEAR, K_COMPANY, K_DOC, K_GLOBAL, K_SCOPED, PE, SI, PI,
	STRIP_CHILD, STRIP_COMMON, STRIP_PARENT, TRANSFER_DOCTYPES,
)

_DT_INFO = {}


class Ref:
	__slots__ = ("row", "fieldname", "link_doctype", "value", "table", "dynamic")

	def __init__(self, row, fieldname, link_doctype, value, table, dynamic):
		self.row, self.fieldname, self.link_doctype = row, fieldname, link_doctype
		self.value, self.table, self.dynamic = value, table, dynamic


def dt_info(doctype):
	"""(exists, company_scoped, submittable)"""
	if doctype not in _DT_INFO:
		if not frappe.db.exists("DocType", doctype):
			_DT_INFO[doctype] = (False, False, False)
		else:
			m = frappe.get_meta(doctype)
			scoped = bool(not m.istable and not m.issingle and m.has_field("company"))
			_DT_INFO[doctype] = (True, scoped, bool(m.is_submittable))
	return _DT_INFO[doctype]


def is_scoped(doctype):
	return dt_info(doctype)[1]


def classify(link_doctype, fieldname):
	if fieldname == "amended_from":
		return K_CLEAR
	if link_doctype == "Company":
		return K_COMPANY if fieldname == "company" else K_GLOBAL
	if link_doctype in TRANSFER_DOCTYPES:
		return K_DOC
	exists, scoped, submittable = dt_info(link_doctype)
	if not exists:
		return K_CLEAR
	if scoped and submittable:
		return K_CLEAR  # transaction outside the transfer set (Quotation, Material Request, JE...)
	if scoped:
		return K_SCOPED
	return K_GLOBAL


def make_skip(prefixes):
	prefixes = tuple(p for p in prefixes if p)

	def skip(fieldname, is_child):
		if fieldname in STRIP_COMMON:
			return True
		if (STRIP_CHILD if is_child else STRIP_PARENT).__contains__(fieldname):
			return True
		return bool(prefixes) and fieldname.startswith(prefixes)

	return skip


def prepare(doc, doctype):
	"""In-place normalisation shared by scan and build."""
	if doctype in (SI, PI):
		doc["advances"] = []  # rebuilt from the Payment Entry side; avoids SI<->PE cycles
		if "allocate_advances_automatically" in doc:
			doc["allocate_advances_automatically"] = 0
	return doc


def iter_refs(doc, doctype, skip):
	meta = frappe.get_meta(doctype)
	yield from _row(doc, meta, None, skip)
	for tf in meta.get_table_fields():
		cmeta = frappe.get_meta(tf.options)
		for row in doc.get(tf.fieldname) or []:
			yield from _row(row, cmeta, tf.fieldname, skip)


def _row(row, meta, table, skip):
	is_child = table is not None
	for df in meta.fields:
		if df.fieldtype == "Link":
			ld = df.options
		elif df.fieldtype == "Dynamic Link":
			ld = row.get(df.options)
		else:
			continue
		val = row.get(df.fieldname)
		if not val or not ld or skip(df.fieldname, is_child):
			continue
		yield Ref(row, df.fieldname, ld, val, table, df.fieldtype == "Dynamic Link")


def is_pe_reference(doctype, ref):
	return doctype == PE and ref.table == "references" and ref.fieldname == "reference_name"

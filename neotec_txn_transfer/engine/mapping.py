"""Source -> target value mapping (Transfer Map)."""

import frappe
from frappe import _

from .constants import ADDR_MAP, CORE_MAP_TYPES, MAP, SERIES_PREFIX
from .walker import is_scoped


class MapError(Exception):
	pass


def load_maps():
	rows = frappe.get_all(
		MAP, fields=["name", "map_doctype", "source_value", "target_value", "action", "status"], limit_page_length=0
	)
	return {(r.map_doctype, r.source_value): r for r in rows}


def resolve(maps, map_doctype, value):
	r = maps.get((map_doctype, value))
	if not r:
		raise MapError(_("No mapping row for {0} '{1}'. Re-run Scan.").format(map_doctype, value))
	if r.action == "Clear":
		return None
	if not r.target_value:
		raise MapError(_("{0} '{1}' is unmapped").format(map_doctype, value))
	return r.target_value


class MapContext:
	def __init__(self, source, target, source_company, target_company, src_abbr, tgt_abbr):
		self.source = source
		self.target = target
		self.source_company = source_company
		self.target_company = target_company
		self.src_abbr = src_abbr
		self.tgt_abbr = tgt_abbr
		self.target_address = target.company_address(target_company)

	def swapped(self, value):
		suffix = f" - {self.src_abbr}"
		if self.src_abbr and value.endswith(suffix):
			return value[: -len(suffix)] + f" - {self.tgt_abbr}"
		return None


def target_valid(map_doctype, value, target, target_company):
	if map_doctype.startswith(SERIES_PREFIX):
		return True
	dt = "Address" if map_doctype == ADDR_MAP else map_doctype
	if not target.exists(dt, value):
		return False
	if map_doctype != ADDR_MAP and is_scoped(dt):
		owner = target.get_value(dt, value, "company")
		return not owner or owner == target_company
	return True


def suggest(map_doctype, value, ctx):
	if map_doctype.startswith(SERIES_PREFIX):
		return value
	if map_doctype == ADDR_MAP:
		return ctx.target_address
	tgt = ctx.target
	if is_scoped(map_doctype):
		owner = ctx.source.get_value(map_doctype, value, "company")
		if owner != ctx.source_company:
			# record not owned by the source company (e.g. a party bank account)
			return value if tgt.exists(map_doctype, value) else None
		for c in filter(None, (ctx.swapped(value), value)):
			if tgt.exists(map_doctype, c) and tgt.get_value(map_doctype, c, "company") == ctx.target_company:
				return c
		return None
	return value if tgt.exists(map_doctype, value) else None


def _prefetch(needs, ctx):
	"""One batched lookup per doctype instead of one request per value (push mode)."""
	by_dt = {}
	for mdt, val in needs:
		if mdt.startswith(SERIES_PREFIX) or mdt == ADDR_MAP:
			continue
		vals = by_dt.setdefault(mdt, set())
		vals.add(val)
		if is_scoped(mdt) and ctx.swapped(val):
			vals.add(ctx.swapped(val))
	for mdt, vals in by_dt.items():
		ctx.target.prefetch(mdt, list(vals), with_company=is_scoped(mdt))


def sync(needs, ctx):
	"""needs: {(map_doctype, source_value): uses}. Manual rows are never overwritten."""
	existing = load_maps()
	_prefetch(needs, ctx)
	for key, uses in needs.items():
		mdt, val = key
		r = existing.get(key)
		if r:
			upd = {"uses": uses}
			if r.status in ("Auto", "Unmapped") and r.action == "Map":
				t = suggest(mdt, val, ctx)
				upd.update(target_value=t, status="Auto" if t else "Unmapped")
			frappe.db.set_value(MAP, r.name, upd, update_modified=False)
		else:
			t = suggest(mdt, val, ctx)
			doc = frappe.get_doc(
				doctype=MAP, map_doctype=mdt, source_value=val, target_value=t,
				action="Map", status="Auto" if t else "Unmapped", uses=uses,
			)
			doc.flags.auto = True
			doc.insert(ignore_permissions=True)
	for key, r in existing.items():
		if key in needs:
			continue
		if r.status == "Manual":
			frappe.db.set_value(MAP, r.name, "uses", 0, update_modified=False)
		else:
			frappe.db.delete(MAP, {"name": r.name})


def unmapped_count():
	return frappe.db.sql(
		f"""select count(*) from `tab{MAP}`
		where action='Map' and ifnull(target_value,'')='' and uses > 0"""
	)[0][0]


def clear_unmapped_non_core():
	core = tuple(CORE_MAP_TYPES)
	frappe.db.sql(
		f"""update `tab{MAP}` set action='Clear', status='Manual'
		where action='Map' and ifnull(target_value,'')='' and map_doctype not in %(core)s
		and map_doctype not like %(series)s""",
		{"core": core, "series": SERIES_PREFIX + "%"},
	)

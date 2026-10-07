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


def target_company_address(company):
	r = frappe.db.sql(
		"""select a.name from `tabAddress` a
		join `tabDynamic Link` dl on dl.parent = a.name and dl.parenttype = 'Address'
		where dl.link_doctype = 'Company' and dl.link_name = %s and a.disabled = 0
		order by a.is_primary_address desc, a.is_your_company_address desc, a.creation asc limit 1""",
		company,
	)
	return r[0][0] if r else None


class MapContext:
	def __init__(self, source, source_company, target_company, src_abbr, tgt_abbr):
		self.source = source
		self.source_company = source_company
		self.target_company = target_company
		self.src_abbr = src_abbr
		self.tgt_abbr = tgt_abbr
		self.target_address = target_company_address(target_company)


def target_valid(map_doctype, value, target_company):
	if map_doctype.startswith(SERIES_PREFIX):
		return True
	dt = "Address" if map_doctype == ADDR_MAP else map_doctype
	if not frappe.db.exists(dt, value):
		return False
	if map_doctype != ADDR_MAP and is_scoped(dt):
		owner = frappe.db.get_value(dt, value, "company")
		return not owner or owner == target_company
	return True


def suggest(map_doctype, value, ctx):
	if map_doctype.startswith(SERIES_PREFIX):
		return value
	if map_doctype == ADDR_MAP:
		return ctx.target_address
	if is_scoped(map_doctype):
		owner = ctx.source.get_value(map_doctype, value, "company")
		if owner != ctx.source_company:
			# record not owned by the source company (e.g. a party bank account)
			return value if frappe.db.exists(map_doctype, value) else None
		candidates = []
		suffix = f" - {ctx.src_abbr}"
		if ctx.src_abbr and value.endswith(suffix):
			candidates.append(value[: -len(suffix)] + f" - {ctx.tgt_abbr}")
		candidates.append(value)
		for c in candidates:
			if frappe.db.exists(map_doctype, c) and frappe.db.get_value(map_doctype, c, "company") == ctx.target_company:
				return c
		return None
	return value if frappe.db.exists(map_doctype, value) else None


def sync(needs, ctx):
	"""needs: {(map_doctype, source_value): uses}. Manual rows are never overwritten."""
	existing = load_maps()
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

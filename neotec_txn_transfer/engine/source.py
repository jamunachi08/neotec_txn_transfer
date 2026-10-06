"""Source adapters: same-site company or a remote Frappe site over REST."""

import json
from urllib.parse import quote

import frappe
import requests
from frappe import _
from frappe.utils import flt


class LocalSource:
	is_remote = False

	def __init__(self, company):
		self.company = company
		self._cache = {}

	def company_info(self):
		d = frappe.db.get_value("Company", self.company, ["name", "abbr", "default_currency"], as_dict=True)
		if not d:
			frappe.throw(_("Source company {0} not found").format(self.company))
		return d

	def list_names(self, doctype, date_field, from_date, to_date):
		return frappe.get_all(
			doctype,
			filters=[
				["company", "=", self.company],
				["docstatus", "=", 1],
				[date_field, "between", [from_date, to_date]],
			],
			pluck="name",
			order_by=f"{date_field} asc, creation asc",
		)

	def get_doc(self, doctype, name):
		return json.loads(frappe.as_json(frappe.get_doc(doctype, name).as_dict()))

	def get_value(self, doctype, name, field):
		key = (doctype, name, field)
		if key not in self._cache:
			self._cache[key] = frappe.db.get_value(doctype, name, field)
		return self._cache[key]

	def bundle_entries(self, bundle):
		return frappe.get_all(
			"Serial and Batch Entry",
			filters={"parent": bundle},
			fields=["serial_no", "batch_no", "qty"],
			order_by="idx asc",
		)

	def gl_debit(self, doctype, name):
		r = frappe.db.sql(
			"""select coalesce(sum(debit), 0) from `tabGL Entry`
			where voucher_type=%s and voucher_no=%s and is_cancelled=0""",
			(doctype, name),
		)
		return flt(r[0][0])

	def stock_by_item(self, doctype, name):
		rows = frappe.db.sql(
			"""select item_code, sum(actual_qty) from `tabStock Ledger Entry`
			where voucher_type=%s and voucher_no=%s and is_cancelled=0 group by item_code""",
			(doctype, name),
		)
		return {r[0]: flt(r[1]) for r in rows}


class RemoteSource:
	is_remote = True
	PAGE = 500

	def __init__(self, url, key, secret, company):
		self.base = (url or "").rstrip("/")
		self.company = company
		self._cache = {}
		self.s = requests.Session()
		self.s.headers.update({"Authorization": f"token {key}:{secret}", "Accept": "application/json"})

	def _get(self, path, params=None):
		try:
			r = self.s.get(self.base + path, params=params, timeout=120)
		except requests.RequestException as e:
			frappe.throw(_("Cannot reach source site: {0}").format(e))
		if r.status_code >= 400:
			frappe.throw(_("Source site returned {0} for {1}: {2}").format(r.status_code, path, r.text[:300]))
		return r.json()

	def _list(self, doctype, fields, filters, order_by=None):
		out, start = [], 0
		while True:
			params = {
				"fields": json.dumps(fields),
				"filters": json.dumps(filters),
				"limit_start": start,
				"limit_page_length": self.PAGE,
			}
			if order_by:
				params["order_by"] = order_by
			data = self._get(f"/api/resource/{quote(doctype)}", params).get("data") or []
			out.extend(data)
			if len(data) < self.PAGE:
				return out
			start += self.PAGE

	def company_info(self):
		d = self._get(f"/api/resource/Company/{quote(self.company, safe='')}").get("data") or {}
		return frappe._dict(name=d.get("name"), abbr=d.get("abbr"), default_currency=d.get("default_currency"))

	def list_names(self, doctype, date_field, from_date, to_date):
		rows = self._list(
			doctype,
			["name"],
			[["company", "=", self.company], ["docstatus", "=", 1], [date_field, "between", [str(from_date), str(to_date)]]],
			order_by=f"{date_field} asc, creation asc",
		)
		return [r["name"] for r in rows]

	def get_doc(self, doctype, name):
		return self._get(f"/api/resource/{quote(doctype)}/{quote(name, safe='')}").get("data") or {}

	def get_value(self, doctype, name, field):
		key = (doctype, name, field)
		if key not in self._cache:
			rows = self._list(doctype, [field], [["name", "=", name]])
			self._cache[key] = rows[0].get(field) if rows else None
		return self._cache[key]

	def bundle_entries(self, bundle):
		return self.get_doc("Serial and Batch Bundle", bundle).get("entries") or []

	def gl_debit(self, doctype, name):
		rows = self._list(
			"GL Entry", ["debit"],
			[["voucher_type", "=", doctype], ["voucher_no", "=", name], ["is_cancelled", "=", 0]],
		)
		return sum(flt(r.get("debit")) for r in rows)

	def stock_by_item(self, doctype, name):
		rows = self._list(
			"Stock Ledger Entry", ["item_code", "actual_qty"],
			[["voucher_type", "=", doctype], ["voucher_no", "=", name], ["is_cancelled", "=", 0]],
		)
		out = {}
		for r in rows:
			out[r["item_code"]] = out.get(r["item_code"], 0) + flt(r.get("actual_qty"))
		return out


def make_source(setup):
	if setup.source_mode == "Remote Site":
		return RemoteSource(
			setup.remote_url,
			setup.api_key,
			setup.get_password("api_secret", raise_exception=False),
			setup.source_company,
		)
	return LocalSource(setup.source_company)

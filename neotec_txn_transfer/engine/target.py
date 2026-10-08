"""Target adapters: this site (insert + submit in-process) or a remote site over REST (push mode)."""

import json
from urllib.parse import quote

import frappe
import requests
from frappe import _

from .source import LocalSource, RemoteError, RemoteSite, UncertainError, error_text


class LocalTarget(LocalSource):
	def company_info(self):
		return frappe.db.get_value("Company", self.company, ["name", "abbr", "default_currency"], as_dict=True)

	def exists(self, doctype, name):
		return bool(frappe.db.exists(doctype, name))

	def prefetch(self, doctype, values, with_company=False):
		pass

	def missing(self, needs):
		return {(dt, v) for dt, vals in needs.items() for v in vals if not frappe.db.exists(dt, v)}

	def company_address(self, company):
		r = frappe.db.sql(
			"""select a.name from `tabAddress` a
			join `tabDynamic Link` dl on dl.parent = a.name and dl.parenttype = 'Address'
			where dl.link_doctype = 'Company' and dl.link_name = %s and a.disabled = 0
			order by a.is_primary_address desc, a.is_your_company_address desc, a.creation asc limit 1""",
			company,
		)
		return r[0][0] if r else None

	def address_display(self, name):
		if not name:
			return None
		from frappe.contacts.doctype.address.address import get_address_display

		return get_address_display(name)

	def fields(self, doctype):
		return None  # same site: builder already uses this site's metadata

	def create(self, doc_dict, set_name=None):
		doc = frappe.get_doc(doc_dict)
		doc.flags.ignore_permissions = True
		if set_name:
			doc.insert(set_name=set_name)
		else:
			doc.insert()
		doc.submit()
		rows = {tf.fieldname: [r.name for r in (doc.get(tf.fieldname) or [])] for tf in doc.meta.get_table_fields()}
		return doc.name, rows


class RemoteTarget(RemoteSite):
	label = "target site"

	def __init__(self, *a, **kw):
		super().__init__(*a, **kw)
		self._exists = {}
		self._fields = {}
		self._addr = {}

	# ---- lookups (cached, batched) -------------------------------------------
	def prefetch(self, doctype, values, with_company=False):
		values = [v for v in set(values) if v and (doctype, v) not in self._exists]
		fields = ["name", "company"] if with_company else ["name"]
		for i in range(0, len(values), 100):
			chunk = values[i : i + 100]
			found = {r["name"]: r for r in self._list(doctype, fields, [["name", "in", chunk]])}
			for v in chunk:
				self._exists[(doctype, v)] = v in found
				if with_company:
					self._cache[(doctype, v, "company")] = (found.get(v) or {}).get("company")

	def exists(self, doctype, name):
		if (doctype, name) not in self._exists:
			self.prefetch(doctype, [name])
		return self._exists[(doctype, name)]

	def missing(self, needs):
		out = set()
		for dt, vals in needs.items():
			self.prefetch(dt, vals)
			out |= {(dt, v) for v in vals if not self._exists.get((dt, v))}
		return out

	def company_address(self, company):
		rows = self._list(
			"Address", ["name"],
			[["Dynamic Link", "link_doctype", "=", "Company"], ["Dynamic Link", "link_name", "=", company],
				["disabled", "=", 0]],
			order_by="is_primary_address desc, creation asc",
		)
		return rows[0]["name"] if rows else None

	def address_display(self, name):
		if not name:
			return None
		if name not in self._addr:
			r = self._get("/api/method/frappe.contacts.doctype.address.address.get_address_display",
				{"address_dict": name})
			self._addr[name] = r.get("message")
		return self._addr[name]

	def fields(self, doctype):
		"""Fieldnames that exist on the target, so custom fields of this site are not sent."""
		if doctype not in self._fields:
			r = self._get("/api/method/frappe.desk.form.load.getdoctype", {"doctype": doctype})
			for d in r.get("docs") or []:
				if d.get("doctype") == "DocType":
					self._fields[d["name"]] = {f["fieldname"] for f in d.get("fields") or []}
			self._fields.setdefault(doctype, set())
		return self._fields[doctype]

	# ---- create ----------------------------------------------------------------
	def create(self, doc_dict, set_name=None):
		"""Insert with docstatus 1: the target validates and submits in one request (one transaction)."""
		payload = dict(doc_dict, docstatus=1)
		path = f"/api/resource/{quote(doc_dict['doctype'])}"
		try:
			r = self.s.post(self.base + path, data=json.dumps(payload, default=str),
				headers={"Content-Type": "application/json"}, timeout=600)
		except (requests.Timeout, requests.ConnectionError) as e:
			raise UncertainError(_("No answer from the target after sending: {0}").format(e))
		except requests.RequestException as e:
			raise RemoteError(_("Could not send to target: {0}").format(e))
		if r.status_code >= 400:
			raise RemoteError(error_text(r))
		data = (r.json() or {}).get("data") or {}
		if not data.get("name"):
			raise UncertainError(_("Target answered without a document name"))
		rows = {k: [row.get("name") for row in v] for k, v in data.items()
			if isinstance(v, list) and v and isinstance(v[0], dict) and "name" in v[0]}
		return data["name"], rows


def make_target(setup):
	if setup.source_mode == "Push to Remote Target":
		return RemoteTarget(
			setup.target_url,
			setup.target_api_key,
			setup.get_password("target_api_secret", raise_exception=False),
			setup.target_company,
		)
	return LocalTarget(setup.target_company)


def is_cross_site(setup):
	return setup.source_mode != "Same Site"

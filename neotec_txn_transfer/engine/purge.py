"""Removes every trace of this app from the site. Called by Finalize and by before_uninstall."""

import frappe

from .constants import APP, APP_DOCTYPES, LEDGER, MAP, SETUP

# (doctype, field holding a doctype name)
_REF_TABLES = (
	("Version", "ref_doctype"), ("Comment", "reference_doctype"), ("Activity Log", "reference_doctype"),
	("Error Log", "reference_doctype"), ("Notification Log", "document_type"), ("ToDo", "reference_type"),
	("DocShare", "share_doctype"), ("Document Follow", "ref_doctype"), ("Communication", "reference_doctype"),
	("Email Queue", "reference_doctype"), ("Energy Point Log", "reference_doctype"),
	("Tag Link", "document_type"), ("View Log", "reference_doctype"), ("User Permission", "allow"),
	("Custom Field", "dt"), ("Property Setter", "doc_type"), ("Client Script", "dt"),
	("Custom DocPerm", "parent"), ("List View Settings", "name"), ("Deleted Document", "deleted_doctype"),
	("Deleted Document", "deleted_name"), ("Data Import", "reference_doctype"),
	("Server Script", "reference_doctype"), ("Prepared Report", "ref_report_doctype"),
)


def _has(dt, col=None):
	if not frappe.db.table_exists(dt):
		return False
	return col is None or frappe.db.has_column(dt, col)


def purge():
	names = list(APP_DOCTYPES)
	like = f"%{APP}%"

	for dt in (LEDGER, MAP):
		if _has(dt):
			frappe.db.delete(dt)
	frappe.db.delete("Singles", {"doctype": SETUP})
	frappe.db.sql("delete from `__Auth` where doctype in %(n)s", {"n": names})
	if "__UserSettings" in frappe.db.get_tables():
		frappe.db.sql("delete from `__UserSettings` where doctype in %(n)s", {"n": names})

	for dt, col in _REF_TABLES:
		if _has(dt, col):
			frappe.db.delete(dt, {col: ["in", names]})

	if _has("Error Log", "method"):
		frappe.db.sql("delete from `tabError Log` where method like %s or error like %s", (like, like))
	if _has("Scheduled Job Log", "scheduled_job_type"):
		frappe.db.sql("delete from `tabScheduled Job Log` where scheduled_job_type like %s", like)
	if _has("Route History", "route"):
		frappe.db.sql(
			"""delete from `tabRoute History` where route like %s or route like %s or route like %s""",
			("%transfer-setup%", "%transfer-map%", "%transfer-ledger%"),
		)
	if _has("File", "attached_to_doctype"):
		for f in frappe.get_all("File", filters={"attached_to_doctype": ["in", names]}, pluck="name"):
			frappe.delete_doc("File", f, ignore_permissions=True, force=True, delete_permanently=True)

	cache = frappe.cache() if callable(frappe.cache) else frappe.cache
	cache.delete_keys(APP)
	for dt in names:
		frappe.clear_cache(doctype=dt)
	frappe.db.commit()


def before_uninstall():
	purge()

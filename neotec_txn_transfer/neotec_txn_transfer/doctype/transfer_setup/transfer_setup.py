import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from neotec_txn_transfer.engine.constants import LEDGER, TRANSFER_DOCTYPES

LOCKED = ["source_mode", "source_company", "target_company", "remote_url", "target_url", "from_date", "to_date"] + [
	v[0] for v in TRANSFER_DOCTYPES.values()
]


class TransferSetup(Document):
	def validate(self):
		if self.from_date and self.to_date and getdate(self.from_date) > getdate(self.to_date):
			frappe.throw(_("From Date must be on or before To Date"))
		local_source = self.source_mode in ("Same Site", "Push to Remote Target")
		local_target = self.source_mode in ("Same Site", "Remote Site")
		if local_source and not frappe.db.exists("Company", self.source_company):
			frappe.throw(_("Source company {0} does not exist on this site").format(self.source_company))
		if local_target and not frappe.db.exists("Company", self.target_company):
			frappe.throw(_("Target company {0} does not exist on this site").format(self.target_company))
		if self.source_mode == "Same Site" and self.source_company == self.target_company:
			frappe.throw(_("Source and target company must differ"))
		if self.source_mode == "Remote Site" and not (self.remote_url and self.api_key and self.api_secret):
			frappe.throw(_("Pull mode needs the source site URL, API key and API secret"))
		if self.source_mode == "Push to Remote Target":
			if not (self.target_url and self.target_api_key and self.target_api_secret):
				frappe.throw(_("Push mode needs the target site URL, API key and API secret"))
			if (self.target_url or "").rstrip("/") == frappe.utils.get_url().rstrip("/"):
				frappe.throw(_("The target URL is this site. Use Same Site mode instead."))
		self._lock_after_run()

	def _lock_after_run(self):
		before = self.get_doc_before_save()
		if not before or not frappe.db.count(LEDGER, {"status": "Done"}):
			return
		changed = [f for f in LOCKED if str(before.get(f) or "") != str(self.get(f) or "")]
		if changed:
			frappe.throw(_("Transfer already started; these fields are locked: {0}").format(", ".join(changed)))

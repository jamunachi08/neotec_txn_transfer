import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import getdate

from neotec_txn_transfer.engine.constants import LEDGER, TRANSFER_DOCTYPES

LOCKED = ["source_mode", "source_company", "target_company", "remote_url", "from_date", "to_date"] + [
	v[0] for v in TRANSFER_DOCTYPES.values()
]


class TransferSetup(Document):
	def validate(self):
		if self.from_date and self.to_date and getdate(self.from_date) > getdate(self.to_date):
			frappe.throw(_("From Date must be on or before To Date"))
		if self.source_mode == "Same Site":
			if not frappe.db.exists("Company", self.source_company):
				frappe.throw(_("Source company {0} does not exist on this site").format(self.source_company))
			if self.source_company == self.target_company:
				frappe.throw(_("Source and target company must differ"))
		elif not (self.remote_url and self.api_key and self.api_secret):
			frappe.throw(_("Remote mode needs the source URL, API key and API secret"))
		self._lock_after_run()

	def _lock_after_run(self):
		before = self.get_doc_before_save()
		if not before or not frappe.db.count(LEDGER, {"status": "Done"}):
			return
		changed = [f for f in LOCKED if str(before.get(f) or "") != str(self.get(f) or "")]
		if changed:
			frappe.throw(_("Transfer already started; these fields are locked: {0}").format(", ".join(changed)))

import frappe
from frappe import _
from frappe.model.document import Document

from neotec_txn_transfer.engine.constants import SETUP
from neotec_txn_transfer.engine.mapping import target_valid


class TransferMap(Document):
	def validate(self):
		if self.flags.auto:
			return
		if self.action == "Map" and self.target_value:
			target = frappe.db.get_single_value(SETUP, "target_company")
			if not target_valid(self.map_doctype, self.target_value, target):
				frappe.throw(_("{0} '{1}' does not exist or does not belong to {2}").format(
					self.map_doctype, self.target_value, target))
		self.status = "Manual"

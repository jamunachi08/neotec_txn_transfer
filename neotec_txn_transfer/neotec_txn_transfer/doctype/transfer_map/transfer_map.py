import frappe
from frappe import _
from frappe.model.document import Document

from neotec_txn_transfer.engine.constants import SETUP
from neotec_txn_transfer.engine.mapping import target_valid
from neotec_txn_transfer.engine.target import make_target


class TransferMap(Document):
	def validate(self):
		if self.flags.auto:
			return
		if self.action == "Map" and self.target_value:
			setup = frappe.get_single(SETUP)
			target = setup.target_company
			if not target_valid(self.map_doctype, self.target_value, make_target(setup), target):
				frappe.throw(_("{0} '{1}' does not exist or does not belong to {2}").format(
					self.map_doctype, self.target_value, target))
		self.status = "Manual"

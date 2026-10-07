"""Static rules for the transfer engine."""

APP = "neotec_txn_transfer"
APP_DOCTYPES = ("Transfer Setup", "Transfer Map", "Transfer Ledger")
SETUP = "Transfer Setup"
MAP = "Transfer Map"
LEDGER = "Transfer Ledger"
REALTIME_EVENT = "ntt_progress"

SO, DN, SI = "Sales Order", "Delivery Note", "Sales Invoice"
PO, PR, PI = "Purchase Order", "Purchase Receipt", "Purchase Invoice"
PE = "Payment Entry"

# doctype -> (setup checkbox, stage rank, date field)
TRANSFER_DOCTYPES = {
	SO: ("include_sales_order", 0, "transaction_date"),
	PO: ("include_purchase_order", 0, "transaction_date"),
	DN: ("include_delivery_note", 1, "posting_date"),
	PR: ("include_purchase_receipt", 1, "posting_date"),
	SI: ("include_sales_invoice", 2, "posting_date"),
	PI: ("include_purchase_invoice", 2, "posting_date"),
	PE: ("include_payment_entry", 3, "posting_date"),
}

STOCK_ALWAYS = {DN, PR}
STOCK_IF_UPDATE = {SI, PI}

# Never copied
STRIP_COMMON = {
	"name", "owner", "creation", "modified", "modified_by", "docstatus", "idx",
	"amended_from", "_user_tags", "_comments", "_assign", "_liked_by", "_seen",
	"parent", "parentfield", "parenttype", "doctype",
}

# Header fields recomputed by ERPNext or meaningless in the target company
STRIP_PARENT = {
	"status", "per_billed", "per_delivered", "per_received", "per_returned", "per_picked",
	"per_installed", "billing_status", "delivery_status", "advance_paid", "outstanding_amount",
	"inter_company_invoice_reference", "inter_company_order_reference", "inter_company_reference",
	"auto_repeat", "repost_required", "unreconciled_amount", "total_advance",
	"against_income_account", "against_expense_account",
}

STRIP_CHILD = {"serial_and_batch_bundle", "rejected_serial_and_batch_bundle"}

STRIP_CHILD_BY_TABLE = {
	(PE, "references"): {"total_amount", "outstanding_amount", "exchange_rate"},
}

# Child progress counters reset to zero; downstream documents rebuild them
ZERO_CHILD = {
	"delivered_qty", "billed_amt", "received_qty", "returned_qty", "ordered_qty", "picked_qty",
	"work_order_qty", "produced_qty", "planned_qty", "installed_qty", "consumed_qty",
	"stock_reserved_qty", "received_stock_qty",
}

# Child Data fields that hold the name of a row in another document
KNOWN_ROW_REF = {
	"so_detail", "dn_detail", "si_detail", "po_detail", "pr_detail",
	"purchase_order_item", "sales_order_item", "sales_invoice_item", "purchase_invoice_item",
	"purchase_receipt_item", "delivery_note_item", "quotation_item", "material_request_item",
	"supplier_quotation_item", "pick_list_item", "pos_invoice_item", "blanket_order_item",
}

# Header address fields that belong to the company (not the party): field -> display field
_SALES_ADDR = {"company_address": "company_address_display", "dispatch_address_name": "dispatch_address"}
_BUY_ADDR = {"billing_address": "billing_address_display", "shipping_address": "shipping_address_display"}
COMPANY_ADDRESS_FIELDS = {
	SO: {"company_address": "company_address_display"},
	DN: _SALES_ADDR, SI: _SALES_ADDR,
	PO: _BUY_ADDR, PR: _BUY_ADDR, PI: _BUY_ADDR,
}

SERIES_PREFIX = "Naming Series::"
ADDR_MAP = "Company Address"
CORE_MAP_TYPES = {"Account", "Cost Center", "Warehouse", ADDR_MAP}

# Link targets kept verbatim even in remote mode
KEEP_AS_IS = {"DocType", "User", "Role", "Module Def", "Currency", "Country", "Language"}

DEFAULT_STRIP_PREFIXES = "custom_zatca\nzatca_\nksa_\ncustom_ksa"
DEFAULT_ZATCA_GUARD = (
	"link:Sales Invoice Additional Fields:sales_invoice\n"
	"field:custom_zatca_status\n"
	"field:custom_uuid"
)

AMOUNT_TOL = 0.05

# classification kinds
K_COMPANY, K_DOC, K_SCOPED, K_GLOBAL, K_CLEAR = "company", "doc", "scoped", "global", "clear"


def doc_key(doctype, name):
	return f"{doctype}::{name}"


def split_key(key):
	dt, name = key.split("::", 1)
	return dt, name

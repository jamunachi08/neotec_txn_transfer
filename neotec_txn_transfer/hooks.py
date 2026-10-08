# Zero-footprint by design. Keep this file minimal:
# no fixtures, no scheduler_events, no doc_events, no custom fields,
# no workspace, no app_include_* assets. verify_tree.py enforces this.

app_name = "neotec_txn_transfer"
app_title = "Neotec Txn Transfer"
app_publisher = "Neotec Integrated Solutions"
app_description = "One-time, zero-footprint transaction transfer between ERPNext companies"
app_email = "info@neotec.sa"
app_license = "Proprietary"

required_apps = ["erpnext"]

before_uninstall = "neotec_txn_transfer.engine.purge.before_uninstall"

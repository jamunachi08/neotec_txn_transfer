# Changelog

## 1.1.0 — 2026-10-08
- New source mode **Push to Remote Target**: install the app on the source site only and send the transactions to another site over its API. The target site needs no app.
- Each document is created and submitted on the target in a single request, so the target either has the whole submitted document or nothing.
- If the target does not answer after a document was sent, the run pauses and the ledger row is marked **Uncertain** instead of retrying (a retry could create a duplicate). The ledger row offers "It was created" / "It was not created" to resolve it.
- Push mode replaces the Dry Run with a **Pre-flight Check** that writes nothing to the target: every document is built, every mapping must resolve, and every linked master (customer, item, account, warehouse, tax template, address, ...) is confirmed to exist on the target.
- Fields and child tables that exist only on the source site are not sent to the target.
- Mapping suggestions on a remote target are looked up in batches of 100 instead of one request per value.
- Verify reads totals, outstanding, GL and stock from the target over the API in push mode.
- Reverse Source is now available whenever the source company is on this site (Same Site and Push).
- Target Company is now a text field, because in push mode it names a company on another site.

## 1.0.1 — 2026-10-07
- Fixed: a job killed by the worker (timeout, restart or deploy) left the form stuck on "A job is running" forever. The app now checks the background queue and clears a dead lock automatically when the form opens or a step is started.
- Progress is now saved on the form (with a "Last Progress At" time) during Scan, Run, Verify and Reverse, so it is visible after a page reload and from any browser.
- Remote scans fetch documents 8 at a time, with automatic retry on busy or unreachable source responses. Source snapshots are taken during the fetch instead of in a second pass.
- Scan stops early with a clear message when the source returns no documents for the company and date range.

## 1.0.0 — 2026-10-06
- First release: one-time transfer of Sales Order, Delivery Note, Sales Invoice, Purchase Order, Purchase Receipt, Purchase Invoice and Payment Entry (including returns) between companies.
- Same-site and remote-site sources; metadata-driven link remapping with abbreviation-based auto mapping.
- Dependency-ordered replay with document and child-row link remapping; resumable per-document commits.
- Dry run with forced rollback; verification of totals, outstanding, GL and stock per document.
- Optional source reversal (same site) with ZATCA guard.
- Finalize & Purge plus before_uninstall purge for a zero-footprint removal.

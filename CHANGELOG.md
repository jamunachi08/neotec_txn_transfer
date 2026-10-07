# Changelog

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

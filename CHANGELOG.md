# Changelog

## 1.0.0 — 2026-10-06
- First release: one-time transfer of Sales Order, Delivery Note, Sales Invoice, Purchase Order, Purchase Receipt, Purchase Invoice and Payment Entry (including returns) between companies.
- Same-site and remote-site sources; metadata-driven link remapping with abbreviation-based auto mapping.
- Dependency-ordered replay with document and child-row link remapping; resumable per-document commits.
- Dry run with forced rollback; verification of totals, outstanding, GL and stock per document.
- Optional source reversal (same site) with ZATCA guard.
- Finalize & Purge plus before_uninstall purge for a zero-footprint removal.

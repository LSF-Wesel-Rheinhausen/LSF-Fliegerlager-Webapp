# Fix uploaded receipt visibility

- Corrects media and static URL prefixes so generated file links are absolute from the site root.
- Routes expense receipt links through a permissioned download endpoint so production users can open uploaded invoices without exposing raw media URLs.
- Serves uploaded media files in local/debug deployments before the catch-all 404 route.
- Adds regression coverage for kiosk receipt uploads, editor access, anonymous denial, missing receipts, and cross-participant access denial.

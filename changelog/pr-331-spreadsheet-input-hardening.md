# Security hardening for spreadsheet exports and imports

- Neutralize formula-like text in all XLSX cost-center export cells, including participant-controlled descriptions.
- Reject meal-booking dates when a camp has missing or inverted date bounds instead of accepting request-provided future dates.
- Validate XLSX archive size, entry count, encryption, total decompression, and per-entry expansion before `openpyxl` materializes workbook content.
- Add regression coverage for formula cells, invalid camp bounds, normal XLSX previews, and oversized shared-string expansion.

Refs #263

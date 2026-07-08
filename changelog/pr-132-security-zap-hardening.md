## Security: CSV exports and baseline headers hardened

- Escaped formula-like text cells in CSV exports to prevent spreadsheet formula injection.
- Locked shared expense rows during approval to avoid duplicate allocations under concurrent requests.
- Added baseline browser security headers for application and static responses.

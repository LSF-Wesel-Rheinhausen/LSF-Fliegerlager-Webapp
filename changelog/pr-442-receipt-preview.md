# Receipt image previews

- Add accessible in-app previews for supported expense receipt images in admin and kiosk views.
- Preserve the existing PDF preview and secure fallback behavior for unsupported files.
- Hide receipt existence from unauthorized download requests while preserving editor and owner responses.
- Return a uniform not-found response for unauthorized expense receipt IDs.
- Allow authorized PDF receipt previews only in same-origin dialogs while retaining global framing protection elsewhere.

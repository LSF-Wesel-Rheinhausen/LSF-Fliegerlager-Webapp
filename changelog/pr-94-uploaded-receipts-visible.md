# Fix uploaded receipt visibility

- Corrects media and static URL prefixes so generated file links are absolute from the site root.
- Serves uploaded media files in local/debug deployments so uploaded invoice and receipt links can be opened directly.
- Adds regression coverage for kiosk receipt uploads and admin receipt links.

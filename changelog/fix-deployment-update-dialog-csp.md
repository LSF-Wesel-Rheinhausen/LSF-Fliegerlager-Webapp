# Update-Dialog CSP-kompatibel laden

- Update-Seite lädt das Dialog-JavaScript jetzt als statisches Asset statt als Inline-Script.
- Script-Tag deaktiviert Cloudflare Rocket Loader per `data-cfasync="false"`, damit die strikte CSP den Bestätigungsdialog nicht blockiert.
- Regressionstests decken sichtbaren Installationsdialog und erfolgreichen Install-POST ab.

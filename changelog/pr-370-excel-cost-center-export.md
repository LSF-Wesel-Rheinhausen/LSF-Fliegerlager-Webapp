# Excel-Kostenstellenexport (#370)

- Behebt den 500er beim Export von Kostenstellen-Details aus `get_cost_center_evaluation()`.
- Normalisiert MealSignup-Objekte sowie CAMP_FLAT-, Spenden- und Förderungs-Dictionaries in fachlich korrekte Workbook-Zeilen.
- Tests: fokussierte Export-/Kostenstellen-/Spreadsheet-Tests, vollständiges pytest, E2E, Ruff, Django check und mypy.
- Stack-Basis: PR #373 (`fix/372-family-child-camp-fees`).

from pathlib import Path


def test_app_css_contains_darkmode_code_contrast_styling():
    css_path = Path(__file__).resolve().parents[1] / "src/static/billing/app-v8.css"
    css = css_path.read_text(encoding="utf-8")

    assert "code {" in css
    dark_code_selector = ':root[data-theme="dark"] code {'
    assert dark_code_selector in css
    dark_code_css = css.split(dark_code_selector, 1)[1].split("}", 1)[0]
    assert "background-color: #222a32;" in dark_code_css
    assert "color: #f1f4f6;" in dark_code_css
    assert "border-color: #455260;" in dark_code_css

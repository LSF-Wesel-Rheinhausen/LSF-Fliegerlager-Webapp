from pathlib import Path


def test_app_css_contains_darkmode_code_contrast_styling():
    css_path = Path(__file__).resolve().parents[1] / "src/static/billing/app-v8.css"
    css = css_path.read_text(encoding="utf-8")

    assert "code {" in css
    assert ':root[data-theme="dark"] code {' in css or "code" in css
    assert "metadata-list dd {" in css

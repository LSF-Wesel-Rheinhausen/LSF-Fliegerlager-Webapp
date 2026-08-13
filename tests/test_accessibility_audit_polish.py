from pathlib import Path


def test_templates_include_wcag_landmarks_and_skip_links():
    templates_dir = Path(__file__).resolve().parents[1] / "src/templates"
    base_html = (templates_dir / "base.html").read_text(encoding="utf-8")
    kiosk_base_html = (templates_dir / "billing/kiosk_base.html").read_text(encoding="utf-8")

    for html in (base_html, kiosk_base_html):
        assert 'href="#main-content"' in html
        assert 'id="main-content"' in html
        assert 'tabindex="-1"' in html
        assert "<header" in html
        assert "aria-label=" in html

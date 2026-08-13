from pathlib import Path


def test_base_templates_contain_screen_reader_live_regions():
    templates_dir = Path(__file__).resolve().parents[1] / "src/templates"
    base_html = (templates_dir / "base.html").read_text(encoding="utf-8")
    kiosk_base_html = (templates_dir / "billing/kiosk_base.html").read_text(encoding="utf-8")

    for html in (base_html, kiosk_base_html):
        assert 'id="sr-announcer-polite"' in html
        assert 'aria-live="polite"' in html
        assert 'id="sr-announcer-assertive"' in html
        assert 'aria-live="assertive"' in html

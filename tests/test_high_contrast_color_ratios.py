from pathlib import Path

from billing.pwa_views import PWA_CACHE_VERSION


def test_high_contrast_theme_css_rules_exist():
    css_path = Path(__file__).resolve().parents[1] / "src/static/billing/app-v8.css"
    css = css_path.read_text(encoding="utf-8")

    assert ':root[data-theme="high-contrast"]' in css
    assert "@media (prefers-contrast: more)" in css
    assert "@media (forced-colors: active)" in css
    assert "--text: #1a2027" in css or "--text:" in css
    assert "outline: 3px solid" in css


def test_pwa_cache_version_bumped_for_accessibility_css():
    assert PWA_CACHE_VERSION >= 37

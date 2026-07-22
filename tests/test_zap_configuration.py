from pathlib import Path

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]


def test_modern_web_application_alert_is_documented_as_ignored() -> None:
    rules = [
        line.split("\t")
        for line in (REPOSITORY_ROOT / ".zap" / "rules.tsv").read_text().splitlines()
        if line.startswith("10109\t")
    ]

    assert rules == [
        [
            "10109",
            "IGNORE",
            "(The JavaScript-enhanced help page is expected to be detected as a modern "
            "web application; this informational alert does not identify a security issue)",
        ]
    ]

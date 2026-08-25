from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TEST_LOCAL_SCRIPT = PROJECT_ROOT / "scripts" / "test-local.sh"
DEV_REQUIREMENTS = PROJECT_ROOT / "requirements-dev.txt"


def test_local_runner_parallelizes_pytest_with_a_portable_serial_fallback() -> None:
    script = TEST_LOCAL_SCRIPT.read_text(encoding="utf-8")
    parallel_tests = ".venv/bin/python -m pytest -n ${pytest_workers} --dist=loadfile --ignore=tests/test_migrations.py"
    migration_tests = ".venv/bin/python -m pytest tests/test_migrations.py"
    parallel_step = f'"Python tests|{parallel_tests}"'
    migration_step = f'"Python migration tests|{migration_tests}"'

    assert 'pytest_workers="${PYTEST_WORKERS:-4}"' in script
    assert '[[ ! "${pytest_workers}" =~ ^[0-9]+$ ]]' in script
    assert parallel_step in script
    assert migration_step in script
    assert script.index(parallel_step) < script.index(migration_step)


def test_dev_requirements_include_portable_xdist_version() -> None:
    requirements = DEV_REQUIREMENTS.read_text(encoding="utf-8").splitlines()

    assert "pytest-xdist>=3.8.0,<4" in requirements

from pathlib import Path

START_E2E = Path(__file__).parents[1] / "scripts" / "start-e2e.sh"


def test_start_e2e_keeps_minimal_prerequisites_before_optional_demo_seed():
    script = START_E2E.read_text()
    migrate = "$PYTHON src/manage.py migrate --noinput"
    optional_seed = 'if [[ "${SEED_LOCAL_TEST_DB:-0}" == "1" ]]'

    assert migrate in script
    assert optional_seed in script
    assert script.index(migrate) < script.index(optional_seed)
    minimal_setup = script[script.index(migrate) + len(migrate) : script.index(optional_seed)]
    assert 'name="E2E-Lagerzugang"' in minimal_setup
    assert "CampKioskAccess" in minimal_setup
    assert 'access.set_pin("864208")' in minimal_setup
    assert "src/db.sqlite3" not in script

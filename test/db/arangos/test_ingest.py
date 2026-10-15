import pytest

from test.db.arangos.conftest import ingest


@pytest.fixture(scope="function")
def modes():
    return [
        "kg",
        "ibes",
    ]


@pytest.mark.parametrize("n_cores", [1, 2])
def test_ingest(
    create_db,
    modes,
    conn_conf,
    current_path,
    test_db_name,
    reset,
    n_cores,
):
    ingest(
        create_db,
        modes,
        conn_conf,
        current_path,
        test_db_name,
        reset,
        n_cores=n_cores,
    )

from conftest import register, register_trainer


def test_assignments_have_a_solution_store(client):
    from app.db import get_conn

    register(client)
    with get_conn() as conn:
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(assignments)")}
    assert "solution_code" in columns
    assert "last_stdin" in columns


def test_the_backfill_runs_once_and_is_recorded(client):
    from app.db import get_conn, init_db

    register(client)
    init_db()  # a second start must not re-run the backfill
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT COUNT(*) FROM migrations WHERE key = 'notebook_code_to_solution_v1'"
        ).fetchone()[0]
    assert rows == 1

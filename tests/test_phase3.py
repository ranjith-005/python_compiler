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


def test_the_backfill_copies_notebook_code_in_order_and_skips_markdown(client):
    from app.db import _backfill_solution_code, create_notebook, get_conn, utcnow

    register(client)
    register_trainer(client)
    with get_conn() as conn:
        student_id = conn.execute(
            "SELECT id FROM users WHERE role = 'student'"
        ).fetchone()["id"]
        trainer_id = conn.execute(
            "SELECT id FROM users WHERE role = 'trainer'"
        ).fetchone()["id"]

        notebook_id = create_notebook(
            conn,
            student_id,
            "work.ipynb",
            [
                ("code", "a = 1"),
                ("markdown", "## notes the student wrote"),
                ("code", "print(a)"),
            ],
        )

        now = utcnow()
        cur = conn.execute(
            "INSERT INTO exercises (trainer_id, title, created_at, updated_at)"
            " VALUES (?, 'Ex', ?, ?)",
            (trainer_id, now, now),
        )
        exercise_id = cur.lastrowid
        cur = conn.execute(
            "INSERT INTO assignments"
            " (exercise_id, student_id, assigned_by, assigned_at, notebook_id)"
            " VALUES (?, ?, ?, ?, ?)",
            (exercise_id, student_id, trainer_id, now, notebook_id),
        )
        assignment_id = cur.lastrowid

        # The guard already fired (with nothing to copy) during the client
        # fixture's init_db(). Clear it so the backfill runs again here, and
        # reset solution_code to '' so the row matches the backfill's filter.
        conn.execute("DELETE FROM migrations WHERE key = 'notebook_code_to_solution_v1'")
        conn.execute(
            "UPDATE assignments SET solution_code = '' WHERE id = ?", (assignment_id,)
        )

        _backfill_solution_code(conn)

        carried = conn.execute(
            "SELECT solution_code FROM assignments WHERE id = ?", (assignment_id,)
        ).fetchone()["solution_code"]

    assert carried == "a = 1\n\nprint(a)"

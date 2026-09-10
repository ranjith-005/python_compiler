"""Header search: titles and names, scoped to what the viewer may see."""

from conftest import register, register_trainer
from test_modules import upload


def test_a_trainer_finds_their_own_module(client):
    register_trainer(client)
    upload(client, title="Python Loops")
    results = client.get("/api/search?q=loops").json()["results"]
    assert any(r["kind"] == "module" and "Loops" in r["label"] for r in results)


def test_a_trainer_finds_a_student_by_name(client):
    register(client, email="aditi@example.com", name="Aditi Sharma")
    client.post("/auth/logout")
    register_trainer(client)
    results = client.get("/api/search?q=aditi").json()["results"]
    assert any(r["kind"] == "student" for r in results)


def test_a_student_never_finds_an_unassigned_module(client):
    """Authorisation is the point of this endpoint, not a detail of it."""
    register_trainer(client)
    upload(client, title="Secret Draft")
    client.post("/auth/logout")

    register(client, email="outsider@example.com")
    results = client.get("/api/search?q=secret").json()["results"]
    assert results == []


def test_an_empty_query_returns_nothing_and_does_not_error(client):
    register_trainer(client)
    res = client.get("/api/search?q=")
    assert res.status_code == 200
    assert res.json()["results"] == []


def test_a_student_never_finds_another_students_record(client):
    """Only a trainer searches people. A student finding classmates by name
    would turn the search box into a roster."""
    register(client, email="classmate@example.com", name="Class Mate")
    client.post("/auth/logout")
    register(client, email="searcher@example.com", name="Search Er")
    results = client.get("/api/search?q=mate").json()["results"]
    assert not any(r["kind"] == "student" for r in results), results


def test_a_visitor_cannot_search_at_all(client):
    assert client.get("/api/search?q=python").status_code == 401


def test_a_whitespace_query_is_treated_as_empty(client):
    """"   " would otherwise become LIKE '%   %' and match nothing slowly."""
    register_trainer(client)
    assert client.get("/api/search?q=%20%20").json()["results"] == []


def test_a_wildcard_is_matched_literally_not_as_a_pattern(client):
    """A user typing % must not get every row back: LIKE treats it as "any
    sequence", so an unescaped query is a way to dump the table."""
    register_trainer(client)
    upload(client, title="Python Loops")
    results = client.get("/api/search?q=%25").json()["results"]
    assert results == [], results


def test_search_is_case_insensitive(client):
    register_trainer(client)
    upload(client, title="Python Loops")
    lower = client.get("/api/search?q=python").json()["results"]
    upper = client.get("/api/search?q=PYTHON").json()["results"]
    assert lower and [r["label"] for r in lower] == [r["label"] for r in upper]

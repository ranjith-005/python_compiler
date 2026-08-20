"""Notebook/cell REST API, ownership isolation, and .ipynb round-trip."""

import json

import nbformat
from conftest import register


def make_notebook(client, name="Test.ipynb"):
    response = client.post("/api/notebooks", json={"name": name})
    assert response.status_code == 201, response.text
    return response.json()


def test_notebook_endpoints_require_auth(client):
    assert client.get("/api/notebooks").status_code == 401
    assert client.post("/api/notebooks", json={"name": "x"}).status_code == 401


def test_register_creates_a_welcome_notebook(client):
    register(client)
    notebooks = client.get("/api/notebooks").json()
    assert [n["name"] for n in notebooks] == ["Welcome.ipynb"]
    assert notebooks[0]["cell_count"] == 3

    detail = client.get(f"/api/notebooks/{notebooks[0]['id']}").json()
    assert [c["cell_type"] for c in detail["cells"]] == ["code", "code", "code"]
    assert [c["position"] for c in detail["cells"]] == [0, 1, 2]


def test_notebook_crud(client):
    register(client)
    nb = make_notebook(client)
    assert len(nb["cells"]) == 1 and nb["cells"][0]["cell_type"] == "code"

    renamed = client.put(f"/api/notebooks/{nb['id']}", json={"name": "Renamed.ipynb"}).json()
    assert renamed["name"] == "Renamed.ipynb"

    assert client.delete(f"/api/notebooks/{nb['id']}").status_code == 200
    assert client.get(f"/api/notebooks/{nb['id']}").status_code == 404


def test_cell_add_update_delete_and_positions(client):
    register(client)
    nb = make_notebook(client)
    first = nb["cells"][0]["id"]

    md = client.post(
        f"/api/notebooks/{nb['id']}/cells", json={"cell_type": "markdown", "source": "# Title"}
    ).json()
    code = client.post(
        f"/api/notebooks/{nb['id']}/cells", json={"cell_type": "code", "source": "print(1)"}
    ).json()

    detail = client.get(f"/api/notebooks/{nb['id']}").json()
    assert [c["id"] for c in detail["cells"]] == [first, md["id"], code["id"]]
    assert [c["position"] for c in detail["cells"]] == [0, 1, 2]

    updated = client.put(
        f"/api/notebooks/{nb['id']}/cells/{code['id']}",
        json={"source": "print(2)", "execution_count": 7,
              "outputs": [{"output_type": "stream", "name": "stdout", "text": "2\n"}]},
    ).json()
    assert updated["source"] == "print(2)"
    assert updated["execution_count"] == 7
    assert updated["outputs"][0]["text"] == "2\n"

    assert client.delete(f"/api/notebooks/{nb['id']}/cells/{md['id']}").status_code == 200
    detail = client.get(f"/api/notebooks/{nb['id']}").json()
    assert [c["position"] for c in detail["cells"]] == [0, 1]


def test_insert_cell_at_position(client):
    register(client)
    nb = make_notebook(client)
    first = nb["cells"][0]["id"]
    inserted = client.post(
        f"/api/notebooks/{nb['id']}/cells", json={"cell_type": "code", "source": "x", "position": 0}
    ).json()
    detail = client.get(f"/api/notebooks/{nb['id']}").json()
    assert [c["id"] for c in detail["cells"]] == [inserted["id"], first]


def test_reorder_cells(client):
    register(client)
    nb = make_notebook(client)
    a = nb["cells"][0]["id"]
    b = client.post(f"/api/notebooks/{nb['id']}/cells", json={"source": "b"}).json()["id"]
    c = client.post(f"/api/notebooks/{nb['id']}/cells", json={"source": "c"}).json()["id"]

    assert client.post(f"/api/notebooks/{nb['id']}/reorder", json={"cell_ids": [c, a, b]}).status_code == 200
    detail = client.get(f"/api/notebooks/{nb['id']}").json()
    assert [cell["id"] for cell in detail["cells"]] == [c, a, b]

    # A partial list is rejected rather than silently dropping cells.
    assert client.post(f"/api/notebooks/{nb['id']}/reorder", json={"cell_ids": [a]}).status_code == 422


def test_bad_cell_type_rejected(client):
    register(client)
    nb = make_notebook(client)
    assert client.post(f"/api/notebooks/{nb['id']}/cells", json={"cell_type": "raw"}).status_code == 422


def test_users_cannot_touch_each_others_notebooks(client):
    register(client, email="a@example.com")
    nb = make_notebook(client, "Private.ipynb")
    cell_id = nb["cells"][0]["id"]
    client.post("/auth/logout")

    register(client, email="b@example.com")
    assert client.get(f"/api/notebooks/{nb['id']}").status_code == 404
    assert client.put(f"/api/notebooks/{nb['id']}", json={"name": "hacked"}).status_code == 404
    assert client.delete(f"/api/notebooks/{nb['id']}").status_code == 404
    assert client.post(f"/api/notebooks/{nb['id']}/cells", json={"source": "x"}).status_code == 404
    assert client.put(f"/api/notebooks/{nb['id']}/cells/{cell_id}", json={"source": "x"}).status_code == 404
    assert client.delete(f"/api/notebooks/{nb['id']}/cells/{cell_id}").status_code == 404
    assert client.get(f"/api/notebooks/{nb['id']}/export").status_code == 404
    assert [n["name"] for n in client.get("/api/notebooks").json()] == ["Welcome.ipynb"]


def test_duplicate_notebook_copies_cells_and_outputs(client):
    register(client)
    nb = make_notebook(client, "Original.ipynb")
    client.put(
        f"/api/notebooks/{nb['id']}/cells/{nb['cells'][0]['id']}",
        json={"source": "print('hi')", "execution_count": 4,
              "outputs": [{"output_type": "stream", "name": "stdout", "text": "hi\n"}]},
    )
    client.post(f"/api/notebooks/{nb['id']}/cells", json={"cell_type": "markdown", "source": "# Notes"})

    copy = client.post(f"/api/notebooks/{nb['id']}/duplicate", json={})
    assert copy.status_code == 201, copy.text
    body = copy.json()
    assert body["name"] == "Copy of Original.ipynb"
    assert body["id"] != nb["id"]
    assert [c["cell_type"] for c in body["cells"]] == ["code", "markdown"]
    assert body["cells"][0]["source"] == "print('hi')"
    assert body["cells"][0]["outputs"][0]["text"] == "hi\n"
    assert body["cells"][0]["execution_count"] == 4

    # The copy is independent: editing it leaves the original alone.
    client.put(f"/api/notebooks/{body['id']}/cells/{body['cells'][0]['id']}", json={"source": "changed"})
    assert client.get(f"/api/notebooks/{nb['id']}").json()["cells"][0]["source"] == "print('hi')"


def test_clear_all_outputs(client):
    register(client)
    nb = make_notebook(client)
    client.put(
        f"/api/notebooks/{nb['id']}/cells/{nb['cells'][0]['id']}",
        json={"execution_count": 2,
              "outputs": [{"output_type": "stream", "name": "stdout", "text": "x\n"}]},
    )
    assert client.post(f"/api/notebooks/{nb['id']}/clear-outputs").json()["cleared"] == 1

    cell = client.get(f"/api/notebooks/{nb['id']}").json()["cells"][0]
    assert cell["outputs"] == []
    assert cell["execution_count"] is None
    # The code itself is untouched.
    assert cell["source"] == nb["cells"][0]["source"]


def test_duplicate_and_clear_respect_ownership(client):
    register(client, email="a@example.com")
    nb = make_notebook(client, "Mine.ipynb")
    client.post("/auth/logout")

    register(client, email="b@example.com")
    assert client.post(f"/api/notebooks/{nb['id']}/duplicate").status_code == 404
    assert client.post(f"/api/notebooks/{nb['id']}/clear-outputs").status_code == 404


def test_ipynb_export_is_valid(client):
    register(client)
    nb = make_notebook(client, "Export.ipynb")
    client.put(
        f"/api/notebooks/{nb['id']}/cells/{nb['cells'][0]['id']}",
        json={"source": "print('hi')", "execution_count": 1,
              "outputs": [{"output_type": "stream", "name": "stdout", "text": "hi\n"}]},
    )
    client.post(f"/api/notebooks/{nb['id']}/cells", json={"cell_type": "markdown", "source": "# Heading"})

    response = client.get(f"/api/notebooks/{nb['id']}/export")
    assert response.status_code == 200
    assert "attachment" in response.headers["content-disposition"]

    parsed = nbformat.reads(response.text, as_version=4)
    nbformat.validate(parsed)
    assert [c["cell_type"] for c in parsed.cells] == ["code", "markdown"]
    assert parsed.cells[0]["outputs"][0]["text"] == "hi\n"
    assert parsed.cells[0]["execution_count"] == 1


def test_ipynb_import_round_trip(client):
    register(client)
    nb = nbformat.v4.new_notebook()
    code = nbformat.v4.new_code_cell("print('imported')")
    code["execution_count"] = 3
    code["outputs"] = [
        nbformat.v4.new_output("stream", name="stdout", text="imported\n")
    ]
    nb.cells = [nbformat.v4.new_markdown_cell("# From Colab"), code]

    response = client.post(
        "/api/notebooks/import",
        files={"file": ("FromColab.ipynb", nbformat.writes(nb), "application/x-ipynb+json")},
    )
    assert response.status_code == 201, response.text
    imported = response.json()
    assert imported["name"] == "FromColab.ipynb"
    assert [c["cell_type"] for c in imported["cells"]] == ["markdown", "code"]
    assert imported["cells"][1]["source"] == "print('imported')"
    assert imported["cells"][1]["execution_count"] == 3
    assert imported["cells"][1]["outputs"][0]["text"] == "imported\n"

    # Round-trips back out unchanged.
    exported = nbformat.reads(client.get(f"/api/notebooks/{imported['id']}/export").text, as_version=4)
    assert exported.cells[1]["source"] == "print('imported')"


def test_import_rejects_garbage(client):
    register(client)
    response = client.post(
        "/api/notebooks/import", files={"file": ("bad.ipynb", b"not json at all", "application/json")}
    )
    assert response.status_code == 422


def test_pages_render(client):
    register(client)
    assert client.get("/", follow_redirects=False).headers["location"] == "/student"
    assert client.get("/notebooks").status_code == 200

    nb_id = client.get("/api/notebooks").json()[0]["id"]
    page = client.get(f"/nb/{nb_id}")
    assert page.status_code == 200
    assert "notebook.js" in page.text
    assert json.loads(page.text.split('type="application/json">')[1].split("</script>")[0])["notebookId"] == nb_id

    # Someone else's notebook id bounces back to the list.
    assert client.get("/nb/999999", follow_redirects=False).headers["location"] == "/notebooks"


def test_retired_script_editor_routes_are_gone(client):
    register(client)
    assert client.get("/ide").status_code == 404
    assert client.post("/api/run", json={"code": "print(1)"}).status_code == 404
    assert client.get("/api/snippets").status_code == 404
    assert client.get("/api/history").status_code == 404

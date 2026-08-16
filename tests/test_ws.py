"""The notebook WebSocket: streaming execution over a live kernel."""

import asyncio
import json

import pytest
from conftest import register

from app.kernel import registry


@pytest.fixture(autouse=True)
def _shutdown_kernels():
    yield
    asyncio.run(registry.shutdown_all())


def drain(ws, until="done", limit=200):
    """Collect messages until a `done` (or `type` == until) arrives."""
    messages = []
    for _ in range(limit):
        msg = ws.receive_json()
        messages.append(msg)
        if msg.get("type") == until:
            return messages
    raise AssertionError(f"never saw {until}; got {[m.get('type') for m in messages]}")


def stream_text(messages):
    return "".join(
        m["output"].get("text", "")
        for m in messages
        if m.get("type") == "output" and m["output"]["output_type"] == "stream"
    )


def test_websocket_requires_auth(client):
    with pytest.raises(Exception):
        with client.websocket_connect("/ws/kernel/1"):
            pass


def test_websocket_rejects_another_users_notebook(client):
    register(client, email="a@example.com")
    nb_id = client.get("/api/notebooks").json()[0]["id"]
    client.post("/auth/logout")

    register(client, email="b@example.com")
    with pytest.raises(Exception):
        with client.websocket_connect(f"/ws/kernel/{nb_id}"):
            pass


def test_execute_streams_output_and_persists_it(client):
    register(client)
    nb = client.post("/api/notebooks", json={"name": "WS.ipynb"}).json()
    cell_id = nb["cells"][0]["id"]

    with client.websocket_connect(f"/ws/kernel/{nb['id']}") as ws:
        ws.send_json({"type": "execute", "cell_id": cell_id, "code": "print('streamed')\n7 * 6"})
        messages = drain(ws)

    assert "streamed" in stream_text(messages)
    results = [
        m["output"] for m in messages
        if m.get("type") == "output" and m["output"]["output_type"] == "execute_result"
    ]
    assert results and results[0]["data"]["text/plain"].strip() == "42"

    done = [m for m in messages if m["type"] == "done"][0]
    assert done["error"] is False and done["execution_count"] >= 1

    # Outputs were written to the database, so a page reload shows them again.
    stored = client.get(f"/api/notebooks/{nb['id']}").json()["cells"][0]
    assert stored["execution_count"] == done["execution_count"]
    kinds = [o["output_type"] for o in stored["outputs"]]
    assert "stream" in kinds and "execute_result" in kinds


def test_state_persists_between_cells_over_the_socket(client):
    register(client)
    nb = client.post("/api/notebooks", json={"name": "State.ipynb"}).json()
    first = nb["cells"][0]["id"]
    second = client.post(f"/api/notebooks/{nb['id']}/cells", json={"source": ""}).json()["id"]

    with client.websocket_connect(f"/ws/kernel/{nb['id']}") as ws:
        ws.send_json({"type": "execute", "cell_id": first, "code": "shared = 'colab-style'"})
        drain(ws)
        ws.send_json({"type": "execute", "cell_id": second, "code": "print(shared)"})
        messages = drain(ws)

    assert "colab-style" in stream_text(messages)


def test_error_cell_reports_traceback(client):
    register(client)
    nb = client.post("/api/notebooks", json={"name": "Err.ipynb"}).json()
    cell_id = nb["cells"][0]["id"]

    with client.websocket_connect(f"/ws/kernel/{nb['id']}") as ws:
        ws.send_json({"type": "execute", "cell_id": cell_id, "code": "undefined_name"})
        messages = drain(ws)

    errors = [
        m["output"] for m in messages
        if m.get("type") == "output" and m["output"]["output_type"] == "error"
    ]
    assert errors and errors[0]["ename"] == "NameError"
    assert [m for m in messages if m["type"] == "done"][0]["error"] is True


def test_input_request_round_trip(client):
    register(client)
    nb = client.post("/api/notebooks", json={"name": "Input.ipynb"}).json()
    cell_id = nb["cells"][0]["id"]

    with client.websocket_connect(f"/ws/kernel/{nb['id']}") as ws:
        ws.send_json(
            {"type": "execute", "cell_id": cell_id, "code": "who = input('name? ')\nprint('hello', who)"}
        )
        messages = []
        for _ in range(200):
            msg = ws.receive_json()
            messages.append(msg)
            if msg.get("type") == "input_request":
                assert "name?" in msg["prompt"]
                ws.send_json({"type": "input_reply", "value": "grace"})
            if msg.get("type") == "done":
                break

    assert any(m.get("type") == "input_request" for m in messages)
    assert "hello grace" in stream_text(messages)


def test_restart_clears_variables(client):
    register(client)
    nb = client.post("/api/notebooks", json={"name": "Restart.ipynb"}).json()
    cell_id = nb["cells"][0]["id"]

    with client.websocket_connect(f"/ws/kernel/{nb['id']}") as ws:
        ws.send_json({"type": "execute", "cell_id": cell_id, "code": "keeper = 1"})
        drain(ws)
        ws.send_json({"type": "restart"})
        drain(ws, until="restarted")
        ws.send_json({"type": "execute", "cell_id": cell_id, "code": "print(keeper)"})
        messages = drain(ws)

    errors = [
        m["output"] for m in messages
        if m.get("type") == "output" and m["output"]["output_type"] == "error"
    ]
    assert errors and errors[0]["ename"] == "NameError"

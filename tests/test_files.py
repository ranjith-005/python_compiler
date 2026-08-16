"""Workspace file manager: uploads, isolation, and path-traversal defence."""

import io

import pytest
from conftest import register

from app.workspace import UnsafePath, resolve_within, safe_name, workspace_dir


def upload(client, name, content, path=""):
    return client.post(
        f"/api/files/upload?path={path}",
        files={"files": (name, io.BytesIO(content), "application/octet-stream")},
    )


def test_file_endpoints_require_auth(client):
    assert client.get("/api/files").status_code == 401
    assert client.post("/api/files/upload", files={"files": ("a.txt", b"x")}).status_code == 401
    assert client.get("/api/files/download?path=a.txt").status_code == 401


def test_upload_list_download_delete(client):
    register(client)
    response = upload(client, "data.csv", b"a,b\n1,2\n")
    assert response.status_code == 201, response.text
    assert response.json()["saved"][0]["name"] == "data.csv"

    listing = client.get("/api/files").json()
    assert [e["name"] for e in listing["entries"]] == ["data.csv"]
    assert listing["entries"][0]["size"] == 8
    assert listing["entries"][0]["is_dir"] is False
    assert listing["used_bytes"] == 8

    got = client.get("/api/files/download?path=data.csv")
    assert got.status_code == 200
    assert got.content == b"a,b\n1,2\n"

    assert client.delete("/api/files?path=data.csv").status_code == 200
    assert client.get("/api/files").json()["entries"] == []


def test_upload_lands_in_the_kernel_working_directory(client):
    """The whole point: an uploaded file is readable from a cell by name."""
    response = register(client)
    user_id = response.json()["id"]
    upload(client, "notes.txt", b"hello from upload")
    assert (workspace_dir(user_id) / "notes.txt").read_bytes() == b"hello from upload"


def test_folders_and_nested_upload(client):
    register(client)
    assert client.post("/api/files/mkdir", json={"path": "", "name": "raw"}).status_code == 201
    upload(client, "inner.txt", b"nested", path="raw")

    root = client.get("/api/files").json()
    assert [(e["name"], e["is_dir"]) for e in root["entries"]] == [("raw", True)]

    nested = client.get("/api/files?path=raw").json()
    assert nested["path"] == "raw"
    assert [e["name"] for e in nested["entries"]] == ["inner.txt"]
    assert client.get("/api/files/download?path=raw/inner.txt").content == b"nested"

    # Deleting the folder removes its contents.
    assert client.delete("/api/files?path=raw").status_code == 200
    assert client.get("/api/files").json()["entries"] == []


def test_duplicate_folder_rejected(client):
    register(client)
    client.post("/api/files/mkdir", json={"name": "data"})
    assert client.post("/api/files/mkdir", json={"name": "data"}).status_code == 409


def test_rename(client):
    register(client)
    upload(client, "old.txt", b"x")
    renamed = client.post("/api/files/rename", json={"path": "old.txt", "new_name": "new.txt"})
    assert renamed.status_code == 200 and renamed.json()["name"] == "new.txt"
    assert client.get("/api/files/download?path=new.txt").status_code == 200


@pytest.mark.parametrize(
    "attack",
    [
        "../escape.txt",
        "../../escape.txt",
        "..\\..\\escape.txt",
        "raw/../../escape.txt",
        "C:\\Windows\\System32\\drivers\\etc\\hosts",
        "/etc/passwd",
    ],
)
def test_path_traversal_is_blocked(client, attack):
    register(client)
    assert client.get(f"/api/files?path={attack}").status_code in (400, 404)
    assert client.delete(f"/api/files?path={attack}").status_code in (400, 404)
    assert client.get(f"/api/files/download?path={attack}").status_code in (400, 404)


def test_uploaded_filename_is_reduced_to_a_basename(client):
    register(client)
    response = upload(client, "../../evil.txt", b"nope")
    assert response.status_code == 201
    assert response.json()["saved"][0]["name"] == "evil.txt"
    assert [e["name"] for e in client.get("/api/files").json()["entries"]] == ["evil.txt"]


def test_users_cannot_see_each_others_files(client):
    register(client, email="a@example.com")
    upload(client, "secret.csv", b"private")
    client.post("/auth/logout")

    register(client, email="b@example.com")
    assert client.get("/api/files").json()["entries"] == []
    assert client.get("/api/files/download?path=secret.csv").status_code == 404
    assert client.delete("/api/files?path=secret.csv").status_code == 404

    client.post("/auth/logout")
    client.post("/auth/login", json={"email": "a@example.com", "password": "password123"})
    assert client.get("/api/files/download?path=secret.csv").content == b"private"


def test_open_text_file_returns_its_contents(client):
    register(client)
    upload(client, "notes.txt", "line one\nline two\n".encode("utf-8"))
    info = client.get("/api/files/content?path=notes.txt").json()
    assert info["kind"] == "text"
    assert info["content"] == "line one\nline two\n"
    assert info["name"] == "notes.txt"
    assert info["size"] == 18


def test_edit_and_save_a_file(client):
    register(client)
    upload(client, "edit.py", b"print('before')\n")
    saved = client.put(
        "/api/files/content", json={"path": "edit.py", "content": "print('after')\n"}
    )
    assert saved.status_code == 200
    assert client.get("/api/files/content?path=edit.py").json()["content"] == "print('after')\n"
    # The file on disk changed, so a cell reading it sees the new text.
    assert client.get("/api/files/download?path=edit.py").content == b"print('after')\n"


def test_open_reports_images_and_binaries(client):
    register(client)
    upload(client, "pic.png", b"\x89PNG\r\n\x1a\n" + b"\x00" * 40)
    assert client.get("/api/files/content?path=pic.png").json()["kind"] == "image"
    assert client.get("/api/files/raw?path=pic.png").status_code == 200
    assert client.get("/api/files/raw?path=pic.png").headers["content-type"].startswith("image/")

    upload(client, "blob.bin", bytes([0xFF, 0xFE, 0x00, 0x01, 0x80]))
    assert client.get("/api/files/content?path=blob.bin").json()["kind"] == "binary"


def test_open_refuses_oversized_files(client, monkeypatch):
    from app import files as files_module

    register(client)
    monkeypatch.setattr(files_module, "MAX_EDIT_BYTES", 10)
    upload(client, "big.txt", b"x" * 100)
    assert client.get("/api/files/content?path=big.txt").json()["kind"] == "large"


def test_content_endpoints_enforce_ownership_and_paths(client):
    register(client, email="a@example.com")
    upload(client, "mine.txt", b"secret")
    client.post("/auth/logout")

    register(client, email="b@example.com")
    assert client.get("/api/files/content?path=mine.txt").status_code == 404
    assert client.put("/api/files/content", json={"path": "mine.txt", "content": "x"}).status_code == 404
    assert client.get("/api/files/content?path=../../escape.txt").status_code in (400, 404)
    assert client.get("/api/files/raw?path=../../escape.txt").status_code in (400, 404)


def test_cannot_delete_workspace_root(client):
    register(client)
    assert client.delete("/api/files?path=").status_code == 400


def test_upload_too_large_is_rejected(client, monkeypatch):
    from app import files as files_module

    register(client)
    monkeypatch.setattr(files_module.settings, "MAX_UPLOAD_BYTES", 10)
    response = upload(client, "big.bin", b"x" * 50)
    assert response.status_code == 413
    # The partial file is cleaned up rather than left behind.
    assert client.get("/api/files").json()["entries"] == []


def test_safe_name_helpers():
    assert safe_name("report.csv") == "report.csv"
    assert safe_name("../../etc/passwd") == "passwd"
    assert safe_name("bad:name?.txt") == "bad_name_.txt"
    assert safe_name("CON.txt") == "_CON.txt"
    assert safe_name("trailing. ") == "trailing"
    with pytest.raises(UnsafePath):
        safe_name("..")
    with pytest.raises(UnsafePath):
        safe_name("")


def test_resolve_within_rejects_escapes():
    root = workspace_dir(4242).resolve()
    assert resolve_within(4242, "sub/file.txt").is_relative_to(root)
    assert resolve_within(4242, "") == root
    with pytest.raises(UnsafePath):
        resolve_within(4242, "../other")

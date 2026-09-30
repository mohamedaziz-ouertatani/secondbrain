import pymupdf
import pytest
from fakes import fake_embed, words


@pytest.fixture
def client(env):
    from fastapi.testclient import TestClient

    from app.main import create_app

    return TestClient(create_app())  # no `with`: no watcher


def test_pdf_page_images(env, client):
    from app.ingest.pipeline import rescan

    inbox, _ = env
    (inbox / "Optim").mkdir(parents=True)
    with pymupdf.open() as pdf:
        for n in (1, 2):
            pdf.new_page().insert_text((72, 72), f"Page {n}: the norm of u is the square root of the sum of squares. " * 3)
        pdf.save(inbox / "Optim" / "norms.pdf")
    (inbox / "Optim" / "note.md").write_text("A note about norms and the triangle inequality. " * 5, encoding="utf-8")
    rescan(fake_embed, words)

    ids = {d["path"]: d["id"] for d in client.get("/documents").json()}
    pdf_id = ids["Optim/norms.pdf"]

    page = client.get(f"/documents/{pdf_id}/pages/2.png")
    assert page.status_code == 200
    assert page.headers["content-type"] == "image/png"
    assert page.content.startswith(b"\x89PNG")

    assert client.get(f"/documents/{pdf_id}/pages/0.png").status_code == 404
    assert client.get(f"/documents/{pdf_id}/pages/3.png").status_code == 404
    assert client.get(f"/documents/{ids['Optim/note.md']}/pages/1.png").status_code == 404


def test_note_images_are_served_beside_the_note(env, client):
    from app.ingest.pipeline import rescan

    inbox, _ = env
    (inbox / "Optim" / "Serie 1").mkdir(parents=True)
    (inbox / "Optim" / "Serie 1.md").write_text("![fig](<Serie 1/fig 1.png>) " + "Norms and balls. " * 10, encoding="utf-8")
    (inbox / "Optim" / "Serie 1" / "fig 1.png").write_bytes(b"\x89PNG fake")
    (inbox / "Optim" / "Serie 1" / "notes.txt").write_text("not an image", encoding="utf-8")
    (inbox.parent / "outside.png").write_bytes(b"\x89PNG secret")
    rescan(fake_embed, words)
    doc = {d["path"]: d["id"] for d in client.get("/documents").json()}["Optim/Serie 1.md"]

    img = client.get(f"/documents/{doc}/assets/Serie%201/fig%201.png")
    assert img.status_code == 200 and img.headers["content-type"] == "image/png"
    assert img.content == b"\x89PNG fake"
    assert client.get(f"/documents/{doc}/assets/Serie%201/missing.png").status_code == 404
    assert client.get(f"/documents/{doc}/assets/Serie%201/notes.txt").status_code == 404  # images only
    assert client.get(f"/documents/{doc}/assets/..%2F..%2Foutside.png").status_code == 404  # stays in the inbox

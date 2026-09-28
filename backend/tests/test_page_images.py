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

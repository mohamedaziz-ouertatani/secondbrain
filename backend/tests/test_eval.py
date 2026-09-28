from fakes import fake_embed, words


def test_quotas_are_proportional_with_a_floor():
    from app.eval.generate import quotas

    q = quotas({"A": 100, "B": 10, "C": 3}, 30)
    assert sum(q.values()) == 30 and q["C"] == 3 and q["B"] >= 5 and q["A"] > q["B"]
    assert quotas({"A": 100, "B": 100}, 4) == {"A": 2, "B": 2}
    assert sum(quotas({"A": 3, "B": 2}, 50).values()) == 5  # never more than exists


def test_reject_reason():
    from app.eval.generate import reject_reason

    p = "Un vecteur gaussien est un vecteur aléatoire dont toute combinaison linéaire suit une loi normale."
    assert reject_reason("", p) == "empty"
    assert reject_reason("Vecteur gaussien ?", p) == "too short"
    assert reject_reason(" ".join(["mot"] * 41), p) == "too long"
    assert reject_reason("Est-ce que toute combinaison linéaire suit une loi normale ?", p) == "copies the passage"
    assert reject_reason("Qu'est-ce qui caractérise un vecteur gaussien ?", p) is None


def notes(inbox, n_courses=2, pages=4):
    """Markdown notes long enough (>= 60 tokens with the words counter), one page each."""
    for c in range(n_courses):
        for p in range(pages):
            f = inbox / f"Course{c}" / f"note{p}.md"
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(" ".join(f"topic{c}x{p} word{i}" for i in range(40)), encoding="utf-8")
    (inbox / "Course0" / "short.md").write_text("too short to ask about", encoding="utf-8")


def fake_chat(messages, schema, temperature=0.3):
    passage = messages[-1]["content"]
    token = next(w for w in passage.split() if w.startswith("topic"))
    return {"question": f"What should a student remember about {token} for the exam?"}


def test_generate_stores_questions_with_their_page(env):
    from app.eval.generate import generate
    from app.ingest.pipeline import rescan

    inbox, db = env
    notes(inbox)
    rescan(fake_embed, words)
    out = generate(n=6, chat=fake_chat)
    assert out["accepted"] == 6 and sum(out["per_course"].values()) == 6
    with db.get_pool().connection() as conn:
        rows = conn.execute("SELECT doc_path, page, question, course FROM eval_questions").fetchall()
    assert len(rows) == 6 and all(r["page"] == 1 and r["doc_path"].endswith(".md") for r in rows)
    assert not any(r["doc_path"].endswith("short.md") for r in rows)
    assert generate(n=6, chat=fake_chat)["accepted"] == 2  # only the 2 pages not asked about yet

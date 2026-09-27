from app.ingest.chunk import chunk_pages


def words(s: str) -> int:
    return len(s.split())


def para(n: int, tag: str) -> str:
    return " ".join(f"{tag}{i}" for i in range(n))


def test_short_page_is_single_chunk():
    chunks = chunk_pages(["hello world"], words, max_tokens=50, overlap=10)
    assert [(c.page, c.text) for c in chunks] == [(1, "hello world")]


def test_chunks_never_cross_pages():
    pages = [para(30, "a"), para(30, "b"), "", para(30, "c")]
    chunks = chunk_pages(pages, words, max_tokens=50, overlap=10)
    for c in chunks:
        tags = {w[0] for w in c.text.split()}
        assert len(tags) == 1
        assert {"a": 1, "b": 2, "c": 4}[tags.pop()] == c.page
    assert 3 not in {c.page for c in chunks}  # empty page yields nothing


def test_respects_budget_and_overlaps():
    paragraphs = [f"{para(20, f'p{i}_')}." for i in range(10)]
    chunks = chunk_pages(["\n\n".join(paragraphs)], words, max_tokens=50, overlap=25)
    assert len(chunks) > 1
    assert all(c.n_tokens <= 50 for c in chunks)
    for prev, nxt in zip(chunks, chunks[1:]):
        assert prev.text.split("\n")[-1] == nxt.text.split("\n")[0]


def test_long_sentence_is_split_by_words():
    chunks = chunk_pages([para(200, "w")], words, max_tokens=50, overlap=0)
    assert all(c.n_tokens <= 50 for c in chunks)
    assert " ".join(c.text for c in chunks).split() == para(200, "w").split()


def test_arabic_sentence_boundaries():
    s = "هذه جملة أولى طويلة. " * 5 + "هل هذا سؤال؟ " * 5
    chunks = chunk_pages([s.strip()], words, max_tokens=12, overlap=0)
    assert all(c.n_tokens <= 12 for c in chunks)
    assert all(c.text.rstrip().endswith((".", "؟")) for c in chunks)

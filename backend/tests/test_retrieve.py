from app.rag.retrieve import answerable, fuse, keywords


def test_keywords_drop_stopwords_and_question_words():
    assert keywords("What is RRF?") == ["rrf"]
    assert keywords("Qu'est-ce qu'un vecteur gaussien ?") == ["vecteur", "gaussien"]
    assert keywords("Quelle est la différence entre TCP et UDP ?") == ["tcp", "udp"]


def test_keywords_split_like_postgres_and_dedupe():
    # underscores and hyphens separate words; single letters are too noisy to match on
    assert keywords("Loi de B_t - B_s, loi de B_t") == ["loi"]
    assert keywords("self-attention mechanisms") == ["self", "attention", "mechanisms"]
    assert keywords("Who won the 2022 World Cup?") == ["won", "2022", "world", "cup"]


def test_keywords_arabic_and_empty():
    assert keywords("ما هي شجرة B؟") == ["شجرة"]
    assert keywords("What is it?") == []


def _hit(cid, score=0.5, **kw):
    return {"chunk_id": cid, "score": score, **kw}


def test_fuse_sums_reciprocal_ranks():
    dense = [_hit(1), _hit(2), _hit(3)]
    lexical = [_hit(3, all_terms=True), _hit(4, all_terms=False)]
    out = fuse(dense, lexical, k=60)
    assert [h["chunk_id"] for h in out] == [3, 1, 2, 4]
    top = out[0]
    assert top["dense_rank"] == 3 and top["lex_rank"] == 1
    assert top["rrf"] == 1 / 63 + 1 / 61
    assert out[1]["lex_rank"] is None and out[3]["dense_rank"] is None


def test_fuse_ties_broken_by_cosine():
    out = fuse([_hit(1, 0.4)], [_hit(2, 0.6, all_terms=False)], k=60)
    assert [h["chunk_id"] for h in out] == [2, 1]


def test_answerable_on_dense_score_or_full_keyword_match():
    assert answerable([_hit(1, 0.62)], 0.35)
    assert not answerable([_hit(1, 0.30, all_terms=False)], 0.35)
    assert answerable([_hit(1, 0.30, all_terms=True)], 0.35)
    assert not answerable([], 0.35)

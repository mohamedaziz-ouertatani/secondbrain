from app.rag.citations import validate


def test_valid_citations_kept_and_renumbered_by_first_use():
    v = validate("B is true [3]. A too [1]. Again B [3].", 3)
    assert v.text == "B is true [1]. A too [2]. Again B [1]."
    assert v.order == [3, 1]
    assert v.valid


def test_out_of_range_removed_and_flagged():
    v = validate("Claim [7]. Other [2].", 3)
    assert v.text == "Claim. Other [1]."
    assert v.invalid == [7]
    assert v.order == [2]
    assert not v.valid


def test_no_citations_is_not_valid():
    v = validate("Just an unsupported claim.", 3)
    assert v.order == [] and not v.valid


def test_grouped_citations():
    v = validate("X [1, 3] and Y [3,5].", 4)
    assert v.text == "X [1][2] and Y [2]."
    assert v.order == [1, 3]
    assert v.invalid == [5]


def test_zero_is_invalid():
    assert validate("x [0]", 2).invalid == [0]

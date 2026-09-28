from app.llm.lang import detect
from app.llm.ollama import hide_leading_think, strip_reasoning


def run(tokens):
    return "".join(hide_leading_think(iter(tokens)))


def test_plain_output_passes_through():
    assert run(["The ", "answer [1]."]) == "The answer [1]."


def test_leading_think_block_hidden():
    assert run(["<th", "ink>", "reason", "ing</think>", "\n\nAnswer", " [1]."]) == "Answer [1]."


def test_short_output_not_swallowed():
    assert run(["<", "b>"]) == "<b>"
    assert run(["Hi"]) == "Hi"


def test_unclosed_think_yields_nothing():
    assert run(["<think>", "never ends"]) == ""


def test_strip_reasoning_with_only_closing_tag():
    assert strip_reasoning("Okay, let me think... [2]\n</think>\n\nFinal [1].") == "Final [1]."
    assert strip_reasoning("No trace [1].") == "No trace [1]."


def test_language_detection():
    assert detect("ما هي شجرة B؟") == "ar"
    assert detect("Comment TCP établit-il une connexion ?") == "fr"
    assert detect("Quelle est la différence entre TCP et UDP") == "fr"
    assert detect("What does third normal form remove?") == "en"
    assert detect("Explain B-tree indexes") == "en"


def test_ollama_client_is_shared_and_follows_the_url(monkeypatch):
    from app.config import get_settings
    from app.llm import ollama

    monkeypatch.setattr(ollama, "_shared", None)
    first = ollama._client()
    assert ollama._client() is first  # reused: no per-call client or connection setup
    assert str(first.base_url).startswith("http://127.0.0.1:11434")

    monkeypatch.setenv("OLLAMA_URL", "http://127.0.0.1:9")
    get_settings.cache_clear()
    try:
        moved = ollama._client()
        assert moved is not first and str(moved.base_url).startswith("http://127.0.0.1:9")
    finally:
        get_settings.cache_clear()

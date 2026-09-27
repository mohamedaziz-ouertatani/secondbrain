"""Tiny question-language guess (ar/fr/en). Small models follow "Answer in X" far better than "same language"."""

import re

_ARABIC = re.compile(r"[؀-ۿݐ-ݿﭐ-﷿ﹰ-﻿]")
_LETTER = re.compile(r"[^\W\d_]")
_FRENCH_WORDS = {
    "le", "la", "les", "un", "une", "des", "du", "de", "est", "sont", "et", "ou", "que", "qui", "quoi",
    "quel", "quelle", "quels", "quelles", "comment", "pourquoi", "combien", "avec", "pour", "dans", "sur",
    "entre", "ce", "cette", "ces", "il", "elle", "nous", "vous", "pas", "au", "aux",
}
_ENGLISH_WORDS = {
    "the", "a", "an", "is", "are", "what", "which", "who", "how", "why", "when", "does", "do", "of",
    "in", "on", "and", "or", "to", "for", "with", "between", "this", "that", "it",
}

NAMES = {"ar": "Arabic", "fr": "French", "en": "English"}


def detect(text: str) -> str:
    letters = _LETTER.findall(text)
    if letters and len(_ARABIC.findall(text)) / len(letters) > 0.3:
        return "ar"
    words = re.findall(r"[a-zà-ÿ]+", text.lower().replace("’", "'").replace("'", " "))
    fr = sum(w in _FRENCH_WORDS for w in words) + 2 * bool(re.search(r"[àâçéèêëîïôûùüÿœ]", text.lower()))
    en = sum(w in _ENGLISH_WORDS for w in words)
    return "fr" if fr > en else "en"

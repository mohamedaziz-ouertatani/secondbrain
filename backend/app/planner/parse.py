"""One typed line -> a draft planner item, by explicit rules (no LLM, no dateparser).

dateparser was tried and read module numbers as dates ("Probability 2 12/01" -> today 22:00). Every rule
here reads a case- and accent-folded copy of the text with the same length as the original, so the spans
it finds can be underlined in what you typed.
"""

import re
import unicodedata
from datetime import date, datetime, time, timedelta

ALIASES = {
    "proba": "Probability 2", "proba 2": "Probability 2", "probability": "Probability 2",
    "optim": "Optimization for ML", "optimisation": "Optimization for ML", "optimization": "Optimization for ML",
    "deep learning": "Advanced Deep Learning", "big data": "Big Data Analytics", "aws": "AWS Fundamentals",
    "blockchain": "Certification en Blockchain",
    "ds project": "Advanced Data Science project", "projet ds": "Advanced Data Science project",
}

MONTHS = {
    "janvier": 1, "janv": 1, "january": 1, "jan": 1, "fevrier": 2, "fevr": 2, "fev": 2, "february": 2, "feb": 2,
    "mars": 3, "march": 3, "mar": 3, "avril": 4, "avr": 4, "april": 4, "apr": 4, "mai": 5, "may": 5,
    "juin": 6, "june": 6, "jun": 6, "juillet": 7, "juil": 7, "july": 7, "jul": 7, "aout": 8, "august": 8, "aug": 8,
    "septembre": 9, "september": 9, "sept": 9, "sep": 9, "octobre": 10, "october": 10, "oct": 10,
    "novembre": 11, "november": 11, "nov": 11, "decembre": 12, "december": 12, "dec": 12,
}
WEEKDAYS = {
    "lundi": 0, "mardi": 1, "mercredi": 2, "jeudi": 3, "vendredi": 4, "samedi": 5, "dimanche": 6,
    "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4, "saturday": 5, "sunday": 6,
    "mon": 0, "tues": 1, "tue": 1, "wed": 2, "thurs": 3, "thu": 3, "fri": 4, "sat": 5, "sun": 6,
}
RELATIVE = {"aujourd'hui": 0, "aujourdhui": 0, "today": 0, "apres-demain": 2, "apres demain": 2,
            "demain": 1, "tomorrow": 1}


def _alt(words) -> str:
    return "|".join(re.escape(w) for w in sorted(words, key=len, reverse=True))


B, E = r"(?<![\w/:])", r"(?![\w/])"  # word bounds that also keep 12/01 and 23:59 whole
_M = _alt(MONTHS)
DATE_RULES = [
    ("dmy", re.compile(B + r"(\d{1,2})/(\d{1,2})(?:/(\d{4}|\d{2}))?" + E)),
    ("day_month", re.compile(B + r"(?:le\s+)?(\d{1,2})(?:er)?\s+(" + _M + r")\.?(?:\s+(\d{4}))?" + E)),
    ("month_day", re.compile(B + r"(" + _M + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?(?:,?\s+(\d{4}))?" + E)),
    ("weekday", re.compile(B + r"(?:(?:next|this|ce)\s+)?(" + _alt(WEEKDAYS) + r")(?:\s+(?:prochain|next))?" + E)),
    ("relative", re.compile(B + r"(" + _alt(RELATIVE) + r")" + E)),
]
TIME_RULES = [
    re.compile(B + r"(\d{1,2})h(\d{2})?" + E),  # 9h, 14h30
    re.compile(B + r"(\d{1,2}):(\d{2})(?:\s?(am|pm))?" + E),  # 23:59, 2:30 pm
    re.compile(B + r"(\d{1,2})\s?(am|pm)" + E),  # 9am
]
RANGE_JOIN = re.compile(r"\s*(?:-|–|a|au|to)\s*")
NOTE_PREFIX = re.compile(r"^\s*(?:note|idea|idee)\s*:")
EVENT_WORDS = re.compile(B + r"(exam|examen|ds|test|cours|class|lecture|reunion|meeting|soutenance|seance)" + E)
TODO_WORDS = re.compile(B + r"(due|deadline|rendre|rendu|avant|before|by|tp|todo|to-do|a faire)" + E)
DANGLING = {"le", "on", "at", "a", "au", "by", "pour", "avant", "before", "due", "for"}


def fold(s: str) -> str:
    """Lower case without accents, one character per character, so indexes match the original."""
    return "".join((unicodedata.normalize("NFD", c)[0].lower()[:1] or c) for c in s)


def _module(folded: str, modules: list[str], aliases: dict[str, str]) -> tuple[str, tuple[int, int]] | None:
    keys = {fold(m): m for m in modules}
    keys.update({fold(a): m for a, m in aliases.items() if m in modules and fold(a) not in keys})
    best = None
    for key, module in keys.items():
        for m in re.finditer(B + re.escape(key) + E, folded):
            if best is None or len(key) > best[2] or (len(key) == best[2] and m.start() < best[1][0]):
                best = (module, m.span(), len(key))
    return (best[0], best[1]) if best else None


def _year(y: str | None) -> int | None:
    return None if y is None else int(y) + (2000 if len(y) == 2 else 0)


def _on_or_after(today: date, month: int, day: int, year: int | None) -> date:
    if year is not None:
        return date(year, month, day)
    d = date(today.year, month, day)
    return d if d >= today else date(today.year + 1, month, day)


def _date(folded: str, today: date) -> tuple[date, tuple[int, int]] | None:
    for kind, rule in DATE_RULES:
        for m in rule.finditer(folded):
            g = m.groups()
            try:
                if kind == "dmy":
                    d = _on_or_after(today, int(g[1]), int(g[0]), _year(g[2]))
                elif kind == "day_month":
                    d = _on_or_after(today, MONTHS[g[1]], int(g[0]), _year(g[2]))
                elif kind == "month_day":
                    d = _on_or_after(today, MONTHS[g[0]], int(g[1]), _year(g[2]))
                elif kind == "weekday":
                    d = today + timedelta(days=(WEEKDAYS[g[0]] - today.weekday()) % 7)
                else:
                    d = today + timedelta(days=RELATIVE[g[0]])
            except ValueError:  # 31/02: not a date, keep looking
                continue
            return d, m.span()
    return None


def _times(folded: str) -> list[tuple[time, tuple[int, int]]]:
    found = []
    for rule in TIME_RULES:
        for m in rule.finditer(folded):
            g = list(m.groups())
            hour = int(g[0])
            minute = int(g[1]) if len(g) > 1 and g[1] and g[1].isdigit() else 0
            ampm = next((x for x in g[1:] if x in ("am", "pm")), None)
            if ampm == "pm" and hour < 12:
                hour += 12
            elif ampm == "am" and hour == 12:
                hour = 0
            if hour < 24 and minute < 60 and not any(s[0] <= m.start() < s[1] for _, s in found):
                found.append((time(hour, minute), m.span()))
    return sorted(found, key=lambda t: t[1][0])


def _title(text: str, cut: list[tuple[int, int]]) -> str:
    keep = [c for i, c in enumerate(text) if not any(a <= i < b for a, b in cut)]
    words = "".join(keep).split()
    while words and fold(words[-1]).strip(",;:-–") in DANGLING | {""}:
        words.pop()
    title = " ".join(words).strip(" ,;:-–")
    return title or text.strip()


def parse_line(text: str, *, now: datetime, modules: list[str], course: str | None = None,
               aliases: dict[str, str] | None = None) -> dict:
    """`now` must be timezone-aware: dates are resolved and returned in its zone."""
    folded = fold(text)
    matched: list[dict] = []

    mod = _module(folded, modules, ALIASES | (aliases or {}))
    if mod:
        course = mod[0]
        matched.append({"start": mod[1][0], "end": mod[1][1], "role": "course"})

    if NOTE_PREFIX.match(folded):
        return {"kind": "note", "title": text.strip(), "course": course, "starts_at": None, "ends_at": None,
                "all_day": False, "matched": matched}

    today = now.date()
    found_date = _date(folded, today)
    times = _times(folded)
    if found_date:  # a time overlapping the date span isn't a time
        a, b = found_date[1]
        times = [t for t in times if t[1][1] <= a or t[1][0] >= b]
    start_t, end_t, time_spans = None, None, []
    if times:
        start_t, time_spans = times[0][0], [times[0][1]]
        if len(times) > 1 and RANGE_JOIN.fullmatch(folded[times[0][1][1]:times[1][1][0]]):
            end_t = times[1][0]
            time_spans = [(times[0][1][0], times[1][1][1])]

    event_word = EVENT_WORDS.search(folded)
    todo_word = TODO_WORDS.search(folded)
    dated = found_date is not None or start_t is not None
    if dated:
        kind, word = ("event", event_word) if event_word else ("todo", todo_word)
    else:
        kind, word = ("todo", todo_word) if todo_word else ("note", None)
    if word:
        matched.append({"start": word.start(1), "end": word.end(1), "role": "kind"})

    starts_at = ends_at = None
    all_day = False
    if dated:
        day = found_date[0] if found_date else today
        if found_date is None and start_t is not None and start_t <= now.time().replace(tzinfo=None):
            day = today + timedelta(days=1)  # a time with no date that has passed today means tomorrow
        tz = now.tzinfo
        if start_t is not None:
            starts_at = datetime.combine(day, start_t, tzinfo=tz)
            if kind == "event" and end_t is not None and end_t > start_t:
                ends_at = datetime.combine(day, end_t, tzinfo=tz)
        elif kind == "todo":
            starts_at = datetime.combine(day, time(23, 59), tzinfo=tz)
        else:
            starts_at, all_day = datetime.combine(day, time(0, 0), tzinfo=tz), True
        if found_date:
            matched.append({"start": found_date[1][0], "end": found_date[1][1], "role": "date"})
        matched += [{"start": a, "end": b, "role": "time"} for a, b in time_spans]

    cut = ([found_date[1]] if found_date else []) + time_spans
    return {"kind": kind, "title": _title(text, cut), "course": course,
            "starts_at": starts_at.isoformat() if starts_at else None,
            "ends_at": ends_at.isoformat() if ends_at else None, "all_day": all_day,
            "matched": sorted(matched, key=lambda m: m["start"])}

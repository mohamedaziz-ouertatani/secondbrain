"""The one-line parser: a fixed now (Tuesday 29 Sep 2026, 13:00 in Tunis) and the real module list."""

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from app.planner.parse import fold, parse_line

TZ = ZoneInfo("Africa/Tunis")
NOW = datetime(2026, 9, 29, 13, 0, tzinfo=TZ)
MODULES = ["AWS Fundamentals", "Advanced Data Science project", "Advanced Deep Learning", "Big Data Analytics",
           "CSR", "Certification en Blockchain", "DEVOPS", "Optimization for ML", "Personnal Skills A",
           "Personnal Skills F", "Probability 2", "SDG"]


def at(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=TZ).isoformat()


CASES = [
    # text, drawer, kind, course, starts_at, ends_at, all_day, title
    ("DEVOPS TP due fri 23:59", None, "todo", "DEVOPS", at(2026, 10, 2, 23, 59), None, False, "DEVOPS TP"),
    ("exam Probability 2 12/01 9h", None, "event", "Probability 2", at(2027, 1, 12, 9), None, False,
     "exam Probability 2"),
    ("réviser proba série 3 avant jeudi", None, "todo", "Probability 2", at(2026, 10, 1, 23, 59), None, False,
     "réviser proba série 3"),
    ("rendre le rapport CSR le 18 oct", None, "todo", "CSR", at(2026, 10, 18, 23, 59), None, False,
     "rendre le rapport CSR"),
    ("idea: use MLflow for the DS project", None, "note", "Advanced Data Science project", None, None, False,
     "idea: use MLflow for the DS project"),
    ("cours optim demain 9h-11h", None, "event", "Optimization for ML", at(2026, 9, 30, 9), at(2026, 9, 30, 11),
     False, "cours optim"),
    ("DS proba 2 lundi 14h30", None, "event", "Probability 2", at(2026, 10, 5, 14, 30), None, False, "DS proba 2"),
    ("meeting 3 october", None, "event", None, at(2026, 10, 3), None, True, "meeting"),
    ("deadline 15/10", None, "todo", None, at(2026, 10, 15, 23, 59), None, False, "deadline"),
    ("submit report tomorrow", None, "todo", None, at(2026, 9, 30, 23, 59), None, False, "submit report"),
    ("exam 12 janvier", None, "event", None, at(2027, 1, 12), None, True, "exam"),
    ("TP big data vendredi prochain", None, "todo", "Big Data Analytics", at(2026, 10, 2, 23, 59), None, False,
     "TP big data"),
    ("buy printer ink", None, "note", None, None, None, False, "buy printer ink"),
    ("todo: email the supervisor", None, "todo", None, None, None, False, "todo: email the supervisor"),
    ("check the slides", "DEVOPS", "note", "DEVOPS", None, None, False, "check the slides"),
    ("quiz CSR fri", "DEVOPS", "todo", "CSR", at(2026, 10, 2, 23, 59), None, False, "quiz CSR"),
    ("exam today 14h", None, "event", None, at(2026, 9, 29, 14), None, False, "exam"),
    ("call at 9am", None, "todo", None, at(2026, 9, 30, 9), None, False, "call"),
    ("pay rent 31/02", None, "note", None, None, None, False, "pay rent 31/02"),
    ("réunion mardi 10h à 12h", None, "event", None, at(2026, 9, 29, 10), at(2026, 9, 29, 12), False, "réunion"),
    ("12/01/2027", None, "todo", None, at(2027, 1, 12, 23, 59), None, False, "12/01/2027"),
    ("Rendre TP DevOps Vendredi 23h59", None, "todo", "DEVOPS", at(2026, 10, 2, 23, 59), None, False,
     "Rendre TP DevOps"),
    ("CH3 exercises by 5/10", None, "todo", None, at(2026, 10, 5, 23, 59), None, False, "CH3 exercises"),
    ("exam SDG october 20th 2:30 pm", None, "event", "SDG", at(2026, 10, 20, 14, 30), None, False, "exam SDG"),
    ("séance soutenance le 1er décembre", None, "event", None, at(2026, 12, 1), None, True, "séance soutenance"),
]


@pytest.mark.parametrize("text,drawer,kind,course,starts,ends,all_day,title", CASES, ids=[c[0] for c in CASES])
def test_parse_line(text, drawer, kind, course, starts, ends, all_day, title):
    d = parse_line(text, now=NOW, modules=MODULES, course=drawer)
    assert (d["kind"], d["course"], d["starts_at"], d["ends_at"], d["all_day"], d["title"]) == (
        kind, course, starts, ends, all_day, title)


def test_matched_spans_point_into_the_original_text():
    text = "DS proba 2 lundi 14h30"
    d = parse_line(text, now=NOW, modules=MODULES)
    assert [(text[m["start"]:m["end"]], m["role"]) for m in d["matched"]] == [
        ("DS", "kind"), ("proba 2", "course"), ("lundi", "date"), ("14h30", "time")]


def test_config_aliases_and_aliases_to_missing_modules():
    d = parse_line("ml homework fri", now=NOW, modules=MODULES, aliases={"ml": "Optimization for ML"})
    assert d["course"] == "Optimization for ML"
    d = parse_line("big data lab fri", now=NOW, modules=["DEVOPS"])
    assert d["course"] is None  # the alias points at a module that isn't in the inbox


def test_fold_keeps_length():
    s = "Réunion à l'amphi, Été ÉCOLE"
    assert len(fold(s)) == len(s) and fold(s) == "reunion a l'amphi, ete ecole"

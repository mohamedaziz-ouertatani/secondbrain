"""Per-module tag vocabulary. The model proposes raw tags per file; each pass maps new raw tags onto canonical
tags by bge-m3 similarity (tag_aliases), then rebuilds document_tags. Your renames, merges and deletes are
aliases and user_named flags, so later passes keep them.
"""

from collections import Counter

import numpy as np

from ..config import get_settings
from ..db import get_pool
from ..llm import ollama

MAX_NAME = 40
_IN_COURSE = "course IS NOT DISTINCT FROM %(c)s::text"


class Clash(ValueError):
    pass


def normalise(name: str) -> str:
    return " ".join(name.lower().split())


def relink(conn, course: str | None) -> None:
    """document_tags for the module, from each document's raw tags and the aliases."""
    conn.execute(
        """DELETE FROM document_tags dt USING documents d
           WHERE dt.document_id = d.id AND d.course IS NOT DISTINCT FROM %(c)s::text""", {"c": course})
    conn.execute(
        """INSERT INTO document_tags (document_id, tag_id)
           SELECT DISTINCT d.id, a.tag_id
           FROM documents d
           CROSS JOIN LATERAL jsonb_array_elements_text(d.raw_tags) AS r(raw)
           JOIN tag_aliases a ON a.raw = r.raw AND a.course IS NOT DISTINCT FROM d.course
           WHERE d.course IS NOT DISTINCT FROM %(c)s::text AND d.enrich_status = 'ok' AND a.tag_id IS NOT NULL""",
        {"c": course})


def run(course: str | None, embed=None) -> dict:
    embed = embed or ollama.embed
    threshold = get_settings().tag_merge_threshold
    with get_pool().connection() as conn, conn.transaction():
        freq: Counter = Counter()
        for r in conn.execute(
            f"SELECT raw_tags FROM documents WHERE {_IN_COURSE} AND enrich_status = 'ok' AND raw_tags IS NOT NULL",
            {"c": course},
        ):
            freq.update(set(r["raw_tags"]))
        aliased = {r["raw"] for r in conn.execute(f"SELECT raw FROM tag_aliases WHERE {_IN_COURSE}", {"c": course})}
        new = sorted((t for t in freq if t not in aliased), key=lambda t: (-freq[t], t))
        created = 0
        if new:
            tags = conn.execute(f"SELECT id, name FROM tags WHERE {_IN_COURSE} ORDER BY id", {"c": course}).fetchall()
            vectors = embed([t["name"] for t in tags] + new)
            known = [(t["id"], np.asarray(v)) for t, v in zip(tags, vectors[: len(tags)], strict=True)]
            for raw, v in zip(new, vectors[len(tags):], strict=True):
                v = np.asarray(v)
                best = max(known, key=lambda k: float(np.dot(k[1], v)), default=None)
                if best is not None and float(np.dot(best[1], v)) >= threshold:
                    tag_id = best[0]
                else:
                    row = conn.execute(
                        "INSERT INTO tags (course, name) VALUES (%s, %s) ON CONFLICT DO NOTHING RETURNING id",
                        (course, raw)).fetchone()
                    tag_id = row["id"] if row else conn.execute(
                        f"SELECT id FROM tags WHERE {_IN_COURSE} AND name = %(n)s", {"c": course, "n": raw}
                    ).fetchone()["id"]
                    created += 1 if row else 0
                    known.append((tag_id, v))
                conn.execute("INSERT INTO tag_aliases (course, raw, tag_id) VALUES (%s, %s, %s)", (course, raw, tag_id))
        relink(conn, course)
        removed = conn.execute(
            f"""DELETE FROM tags t WHERE {_IN_COURSE} AND NOT user_named
                AND NOT EXISTS (SELECT 1 FROM document_tags dt WHERE dt.tag_id = t.id)""", {"c": course}
        ).rowcount
    return {"new_raw": len(new), "new_tags": created, "removed": removed}


def list_tags(course: str | None = None, all_courses: bool = True) -> list[dict]:
    with get_pool().connection() as conn:
        return conn.execute(
            f"""SELECT t.id, t.course, t.name, t.user_named,
                       (SELECT count(*) FROM document_tags dt WHERE dt.tag_id = t.id) AS count,
                       COALESCE((SELECT jsonb_agg(a.raw ORDER BY a.raw) FROM tag_aliases a
                                 WHERE a.tag_id = t.id AND a.raw <> t.name), '[]') AS raws
                FROM tags t WHERE %(all)s OR t.{_IN_COURSE}
                ORDER BY t.course NULLS LAST, count DESC, t.name""",
            {"all": all_courses, "c": course},
        ).fetchall()


def document_tags(doc_id: int) -> list[dict]:
    with get_pool().connection() as conn:
        return conn.execute(
            """SELECT t.id, t.name FROM document_tags dt JOIN tags t ON t.id = dt.tag_id
               WHERE dt.document_id = %s ORDER BY t.name""", (doc_id,)).fetchall()


def _tag(conn, tag_id: int) -> dict | None:
    return conn.execute("SELECT id, course, name FROM tags WHERE id = %s", (tag_id,)).fetchone()


def rename(tag_id: int, name: str) -> dict | None:
    name = normalise(name)
    if not name or len(name) > MAX_NAME:
        raise ValueError(f"a tag name is 1 to {MAX_NAME} characters")
    with get_pool().connection() as conn, conn.transaction():
        tag = _tag(conn, tag_id)
        if tag is None:
            return None
        clash = conn.execute(f"SELECT 1 FROM tags WHERE {_IN_COURSE} AND name = %(n)s AND id <> %(id)s",
                             {"c": tag["course"], "n": name, "id": tag_id}).fetchone()
        if clash:
            raise Clash(f"this module already has a tag called {name}; merge them instead")
        return conn.execute("UPDATE tags SET name = %s, user_named = true WHERE id = %s RETURNING id, course, name",
                            (name, tag_id)).fetchone()


def merge(src: int, into: int) -> dict | None:
    with get_pool().connection() as conn, conn.transaction():
        a, b = _tag(conn, src), _tag(conn, into)
        if a is None or b is None or src == into:
            return None
        if a["course"] != b["course"]:
            raise ValueError("tags from different modules can't be merged")
        conn.execute("UPDATE tag_aliases SET tag_id = %s WHERE tag_id = %s", (into, src))
        conn.execute("UPDATE tags SET user_named = true WHERE id = %s", (into,))
        conn.execute("DELETE FROM tags WHERE id = %s", (src,))
        relink(conn, b["course"])
        return b


def delete(tag_id: int) -> bool:
    with get_pool().connection() as conn, conn.transaction():
        conn.execute("UPDATE tag_aliases SET tag_id = NULL WHERE tag_id = %s", (tag_id,))  # the raw forms stay dropped
        return conn.execute("DELETE FROM tags WHERE id = %s", (tag_id,)).rowcount > 0

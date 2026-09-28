"""Rebuildable local section index with corpus-level freshness checks."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile

import yaml

from harness.documents import Document, fingerprint, parse, paths, sections
from harness.readiness import ensure_readable
from harness import domains
from harness.retrieval import card

SCHEMA = "2"


def build(root, database, scope="current"):
    publication = ensure_readable(root) if scope == 'current' else None
    database.parent.mkdir(parents=True, exist_ok=True)
    before = fingerprint(root, scope)
    fd, name = tempfile.mkstemp(prefix="index-", suffix=".sqlite", dir=database.parent)
    os.close(fd)
    temporary = Path(name)
    try:
        with closing(sqlite3.connect(temporary)) as db:
            db.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
            db.execute("CREATE TABLE sections (path TEXT, title TEXT, heading TEXT, body TEXT, hash TEXT, card TEXT)")
            owners = set(paths(root, scope))
            if scope == 'current':
                owners.update(domains.paths(root))
            for path in sorted(owners):
                rel = path.relative_to(root).as_posix()
                raw = path.read_bytes()
                if path.suffix != '.md':
                    sha = hashlib.sha256(raw).hexdigest()
                    for heading, body in domains.sections(path, raw):
                        db.execute('INSERT INTO sections VALUES (?,?,?,?,?,?)', (rel, path.stem, heading, body, sha, '{}'))
                    continue
                try:
                    doc = parse(rel, raw)
                except (ValueError, UnicodeError, yaml.YAMLError):
                    if scope == "current":
                        raise
                    # Originals are evidence, not documents required to obey our schema.
                    original = raw.decode("utf-8", errors="replace")
                    doc = Document(rel, original, {}, original, hashlib.sha256(raw).hexdigest())
                title = str(doc.metadata.get("title", path.stem))
                discovery = json.dumps(card(doc), ensure_ascii=False) if scope == "current" else "{}"
                for heading, body in sections(doc.body):
                    db.execute("INSERT INTO sections VALUES (?,?,?,?,?,?)", (rel, title, heading, body, doc.sha256, discovery))
            if fingerprint(root, scope) != before:
                raise ValueError("Corpus changed during indexing; retry after writers finish")
            db.executemany("INSERT INTO meta VALUES (?,?)", [("schema", SCHEMA), ("revision", before), ("scope", scope), ("root", str(root.resolve()))])
            db.commit()
        if scope == 'current':
            ensure_readable(root, publication)
        temporary.replace(database)
    finally:
        temporary.unlink(missing_ok=True)
    return before


def search(root, database, query, scope="current", limit=5, excerpt_chars=900, *, brief=False):
    publication = ensure_readable(root) if scope == 'current' else None
    if not query.strip() or not 1 <= limit <= 50 or not 100 <= excerpt_chars <= 5000:
        raise ValueError("Query must be nonempty; limit 1–50; excerpt_chars 100–5000")
    current = fingerprint(root, scope)
    stale = True
    if database.exists():
        try:
            with closing(sqlite3.connect(database)) as db:
                meta = dict(db.execute("SELECT key,value FROM meta"))
                stale = meta != {"schema": SCHEMA, "revision": current, "scope": scope, "root": str(root.resolve())}
        except sqlite3.DatabaseError:
            stale = True
    if stale:
        current = build(root, database, scope)
    words = query.casefold().split()
    matches = []
    with closing(sqlite3.connect(database)) as db:
        for path, title, heading, body, sha, raw_card in db.execute("SELECT * FROM sections"):
            discovery = json.loads(raw_card)
            hints = discovery.get("retrieval", {})
            terms = " ".join([hints.get("description", ""), hints.get("use_when", ""), *hints.get("aliases", [])])
            fields = [title.casefold(), heading.casefold(), body.casefold(), path.casefold(), terms.casefold()]
            if not all(any(word in field for field in fields) for word in words):
                continue
            score = sum(sum(weight for field, weight in zip(fields, (5, 4, 1, 2, 6)) if word in field) for word in words)
            position = next((fields[2].find(word) for word in words if word in fields[2]), 0)
            start = max(0, position - 150)
            excerpt = body[start:start + excerpt_chars]
            hit = {"path": path, "heading": heading, "sha256": sha, "score": score, **discovery}
            if not brief:
                hit.update(excerpt=excerpt, truncated=len(excerpt) < len(body))
            matches.append(hit)
    matches.sort(key=lambda hit: (-hit["score"], hit["path"], hit["heading"]))
    if fingerprint(root, scope) != current:
        raise ValueError("Corpus changed during query; retry")
    if scope == 'current':
        ensure_readable(root, publication)
    owners = {}
    for hit in matches:
        owners.setdefault(hit["path"], hit)
    return {"scope": scope, "revision": current, "rebuilt": stale,
            "total_hits": len(matches), "total_documents": len(owners),
            "hits": list(owners.values())[:limit]}

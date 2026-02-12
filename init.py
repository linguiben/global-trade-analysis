"""Deploy-time database initializer.

Behavior:
- Reads init_db.sql (schema-only DDL).
- Executes statements one-by-one.
- Skips "already exists"-type errors so it can be run repeatedly.

Usage (inside container / host with env):
  python init.py

Requires:
- DATABASE_URL env var (SQLAlchemy-style URL works; we convert to psycopg conninfo)
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import psycopg


SKIP_PATTERNS = [
    # common idempotency cases
    "already exists",
    "duplicate key value violates unique constraint",
    "relation .* already exists",
    "type .* already exists",
    "schema .* already exists",
    "constraint .* already exists",
    "multiple primary keys for table",
    "index .* already exists",
    "does not exist, skipping",  # e.g. DROP ... IF EXISTS in dumps
]


def _should_skip_error(msg: str) -> bool:
    s = msg or ""
    return any(re.search(pat, s, flags=re.IGNORECASE) for pat in SKIP_PATTERNS)


def _read_sql(path: Path) -> str:
    raw = path.read_text(encoding="utf-8", errors="ignore")
    # Remove pg_dump \restrict/\unrestrict lines for safety
    raw = re.sub(r"^\\restrict\s+.*$", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"^\\unrestrict\s+.*$", "", raw, flags=re.MULTILINE)
    # Drop full-line comments. pg_dump comment lines contain semicolons and would
    # otherwise split into invalid SQL fragments (e.g. "Type: TABLE").
    raw = re.sub(r"^\s*--.*$", "", raw, flags=re.MULTILINE)
    return raw


def _split_sql(sql: str) -> list[str]:
    # SQL splitter: handles semicolons outside single/double quotes and dollar-quoted blocks.
    stmts = []
    buf = []
    in_squote = False
    in_dquote = False
    dollar_tag: str | None = None

    i = 0
    n = len(sql)
    while i < n:
        if dollar_tag:
            if sql.startswith(dollar_tag, i):
                buf.append(dollar_tag)
                i += len(dollar_tag)
                dollar_tag = None
                continue
            buf.append(sql[i])
            i += 1
            continue

        # Detect start of dollar-quoted block: $$...$$ or $tag$...$tag$
        if not in_squote and not in_dquote and sql[i] == "$":
            m = re.match(r"^\$(?:[A-Za-z_][A-Za-z0-9_]*)?\$", sql[i:])
            if m:
                tag = m.group(0)
                dollar_tag = tag
                buf.append(tag)
                i += len(tag)
                continue

        ch = sql[i]

        # Handle escaped quote in string literals ('' or "")
        if in_squote and ch == "'" and i + 1 < n and sql[i + 1] == "'":
            buf.append("''")
            i += 2
            continue
        if in_dquote and ch == '"' and i + 1 < n and sql[i + 1] == '"':
            buf.append('""')
            i += 2
            continue

        if ch == "'" and not in_dquote:
            in_squote = not in_squote
        elif ch == '"' and not in_squote:
            in_dquote = not in_dquote

        if ch == ";" and not in_squote and not in_dquote:
            stmt = "".join(buf).strip()
            if stmt:
                stmts.append(stmt)
            buf = []
            i += 1
            continue

        buf.append(ch)
        i += 1

    tail = "".join(buf).strip()
    if tail:
        stmts.append(tail)

    # drop pure comments / SET noise to reduce churn
    cleaned = []
    for s in stmts:
        ss = s.strip()
        if not ss:
            continue
        # keep SET/SELECT pg_catalog.set_config from dump as they are harmless
        cleaned.append(ss)
    return cleaned


def _to_psycopg_url(url: str) -> str:
    # psycopg accepts SQLAlchemy-style "postgresql+psycopg://" but not always;
    # normalize to "postgresql://".
    return url.replace("postgresql+psycopg://", "postgresql://")


def main() -> int:
    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("DATABASE_URL is not set", file=sys.stderr)
        return 2

    sql_path = Path(__file__).with_name("init_db.sql")
    if not sql_path.exists():
        print(f"Missing {sql_path}", file=sys.stderr)
        return 2

    sql = _read_sql(sql_path)
    stmts = _split_sql(sql)

    conninfo = _to_psycopg_url(db_url)
    total = 0
    skipped = 0
    failed = 0

    with psycopg.connect(conninfo, autocommit=True) as conn:
        with conn.cursor() as cur:
            for i, stmt in enumerate(stmts, start=1):
                try:
                    cur.execute(stmt)
                    total += 1
                except Exception as e:  # noqa: BLE001
                    msg = str(e)
                    if _should_skip_error(msg):
                        skipped += 1
                        continue
                    failed += 1
                    print(f"[init.py] Statement {i} failed:\n{stmt}\n---\n{msg}", file=sys.stderr)
                    return 1

    print(f"[init.py] done: executed={total} skipped={skipped} failed={failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

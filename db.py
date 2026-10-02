"""
Postgres (Neon) connection used by every script in this repo.

Connects with DATABASE_URL from the environment or .env, and keeps the
sqlite3-style API the scripts were written against:
  - `?` placeholders
  - rows readable by index or column name (r[0] / r['name'])
  - INSERT OR REPLACE / INSERT OR IGNORE (become ON CONFLICT upserts)

Upserts are buffered and sent in batches, since one round trip per row to a
remote database is far too slow for a full scrape. Buffered rows are flushed
before any other statement runs and on commit(), so reads always see them.
"""
import os, re
from pathlib import Path

import psycopg
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

_INSERT_OR = re.compile(
    r"^\s*INSERT\s+OR\s+(REPLACE|IGNORE)\s+INTO\s+(\w+)\s*\(([^)]*)\)\s*VALUES\s*\(([^)]*)\)\s*$",
    re.I | re.S,
)
_CREATE_TABLE = re.compile(r"^\s*CREATE\s+TABLE", re.I)
_FLUSH_AT = 5000


class Row(tuple):
    """Tuple that can also be indexed by column name, like sqlite3.Row."""
    _index = {}

    def __getitem__(self, key):
        if isinstance(key, str):
            return tuple.__getitem__(self, self._index[key])
        return tuple.__getitem__(self, key)

    def keys(self):
        return list(self._index)


def _row_factory(cursor):
    if not cursor.description:
        return None
    names = [d.name for d in cursor.description]
    cls = type("Row", (Row,), {"_index": {n: i for i, n in enumerate(names)}})
    return lambda values: cls(values)


def _placeholders(sql):
    """Convert sqlite `?` placeholders to psycopg `%s`, leaving quoted text alone."""
    out, quote = [], None
    for ch in sql:
        if quote:
            out.append("%%" if ch == "%" else ch)
            if ch == quote:
                quote = None
        elif ch in ("'", '"'):
            quote = ch
            out.append(ch)
        elif ch == "?":
            out.append("%s")
        elif ch == "%":
            out.append("%%")
        else:
            out.append(ch)
    return "".join(out)


class Connection:
    def __init__(self, url, read_only=False):
        self.raw = psycopg.connect(url, row_factory=_row_factory)
        self.raw.read_only = read_only
        self._pk = {}
        self._buffer = {}  # (sql) -> [params, ...]

    # ── upserts ──────────────────────────────────────────────────────────────
    def _primary_key(self, table):
        if table not in self._pk:
            rows = self.raw.execute("""
                SELECT a.attname FROM pg_index i
                JOIN pg_attribute a ON a.attrelid = i.indrelid AND a.attnum = ANY(i.indkey)
                WHERE i.indrelid = %s::regclass AND i.indisprimary
            """, (table,)).fetchall()
            self._pk[table] = [r[0] for r in rows]
        return self._pk[table]

    def _upsert_sql(self, mode, table, cols):
        cols = [c.strip() for c in cols.split(",")]
        pk = self._primary_key(table)
        sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})"
        updates = [c for c in cols if c not in pk]
        if mode.upper() == "IGNORE" or not updates:
            return sql + " ON CONFLICT DO NOTHING"
        return (sql + f" ON CONFLICT ({', '.join(pk)}) DO UPDATE SET "
                + ", ".join(f"{c} = EXCLUDED.{c}" for c in updates))

    def flush(self):
        buffer, self._buffer = self._buffer, {}
        with self.raw.cursor() as cur:
            for sql, rows in buffer.items():
                cur.executemany(sql, rows)

    # ── sqlite3-compatible API ───────────────────────────────────────────────
    def execute(self, sql, params=()):
        m = _INSERT_OR.match(sql)
        if m:
            key = self._upsert_sql(m.group(1), m.group(2), m.group(3))
            rows = self._buffer.setdefault(key, [])
            rows.append(tuple(params))
            if len(rows) >= _FLUSH_AT:
                self.flush()
            return None
        self.flush()
        if _CREATE_TABLE.match(sql):
            # sqlite REAL is 8-byte; Postgres REAL is 4-byte
            sql = re.sub(r"\bREAL\b", "DOUBLE PRECISION", sql, flags=re.I)
        return self.raw.execute(_placeholders(sql) if params else sql, params or None)

    def executemany(self, sql, seq):
        for params in seq:
            self.execute(sql, params)

    def executescript(self, script):
        for stmt in script.split(";"):
            if stmt.strip():
                self.execute(stmt)

    def commit(self):
        self.flush()
        self.raw.commit()

    def rollback(self):
        self._buffer = {}
        self.raw.rollback()

    def close(self):
        self.raw.close()


def connect(read_only=False):
    """read_only=True for reports and AI tools, so they can never change data."""
    url = os.getenv("DATABASE_URL")
    if not url:
        raise SystemExit("Set DATABASE_URL (Neon connection string) in .env or the environment")
    return Connection(url, read_only=read_only)

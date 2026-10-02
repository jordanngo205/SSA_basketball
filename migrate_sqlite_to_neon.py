#!/usr/bin/env python3
"""
One-time copy of data/db/ssa.db (SQLite) into the Neon Postgres database.

Recreates every table with the same columns and primary keys, bulk-loads the
rows, rebuilds the indexes, then checks row counts match.

Usage:
    python migrate_sqlite_to_neon.py                 # refuses if tables already have data
    python migrate_sqlite_to_neon.py --replace       # drop and reload existing tables
    python migrate_sqlite_to_neon.py --sqlite other.db
"""
import argparse, os, re, sqlite3, sys
from pathlib import Path

import db

TYPES = {"TEXT": "TEXT", "REAL": "DOUBLE PRECISION", "INTEGER": "BIGINT"}


def pg_create(conn_sq, table):
    cols = conn_sq.execute(f'PRAGMA table_info("{table}")').fetchall()
    pk = [c[1] for c in sorted(cols, key=lambda c: c[5]) if c[5]]
    defs = []
    for _, name, typ, notnull, default, _ in cols:
        d = f"{name} {TYPES.get(typ.upper(), 'TEXT')}"
        if notnull or name in pk:
            d += " NOT NULL"
        if default is not None:
            d += f" DEFAULT {default}"
        defs.append(d)
    if pk:
        defs.append(f"PRIMARY KEY ({', '.join(pk)})")
    return f"CREATE TABLE {table} (\n    " + ",\n    ".join(defs) + "\n)", [c[1] for c in cols]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sqlite", default=str(Path(__file__).parent / "data" / "db" / "ssa.db"))
    ap.add_argument("--replace", action="store_true")
    args = ap.parse_args()

    sq = sqlite3.connect(args.sqlite)
    pg = db.connect().raw
    tables = [r[0] for r in sq.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    indexes = [r[0] for r in sq.execute(
        "SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL")]

    existing = {r[0] for r in pg.execute(
        "SELECT tablename FROM pg_tables WHERE schemaname = 'public'").fetchall()}
    clash = [t for t in tables if t in existing]
    if clash and not args.replace:
        sys.exit(f"Tables already exist in Neon: {', '.join(clash)}\nRe-run with --replace to drop and reload them.")

    for t in tables:
        create, cols = pg_create(sq, t)
        pg.execute(f"DROP TABLE IF EXISTS {t}")
        pg.execute(create)
        n = 0
        with pg.cursor().copy(f"COPY {t} ({', '.join(cols)}) FROM STDIN") as copy:
            for row in sq.execute(f'SELECT {", ".join(cols)} FROM "{t}"'):
                copy.write_row(row)
                n += 1
        print(f"  {t:32s} {n:>8,} rows")

    for sql in indexes:
        pg.execute(re.sub(r"^CREATE INDEX", "CREATE INDEX IF NOT EXISTS", sql.strip(), flags=re.I))
    pg.commit()

    print("\nVerifying row counts...")
    bad = 0
    for t in tables:
        a = sq.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
        b = pg.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        if a != b:
            bad += 1
            print(f"  MISMATCH {t}: sqlite={a} neon={b}")
    print("  All tables match." if not bad else f"  {bad} table(s) differ.")
    size = pg.execute("SELECT pg_size_pretty(pg_database_size(current_database()))").fetchone()[0]
    print(f"  Neon database size: {size}")
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()

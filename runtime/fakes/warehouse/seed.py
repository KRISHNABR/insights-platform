"""Seed the stub warehouse.

A SQLite file standing in for the analytics warehouse. The brief invites fakes; what
matters is that the SHAPE is right - three tables, one of them genuinely sensitive, one
of them deliberately unused so the test suite can prove entitlement is enforced rather
than assumed.

    python runtime/fakes/warehouse/seed.py [path]
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

DEFAULT = Path(__file__).with_name("warehouse.db")

HEADCOUNT = [
    ("2026-09", "Engineering", 184),
    ("2026-09", "Sales", 96),
    ("2026-09", "People Ops", 12),
    ("2026-08", "Engineering", 179),
    ("2026-08", "Sales", 94),
    ("2026-08", "People Ops", 12),
]

# The most sensitive thing the platform holds. Individual rows, real field names -
# the masking rules and the telemetry assertions in the catalog are written against these.
COMPENSATION = [
    (1, "Krishna Murari", "People Ops", 94000, 8.0),
    (2, "Vidya Raman", "People Analytics", 112000, 12.0),
    (3, "Lokesh Iyer", "People Analytics", 101500, 10.0),
    (4, "Kishore Nambiar", "Engineering", 138000, 15.0),
]

PIPELINE = [
    ("EMEA", "Acme Corp", 240000, "negotiation"),
    ("AMER", "Globex", 95000, "qualified"),
]


def seed(path: Path = DEFAULT) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    with conn:
        conn.executescript(
            """
            DROP TABLE IF EXISTS hr_headcount;
            DROP TABLE IF EXISTS hr_compensation;
            DROP TABLE IF EXISTS sales_pipeline;

            CREATE TABLE hr_headcount   (month TEXT, dept TEXT, headcount INTEGER);
            CREATE TABLE hr_compensation(employee_id INTEGER, employee_name TEXT,
                                         dept TEXT, base_salary INTEGER, bonus_pct REAL);
            CREATE TABLE sales_pipeline (region TEXT, account TEXT, value INTEGER, stage TEXT);
            """
        )
        conn.executemany("INSERT INTO hr_headcount VALUES (?,?,?)", HEADCOUNT)
        conn.executemany("INSERT INTO hr_compensation VALUES (?,?,?,?,?)", COMPENSATION)
        conn.executemany("INSERT INTO sales_pipeline VALUES (?,?,?,?)", PIPELINE)
    conn.close()
    return path


if __name__ == "__main__":
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT
    print(f"seeded {seed(target)}")

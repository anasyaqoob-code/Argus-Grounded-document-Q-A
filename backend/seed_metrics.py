"""Seed synthetic query_metrics rows for chart development.

Writes to a SEPARATE database file (app_seed.db by default) so your
real app.db is never touched. Point the backend at it temporarily:

    # In backend/app/storage.py, line ~48, temporarily change:
    DB_PATH = DATA_DIR / "app.db"
    # to:
    DB_PATH = DATA_DIR / "app_seed.db"

Restart uvicorn, reload /admin, look at the charts.

When done, switch DB_PATH back to app.db and delete the seed file:

    rm backend/app/data/app_seed.db

Or, if you WANT the seed data in your real DB (for a demo, or because
you don't care about the existing metrics), pass --real:

    python -m app.seed_metrics --real

Run from the backend/ directory:

    source venv/bin/activate
    python -m app.seed_metrics
"""

from __future__ import annotations

import argparse
import math
import random
import sqlite3
import time
from pathlib import Path

THIS_DIR = Path(__file__).resolve().parent
DATA_DIR = THIS_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_SEED_DB = DATA_DIR / "app_seed.db"
REAL_DB = DATA_DIR / "app.db"

DAYS = 30
QUERIES_PER_DAY_MIN = 4
QUERIES_PER_DAY_MAX = 14


def _schema(conn: sqlite3.Connection) -> None:
    """Create the tables the seeder writes to. Idempotent."""
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS query_metrics (
            message_id INTEGER PRIMARY KEY,
            user_id TEXT NOT NULL,
            session_id TEXT NOT NULL,
            created_at REAL NOT NULL,
            faithfulness REAL,
            context_precision REAL,
            chunks_retrieved INTEGER,
            abstained INTEGER NOT NULL DEFAULT 0,
            verification_passed INTEGER,
            latency_ms REAL,
            composite REAL
        );
        CREATE INDEX IF NOT EXISTS idx_query_metrics_time
            ON query_metrics(created_at);
        CREATE INDEX IF NOT EXISTS idx_query_metrics_user
            ON query_metrics(user_id, created_at);

        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            created_at REAL NOT NULL,
            updated_at REAL NOT NULL,
            user_id TEXT NOT NULL DEFAULT 'anon'
        );

        CREATE TABLE IF NOT EXISTS auth_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT NOT NULL,
            event TEXT NOT NULL,
            created_at REAL NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_auth_events_time
            ON auth_events(created_at);

        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            metadata_json TEXT,
            created_at REAL NOT NULL
        );
        """
    )


def _clamp01(v: float) -> float:
    return max(0.0, min(1.0, v))


def _wiggle(day: int, seed: float, scale: float = 0.14) -> float:
    """Deterministic but busy-looking oscillation. Two frequencies so
    neighbouring days don't move in lockstep. Range: roughly ±scale.
    """
    a = math.sin((day + seed) * 0.9) * 0.6
    b = math.sin((day * 1.7) + seed * 2.1) * 0.4
    return (a + b) * scale


def _make_metric_rows(
    days: int,
    rng: random.Random,
) -> list[tuple]:
    """Build one tuple per (day, query) matching query_metrics columns."""
    now = time.time()
    rows: list[tuple] = []
    next_id = 1

    for day_offset in range(days):
        # day_offset 0 = oldest, days-1 = today
        day_start = now - (days - 1 - day_offset) * 86400
        n = rng.randint(QUERIES_PER_DAY_MIN, QUERIES_PER_DAY_MAX)

        # Base levels that drift over the window so the lines actually
        # trend somewhere — otherwise everything is flat noise.
        progress = day_offset / max(1, days - 1)
        base_faith = 0.66 + 0.12 * progress
        base_prec = 0.58 + 0.14 * progress
        base_comp = 0.62 + 0.16 * progress

        for i in range(n):
            ts = day_start + rng.uniform(0, 86400 * 0.98)

            faithfulness = _clamp01(
                base_faith + _wiggle(day_offset, 0.3) + rng.uniform(-0.05, 0.05)
            )
            precision = _clamp01(
                base_prec + _wiggle(day_offset, 1.7) + rng.uniform(-0.06, 0.06)
            )
            composite = _clamp01(
                base_comp + _wiggle(day_offset, 3.1) + rng.uniform(-0.05, 0.05)
            )

            # Abstention: mostly 0, occasionally 1 — enough to make the
            # rate line wiggle without being dominant.
            abstained = 1 if rng.random() < 0.08 else 0

            # Verification: mostly pass (1), sometimes fail (0), rarely
            # null (not run).
            r = rng.random()
            if r < 0.80:
                verification = 1
            elif r < 0.94:
                verification = 0
            else:
                verification = None

            # Latency: 800 ms – 6500 ms, with a slow day-scale wave so
            # the latency line isn't uniform noise.
            latency_ms = 2600.0 + _wiggle(day_offset, 5.0, scale=1400.0) + rng.uniform(
                -600.0, 900.0
            )
            latency_ms = max(400.0, latency_ms)

            rows.append(
                (
                    next_id,
                    "seed_user",
                    f"seed_session_{day_offset}",
                    ts,
                    round(faithfulness, 4),
                    round(precision, 4),
                    rng.randint(2, 8),  # chunks_retrieved
                    abstained,
                    verification,
                    round(latency_ms, 1),
                    round(composite, 4),
                )
            )
            next_id += 1

    return rows


def _make_auth_events(days: int, rng: random.Random) -> list[tuple]:
    """Signup/login events so the Signups & logins chart also has data."""
    now = time.time()
    out: list[tuple] = []
    for day_offset in range(days):
        day_start = now - (days - 1 - day_offset) * 86400
        # A ramp of activity — starts quiet, ends busier.
        ramp = 0.3 + 0.7 * (day_offset / max(1, days - 1))
        n_signup = rng.randint(0, max(1, int(4 * ramp)))
        n_login = rng.randint(1, max(2, int(9 * ramp)))
        for _ in range(n_signup):
            out.append(
                ("seed_user", "signup", day_start + rng.uniform(0, 86400))
            )
        for _ in range(n_login):
            out.append(
                ("seed_user", "login", day_start + rng.uniform(0, 86400))
            )
    return out


def _make_sessions(days: int, rng: random.Random) -> list[tuple]:
    """A session per day, so sessions_by_day() has something to count."""
    now = time.time()
    out: list[tuple] = []
    for day_offset in range(days):
        day_start = now - (days - 1 - day_offset) * 86400
        n = rng.randint(1, 6)
        for i in range(n):
            sid = f"seed_{day_offset}_{i}"
            ts = day_start + rng.uniform(0, 86400)
            out.append((sid, f"Seeded session {day_offset}-{i}", ts, ts, "seed_user"))
    return out


def seed(db_path: Path, days: int = DAYS, wipe: bool = True) -> None:
    rng = random.Random(42)  # deterministic — same output every run

    conn = sqlite3.connect(db_path)
    try:
        _schema(conn)

        if wipe:
            print(f"Wiping existing seed rows from {db_path.name}…")
            conn.execute("DELETE FROM query_metrics WHERE user_id = 'seed_user'")
            conn.execute("DELETE FROM auth_events WHERE user_id = 'seed_user'")
            conn.execute("DELETE FROM sessions WHERE user_id = 'seed_user'")
            conn.execute("DELETE FROM messages WHERE session_id LIKE 'seed_%'")

        metric_rows = _make_metric_rows(days, rng)
        conn.executemany(
            """
            INSERT OR REPLACE INTO query_metrics (
                message_id, user_id, session_id, created_at,
                faithfulness, context_precision, chunks_retrieved,
                abstained, verification_passed, latency_ms, composite
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            metric_rows,
        )

        auth_rows = _make_auth_events(days, rng)
        conn.executemany(
            "INSERT INTO auth_events (user_id, event, created_at) VALUES (?, ?, ?)",
            auth_rows,
        )

        session_rows = _make_sessions(days, rng)
        conn.executemany(
            "INSERT OR REPLACE INTO sessions (id, title, created_at, updated_at, user_id) "
            "VALUES (?, ?, ?, ?, ?)",
            session_rows,
        )

        conn.commit()
    finally:
        conn.close()

    print(f"Seeded {len(metric_rows)} query_metrics rows across {days} days.")
    print(f"Seeded {len(auth_rows)} auth events.")
    print(f"Seeded {len(session_rows)} sessions.")
    print(f"Database: {db_path}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--real",
        action="store_true",
        help="Seed the REAL app.db (app/data/app.db) instead of the "
             "separate seed DB. Existing seed rows are wiped first; "
             "your real (non-seed) metrics are untouched.",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DAYS,
        help=f"How many days of history to generate (default {DAYS}).",
    )
    args = parser.parse_args()

    target = REAL_DB if args.real else DEFAULT_SEED_DB

    if args.real:
        print("!! Seeding the REAL database.")
        print(f"!! Target: {target}")
        print("!! Your non-seed rows are safe, but this is not reversible")
        print("!! without manually deleting WHERE user_id='seed_user'.")
        resp = input("Continue? [y/N] ").strip().lower()
        if resp != "y":
            print("Aborted.")
            return

    seed(target, days=args.days, wipe=True)


if __name__ == "__main__":
    main()
"""SQLite storage for Daylight.

The database file is the single source of truth. Nothing that matters lives in
process memory: every read goes to SQLite, every write is committed before the
HTTP response is sent, so restarting the process never loses a goal, a check-in
or a daily card.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from datetime import date, datetime, timedelta

SCHEMA = """
CREATE TABLE IF NOT EXISTS goals (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    day        TEXT NOT NULL,
    text       TEXT NOT NULL,
    next_step  TEXT NOT NULL DEFAULT '',
    done       INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    done_at    TEXT
);
CREATE TABLE IF NOT EXISTS checkins (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    day        TEXT NOT NULL,
    did        TEXT NOT NULL,
    learned    TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS cards (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    day        TEXT NOT NULL,
    body       TEXT NOT NULL,
    mode       TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (
    key   TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_goals_day ON goals(day);
CREATE INDEX IF NOT EXISTS idx_checkins_day ON checkins(day);
CREATE INDEX IF NOT EXISTS idx_cards_day ON cards(day);
"""

PLANT_STAGES = ["seed", "sprout", "leaf", "bud", "bloom"]


def _now() -> str:
    return datetime.now().replace(microsecond=0).isoformat()


class Store:
    """Thin, explicit wrapper around one SQLite file."""

    def __init__(self, data_dir: str) -> None:
        self.data_dir = os.path.abspath(data_dir)
        os.makedirs(self.data_dir, exist_ok=True)
        self.db_path = os.path.join(self.data_dir, "daylight.db")
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.db_path, timeout=10, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA foreign_keys=ON")
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    # ---------------------------------------------------------------- helpers

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    @staticmethod
    def today() -> str:
        return date.today().isoformat()

    def _touch(self) -> None:
        self._conn.execute(
            "INSERT INTO meta(key, value) VALUES('last_write', ?) "
            "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
            (_now(),),
        )

    def last_write(self) -> str:
        row = self._conn.execute("SELECT value FROM meta WHERE key='last_write'").fetchone()
        return row["value"] if row else ""

    def counts(self) -> dict:
        one = lambda sql: self._conn.execute(sql).fetchone()[0]  # noqa: E731
        return {
            "goals": one("SELECT COUNT(*) FROM goals"),
            "checkins": one("SELECT COUNT(*) FROM checkins"),
            "cards": one("SELECT COUNT(*) FROM cards"),
        }

    # ---------------------------------------------------------------- writes

    def add_goal(self, text: str, next_step: str = "", day: str | None = None) -> int:
        day = day or self.today()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO goals(day, text, next_step, created_at) VALUES(?,?,?,?)",
                (day, text, next_step, _now()),
            )
            self._touch()
            self._conn.commit()
            return int(cur.lastrowid)

    def set_next_step(self, goal_id: int, next_step: str) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE goals SET next_step=? WHERE id=?", (next_step, goal_id)
            )
            self._touch()
            self._conn.commit()
            return cur.rowcount > 0

    def complete_goal(self, goal_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute(
                "UPDATE goals SET done=1, done_at=? WHERE id=? AND done=0",
                (_now(), goal_id),
            )
            self._touch()
            self._conn.commit()
            return cur.rowcount > 0

    def add_checkin(self, did: str, learned: str = "", day: str | None = None) -> int:
        day = day or self.today()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO checkins(day, did, learned, created_at) VALUES(?,?,?,?)",
                (day, did, learned, _now()),
            )
            self._touch()
            self._conn.commit()
            return int(cur.lastrowid)

    def add_card(self, body: str, mode: str, day: str | None = None) -> int:
        day = day or self.today()
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO cards(day, body, mode, created_at) VALUES(?,?,?,?)",
                (day, body, mode, _now()),
            )
            self._touch()
            self._conn.commit()
            return int(cur.lastrowid)

    # ---------------------------------------------------------------- reads

    def goals_for(self, day: str | None = None) -> list:
        day = day or self.today()
        rows = self._conn.execute(
            "SELECT * FROM goals WHERE day=? ORDER BY id", (day,)
        ).fetchall()
        return [dict(r) for r in rows]

    def goal_by_id(self, goal_id: int):
        row = self._conn.execute("SELECT * FROM goals WHERE id=?", (goal_id,)).fetchone()
        return dict(row) if row else None

    def checkins_for(self, day: str | None = None) -> list:
        day = day or self.today()
        rows = self._conn.execute(
            "SELECT * FROM checkins WHERE day=? ORDER BY id", (day,)
        ).fetchall()
        return [dict(r) for r in rows]

    def cards_for(self, day: str | None = None) -> list:
        day = day or self.today()
        rows = self._conn.execute(
            "SELECT * FROM cards WHERE day=? ORDER BY id DESC", (day,)
        ).fetchall()
        return [dict(r) for r in rows]

    def all_days(self, limit: int = 60) -> list:
        """Every day that has at least one goal or check-in, newest first."""
        rows = self._conn.execute(
            "SELECT day FROM ("
            "  SELECT day FROM goals UNION SELECT day FROM checkins"
            ") ORDER BY day DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [r["day"] for r in rows]

    def streak(self, day: str | None = None) -> int:
        """Consecutive days ending today (or yesterday) with a check-in."""
        day = day or self.today()
        days = set(
            r["day"] for r in self._conn.execute("SELECT DISTINCT day FROM checkins").fetchall()
        )
        if not days:
            return 0
        cursor = date.fromisoformat(day)
        if cursor.isoformat() not in days:
            cursor -= timedelta(days=1)
            if cursor.isoformat() not in days:
                return 0
        run = 0
        while cursor.isoformat() in days:
            run += 1
            cursor -= timedelta(days=1)
        return run

    def garden(self, limit: int = 21) -> list:
        """One plant per day, backed by that day's real records."""
        out = []
        for day in self.all_days(limit=limit):
            goals = self.goals_for(day)
            checkins = self.checkins_for(day)
            done = sum(1 for g in goals if g["done"])
            activity = done + len(checkins)
            stage = PLANT_STAGES[min(len(PLANT_STAGES) - 1, activity)]
            out.append(
                {
                    "day": day,
                    "stage": stage,
                    "activity": activity,
                    "goals": goals,
                    "checkins": checkins,
                    "cards": self.cards_for(day),
                }
            )
        return out

    def state(self, connector_configured: bool = False) -> dict:
        day = self.today()
        goals = self.goals_for(day)
        checkins = self.checkins_for(day)
        done = sum(1 for g in goals if g["done"])
        total = len(goals)
        return {
            "today": day,
            "goals": goals,
            "checkins": checkins,
            "cards": self.cards_for(day),
            "progress": {
                "done": done,
                "total": total,
                "percent": round(done / total * 100) if total else 0,
            },
            "streak": self.streak(day),
            "garden": self.garden(),
            "mode": "connector" if connector_configured else "local",
        }

    # ---------------------------------------------------------------- export

    def export_markdown(self) -> str:
        lines = [
            "# Daylight · 向阳 — 我的记录",
            "",
            f"导出时间：{_now()}",
            f"记录天数：{len(self.all_days(limit=10000))} 天 · 连续 {self.streak()} 天",
            "",
            "> 数据来自你的真实记录：目标、行动、经验卡。没有一条是自动编造的。",
            "",
        ]
        for day in self.all_days(limit=10000):
            lines.append(f"## {day}")
            lines.append("")
            goals = self.goals_for(day)
            if goals:
                lines.append("### 小目标")
                for g in goals:
                    mark = "已完成" if g["done"] else "进行中"
                    lines.append(f"- [{mark}] {g['text']}")
                    if g.get("next_step"):
                        lines.append(f"  - 下一步：{g['next_step']}")
                lines.append("")
            checkins = self.checkins_for(day)
            if checkins:
                lines.append("### 行动记录")
                for c in checkins:
                    lines.append(f"- 我做了什么：{c['did']}")
                    if c["learned"]:
                        lines.append(f"  - 我学到：{c['learned']}")
                lines.append("")
            cards = self.cards_for(day)
            if cards:
                lines.append("### 经验卡")
                for c in cards:
                    lines.append(f"（{c['mode']} · {c['created_at']}）")
                    lines.append("")
                    lines.append(c["body"])
                    lines.append("")
            lines.append("")
        if not self.all_days(limit=1):
            lines.append("还没有记录。今天写下一个目标，花园就会长出第一株。")
            lines.append("")
        return "\n".join(lines)

    def health(self) -> dict:
        files = {}
        for suffix in ("", "-wal", "-shm"):
            path = self.db_path + suffix
            if os.path.isfile(path):
                files[suffix or "main"] = os.path.getsize(path)
        return {
            "status": "ok",
            "data_dir": self.data_dir,
            "db_path": self.db_path,
            "db_bytes": sum(files.values()),
            "db_files": files,
            "last_write": self.last_write(),
            "counts": self.counts(),
            "server_time": _now(),
        }

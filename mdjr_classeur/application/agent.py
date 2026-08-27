from __future__ import annotations

import sqlite3
import time
import uuid
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AgentRecord:
    path: str
    size: int
    mtime_ns: int
    state: str
    attempts: int
    last_error: str = ""


class AgentLedger:
    """Journal local de progression pour les traitements volumineux.

    Le registre est indépendant de l’interface. Il permet à l’agent de reprendre
    après une fermeture, une panne ou une perte de connexion sans recommencer les
    fichiers déjà traités.
    """

    def __init__(self, database_path: Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.connection = sqlite3.connect(str(self.database_path), timeout=10.0)
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA synchronous=NORMAL")
        self.connection.execute("PRAGMA busy_timeout=10000")
        self._initialize()

    def _initialize(self) -> None:
        self.connection.execute(
            """CREATE TABLE IF NOT EXISTS agent_jobs (
                path TEXT PRIMARY KEY,
                size INTEGER NOT NULL,
                mtime_ns INTEGER NOT NULL,
                state TEXT NOT NULL,
                attempts INTEGER NOT NULL DEFAULT 0,
                last_error TEXT NOT NULL DEFAULT '',
                target TEXT NOT NULL DEFAULT '',
                updated_at REAL NOT NULL
            )"""
        )
        columns = {row[1] for row in self.connection.execute("PRAGMA table_info(agent_jobs)").fetchall()}
        if "target" not in columns:
            self.connection.execute("ALTER TABLE agent_jobs ADD COLUMN target TEXT NOT NULL DEFAULT ''")
        self.connection.execute("CREATE INDEX IF NOT EXISTS idx_agent_jobs_state ON agent_jobs(state)")
        self.connection.commit()

    @staticmethod
    def signature(path: Path) -> tuple[str, int, int] | None:
        try:
            stat = path.stat()
            return str(path.resolve()), stat.st_size, stat.st_mtime_ns
        except OSError:
            return None

    def needs_processing(self, path: Path) -> bool:
        signature = self.signature(path)
        if signature is None:
            return False
        row = self.connection.execute(
            "SELECT size, mtime_ns, state, target FROM agent_jobs WHERE path = ?", (signature[0],)
        ).fetchone()
        if row is None:
            return True
        if tuple(row[:2]) != signature[1:] or row[2] not in {"done", "skipped"}:
            return True
        return not row[3] or not Path(row[3]).exists()

    def start(self, path: Path) -> bool:
        signature = self.signature(path)
        if signature is None:
            return False
        self.connection.execute(
            """INSERT INTO agent_jobs(path, size, mtime_ns, state, attempts, last_error, updated_at)
               VALUES (?, ?, ?, 'running', 1, '', ?)
               ON CONFLICT(path) DO UPDATE SET
                 size=excluded.size, mtime_ns=excluded.mtime_ns, state='running',
                 attempts=agent_jobs.attempts + 1, last_error='', updated_at=excluded.updated_at""",
            (*signature, time.time()),
        )
        self.connection.commit()
        return True

    def finish(self, path: Path, state: str = "done", error: str = "", target: Path | None = None) -> None:
        if state not in {"done", "skipped", "failed"}:
            raise ValueError(f"État agent inconnu : {state}")
        signature = self.signature(path)
        if signature is None:
            return
        self.connection.execute(
            """INSERT INTO agent_jobs(path, size, mtime_ns, state, attempts, last_error, target, updated_at)
               VALUES (?, ?, ?, ?, 0, ?, ?, ?)
               ON CONFLICT(path) DO UPDATE SET
                 size=excluded.size, mtime_ns=excluded.mtime_ns, state=excluded.state,
                 attempts=agent_jobs.attempts, last_error=excluded.last_error,
                 target=excluded.target, updated_at=excluded.updated_at""",
            (*signature, state, error[:2000], str(target or ""), time.time()),
        )
        self.connection.commit()

    def recover_interrupted(self) -> int:
        cursor = self.connection.execute(
            "UPDATE agent_jobs SET state='pending', updated_at=? WHERE state='running'",
            (time.time(),),
        )
        self.connection.commit()
        return cursor.rowcount

    def counts(self) -> dict[str, int]:
        rows = self.connection.execute(
            "SELECT state, COUNT(*) FROM agent_jobs GROUP BY state"
        ).fetchall()
        return {str(state): int(count) for state, count in rows}

    def close(self) -> None:
        self.connection.close()


@dataclass(frozen=True)
class AgentRun:
    run_id: str
    started_at: float


def new_run() -> AgentRun:
    return AgentRun(str(uuid.uuid4()), time.time())

"""SQLite persistence for both Tomatto services.

The Manager owns the authoritative rule list plus a monotonic ``version`` that
increments on every mutation (add/delete). The Sync service stores only the
latest full snapshot pushed to it and refuses stale versions — this is the
integration seam exercised by tests/integration/.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path


def _connect(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_parent_dir(path: str) -> None:
    parent = str(Path(path).resolve().parent)
    Path(parent).mkdir(parents=True, exist_ok=True)


class DuplicateDomainError(Exception):
    """Raised when adding a domain that is already blocked."""


class ManagerStore:
    def __init__(self, path: str) -> None:
        _ensure_parent_dir(path)
        self.path = path
        with _connect(path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS rules (
                    id TEXT PRIMARY KEY,
                    domain TEXT NOT NULL UNIQUE,
                    include_subdomains INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    sync_status TEXT NOT NULL DEFAULT 'pending'
                )
                """
            )
            conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value INTEGER NOT NULL)")
            conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('version', 0)")

    # -- reads ---------------------------------------------------------------

    def get_version(self) -> int:
        with _connect(self.path) as conn:
            row = conn.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()
            return int(row["value"])

    def list_rules(self) -> list[dict]:
        with _connect(self.path) as conn:
            rows = conn.execute("SELECT * FROM rules ORDER BY created_at, id").fetchall()
        return [self._to_dict(row) for row in rows]

    def snapshot(self) -> dict:
        """Full-list payload pushed to the Sync API."""
        return {
            "version": self.get_version(),
            "sites": [
                {"domain": r["domain"], "include_subdomains": r["include_subdomains"]}
                for r in self.list_rules()
            ],
        }

    # -- writes --------------------------------------------------------------

    def add_rule(self, domain: str, include_subdomains: bool) -> dict:
        import uuid

        rule_id = uuid.uuid4().hex
        created_at = datetime.now(timezone.utc).isoformat()
        with _connect(self.path) as conn:
            try:
                conn.execute(
                    "INSERT INTO rules (id, domain, include_subdomains, created_at, sync_status)"
                    " VALUES (?, ?, ?, ?, 'pending')",
                    (rule_id, domain, int(include_subdomains), created_at),
                )
            except sqlite3.IntegrityError as exc:
                raise DuplicateDomainError(domain) from exc
            conn.execute("UPDATE meta SET value = value + 1 WHERE key = 'version'")
        return {
            "id": rule_id,
            "domain": domain,
            "include_subdomains": include_subdomains,
            "created_at": created_at,
            "sync_status": "pending",
        }

    def delete_rule(self, rule_id: str) -> bool:
        with _connect(self.path) as conn:
            cur = conn.execute("DELETE FROM rules WHERE id = ?", (rule_id,))
            if cur.rowcount == 0:
                return False
            conn.execute("UPDATE meta SET value = value + 1 WHERE key = 'version'")
        return True

    def mark_all_synced(self) -> None:
        with _connect(self.path) as conn:
            conn.execute("UPDATE rules SET sync_status = 'synced'")

    # -- helpers ---------------------------------------------------------------

    @staticmethod
    def _to_dict(row: sqlite3.Row) -> dict:
        return {
            "id": row["id"],
            "domain": row["domain"],
            "include_subdomains": bool(row["include_subdomains"]),
            "created_at": row["created_at"],
            "sync_status": row["sync_status"],
        }


class SyncStore:
    """Holds the latest snapshot received from the Manager API."""

    def __init__(self, path: str) -> None:
        _ensure_parent_dir(path)
        self.path = path
        with _connect(path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sites (
                    domain TEXT PRIMARY KEY,
                    include_subdomains INTEGER NOT NULL DEFAULT 1
                )
                """
            )
            conn.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value INTEGER NOT NULL)")
            conn.execute("INSERT OR IGNORE INTO meta (key, value) VALUES ('version', 0)")

    def get(self) -> tuple[int, list[dict]]:
        with _connect(self.path) as conn:
            version = int(conn.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()["value"])
            rows = conn.execute("SELECT domain, include_subdomains FROM sites ORDER BY domain").fetchall()
        sites = [
            {"domain": r["domain"], "include_subdomains": bool(r["include_subdomains"])} for r in rows
        ]
        return version, sites

    def put_snapshot(self, version: int, sites: list[dict]) -> bool:
        """Replace the stored snapshot. Returns False (stale) if ``version`` is
        older than what we already hold; equal versions are accepted so retries
        stay idempotent."""
        with _connect(self.path) as conn:
            current = int(conn.execute("SELECT value FROM meta WHERE key = 'version'").fetchone()["value"])
            if version < current:
                return False
            conn.execute("DELETE FROM sites")
            conn.executemany(
                "INSERT INTO sites (domain, include_subdomains) VALUES (?, ?)",
                [(s["domain"], int(s["include_subdomains"])) for s in sites],
            )
            conn.execute("UPDATE meta SET value = ? WHERE key = 'version'", (version,))
        return True

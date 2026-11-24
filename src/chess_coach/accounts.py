"""Linked Chess.com and Lichess accounts: link, list, sync in the background, unlink."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime

import psycopg

from chess_coach import sources
from chess_coach.import_games import import_pgn


class AlreadyLinked(ValueError):
    pass


def link(conn: psycopg.Connection, platform: str, username: str) -> dict:
    sources.check_username(platform, username)
    try:
        row = conn.execute(
            "INSERT INTO linked_accounts (platform, username) VALUES (%s, %s)"
            " RETURNING id, platform, username, linked_at, last_synced_at", (platform, username),
        ).fetchone()
    except psycopg.errors.UniqueViolation as e:
        conn.rollback()
        raise AlreadyLinked(f"{username} is already linked on that site") from e
    conn.commit()
    return _row(row, 0)


def _row(r: tuple, games: int) -> dict:
    return {"id": r[0], "platform": r[1], "username": r[2], "linked_at": r[3].isoformat(),
            "last_synced_at": r[4].isoformat() if r[4] else None, "games": games}


def get(conn: psycopg.Connection, account_id: int) -> dict | None:
    return next((a for a in list_accounts(conn) if a["id"] == account_id), None)


def list_accounts(conn: psycopg.Connection) -> list[dict]:
    rows = conn.execute(
        "SELECT a.id, a.platform, a.username, a.linked_at, a.last_synced_at, count(g.id)"
        " FROM linked_accounts a LEFT JOIN games g ON g.source_account = a.id"
        " GROUP BY a.id ORDER BY a.id").fetchall()
    return [_row(r[:5], r[5]) for r in rows]


def unlink(conn: psycopg.Connection, account_id: int, delete_games: bool) -> int | None:
    """Remove the link. Returns how many games were deleted, or None if there was no such account.
    Without delete_games the games stay and simply no longer belong to an account."""
    if not conn.execute("SELECT 1 FROM linked_accounts WHERE id = %s", (account_id,)).fetchone():
        return None
    with conn.transaction():
        deleted = 0
        if delete_games:  # moves, evaluations, facts and explanations go with them (cascade)
            deleted = conn.execute("DELETE FROM games WHERE source_account = %s",
                                   (account_id,)).rowcount
        conn.execute("DELETE FROM linked_accounts WHERE id = %s", (account_id,))
    return deleted


@dataclass
class SyncState:
    state: str = "idle"  # idle | fetching | analysing | done | error | cancelled
    done: int = 0
    total: int = 0
    imported: int = 0
    message: str = ""
    stop: threading.Event = field(default_factory=threading.Event)

    def public(self) -> dict:
        return {"state": self.state, "done": self.done, "total": self.total,
                "imported": self.imported, "message": self.message}


class SyncManager:
    """Runs one sync at a time in a background thread. Stockfish is the slow part, so a second
    request while one runs is refused instead of queued."""

    def __init__(self, connect: Callable[[], psycopg.Connection], engine_factory,
                 get: sources.Get = sources.http_get, depth: int = 14) -> None:
        self._connect, self._engine_factory, self._get, self._depth = connect, engine_factory, get, depth
        self._lock = threading.Lock()
        self.states: dict[int, SyncState] = {}
        self._thread: threading.Thread | None = None

    def busy(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def status(self, account_id: int) -> dict:
        return self.states.get(account_id, SyncState()).public()

    def start(self, account: dict, since: datetime) -> bool:
        with self._lock:
            if self.busy():
                return False
            st = self.states[account["id"]] = SyncState(state="fetching")
            self._thread = threading.Thread(target=self._run, args=(account, since, st), daemon=True)
            self._thread.start()
            return True

    def cancel(self, account_id: int) -> None:
        if st := self.states.get(account_id):
            st.stop.set()

    def wait(self, timeout: float = 30) -> None:
        if self._thread:
            self._thread.join(timeout)

    def _run(self, account: dict, since: datetime, st: SyncState) -> None:
        try:
            pgns = sources.fetch(account["platform"], account["username"], since, self._get)
            st.total, st.state = len(pgns), "analysing"
            if pgns and not st.stop.is_set():
                def log(_line: str) -> None:
                    st.done += 1
                with self._connect() as conn, self._engine_factory() as engine:
                    summary = import_pgn(conn, None, engine, engine.version, self._depth, None,
                                         log=log, pgn_text="\n\n".join(pgns),
                                         source_account=account["id"], should_stop=st.stop.is_set)
                    st.imported = summary.imported
                    if not st.stop.is_set():
                        conn.execute("UPDATE linked_accounts SET last_synced_at = now()"
                                     " WHERE id = %s", (account["id"],))
                        conn.commit()
                    st.message = (f"{summary.skipped_duplicate} already stored"
                                  + (f", {len(summary.failed)} failed" if summary.failed else ""))
            st.state = "cancelled" if st.stop.is_set() else "done"
        except sources.SourceError as e:
            st.state, st.message = "error", str(e)
        except Exception as e:  # noqa: BLE001 - the thread must report, not die silently
            st.state, st.message = "error", f"{type(e).__name__}: {e}"

from __future__ import annotations

import asyncio
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List


@dataclass(slots=True)
class SupportTicket:
    id: int
    user_id: int
    subject: str
    moderator_name: str | None
    complaint_type: str | None
    target_name: str | None
    status: str
    assigned_to: int | None
    created_at: str
    updated_at: str


@dataclass(slots=True)
class SupportMessage:
    id: int
    ticket_id: int
    author_id: int
    author_role: str
    text: str
    created_at: str


class SupportService:
    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path
        self._lock = asyncio.Lock()
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._db_path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init_db(self) -> None:
        conn = self._connect()
        try:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS support_tickets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    user_id INTEGER NOT NULL,
                    subject TEXT NOT NULL,
                    moderator_name TEXT,
                    complaint_type TEXT,
                    target_name TEXT,
                    status TEXT NOT NULL,
                    assigned_to INTEGER,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS support_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    ticket_id INTEGER NOT NULL,
                    author_id INTEGER NOT NULL,
                    author_role TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
                """
            )
            try:
                conn.execute("ALTER TABLE support_tickets ADD COLUMN complaint_type TEXT")
            except sqlite3.OperationalError:
                pass
            try:
                conn.execute("ALTER TABLE support_tickets ADD COLUMN target_name TEXT")
            except sqlite3.OperationalError:
                pass
            conn.commit()
        finally:
            conn.close()

    async def create_ticket(
        self,
        user_id: int,
        subject: str,
        moderator_name: str | None,
        complaint_type: str | None,
        target_name: str | None,
    ) -> SupportTicket:
        async with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            def _run() -> SupportTicket:
                conn = self._connect()
                try:
                    cur = conn.execute(
                        """
                        INSERT INTO support_tickets (
                          user_id, subject, moderator_name, complaint_type, target_name,
                          status, assigned_to, created_at, updated_at
                        )
                        VALUES (?, ?, ?, ?, ?, 'open', NULL, ?, ?)
                        """,
                        (user_id, subject, moderator_name, complaint_type, target_name, now, now),
                    )
                    ticket_id = cur.lastrowid
                    conn.commit()
                    row = conn.execute("SELECT * FROM support_tickets WHERE id = ?", (ticket_id,)).fetchone()
                    return SupportTicket(**dict(row))
                finally:
                    conn.close()
            return await asyncio.to_thread(_run)

    async def list_tickets(self, *, user_id: int | None, include_all: bool) -> List[SupportTicket]:
        async with self._lock:
            def _run() -> List[SupportTicket]:
                conn = self._connect()
                try:
                    if include_all:
                        rows = conn.execute(
                            "SELECT * FROM support_tickets WHERE status != 'closed' ORDER BY updated_at DESC"
                        ).fetchall()
                    else:
                        rows = conn.execute(
                            "SELECT * FROM support_tickets WHERE user_id = ? AND status != 'closed' ORDER BY updated_at DESC",
                            (user_id,),
                        ).fetchall()
                    return [SupportTicket(**dict(row)) for row in rows]
                finally:
                    conn.close()
            return await asyncio.to_thread(_run)

    async def get_ticket(self, ticket_id: int) -> SupportTicket | None:
        async with self._lock:
            def _run() -> SupportTicket | None:
                conn = self._connect()
                try:
                    row = conn.execute("SELECT * FROM support_tickets WHERE id = ?", (ticket_id,)).fetchone()
                    return SupportTicket(**dict(row)) if row else None
                finally:
                    conn.close()
            return await asyncio.to_thread(_run)

    async def list_messages(self, ticket_id: int) -> List[SupportMessage]:
        async with self._lock:
            def _run() -> List[SupportMessage]:
                conn = self._connect()
                try:
                    rows = conn.execute(
                        "SELECT * FROM support_messages WHERE ticket_id = ? ORDER BY id ASC",
                        (ticket_id,),
                    ).fetchall()
                    return [SupportMessage(**dict(row)) for row in rows]
                finally:
                    conn.close()
            return await asyncio.to_thread(_run)

    async def add_message(self, ticket_id: int, author_id: int, author_role: str, text: str) -> SupportMessage:
        async with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            def _run() -> SupportMessage:
                conn = self._connect()
                try:
                    cur = conn.execute(
                        """
                        INSERT INTO support_messages (ticket_id, author_id, author_role, text, created_at)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (ticket_id, author_id, author_role, text, now),
                    )
                    conn.execute(
                        "UPDATE support_tickets SET updated_at = ? WHERE id = ?",
                        (now, ticket_id),
                    )
                    conn.commit()
                    row = conn.execute("SELECT * FROM support_messages WHERE id = ?", (cur.lastrowid,)).fetchone()
                    return SupportMessage(**dict(row))
                finally:
                    conn.close()
            return await asyncio.to_thread(_run)

    async def assign(self, ticket_id: int, moderator_id: int) -> None:
        async with self._lock:
            now = datetime.now(timezone.utc).isoformat()
            def _run() -> None:
                conn = self._connect()
                try:
                    conn.execute(
                        "UPDATE support_tickets SET assigned_to = ?, status = 'in_progress', updated_at = ? WHERE id = ?",
                        (moderator_id, now, ticket_id),
                    )
                    conn.commit()
                finally:
                    conn.close()
            await asyncio.to_thread(_run)

    async def close(self, ticket_id: int) -> None:
        async with self._lock:
            def _run() -> None:
                conn = self._connect()
                try:
                    conn.execute("DELETE FROM support_messages WHERE ticket_id = ?", (ticket_id,))
                    conn.execute("DELETE FROM support_tickets WHERE id = ?", (ticket_id,))
                    conn.commit()
                finally:
                    conn.close()
            await asyncio.to_thread(_run)

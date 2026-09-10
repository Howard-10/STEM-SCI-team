"""Durable idempotency journal for project-scoped conversation commands."""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


class ConversationCommandJournal:
    """Persist orchestration turns independently from QA answer memory."""

    def __init__(self, database: Path) -> None:
        database.parent.mkdir(parents=True, exist_ok=True)
        self.database = database
        with self._connect() as connection:
            connection.execute(
                """
                create table if not exists orchestration_conversation_turns (
                    ordinal integer primary key autoincrement,
                    project_id text not null,
                    turn_id text not null,
                    actor text not null,
                    message text not null,
                    request_hash text not null,
                    status text not null,
                    response_json text,
                    created_at text not null,
                    unique(project_id, turn_id)
                )
                """
            )
            connection.execute(
                """
                create index if not exists idx_orchestration_turns_project
                on orchestration_conversation_turns(project_id, ordinal)
                """
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database, timeout=15)
        connection.row_factory = sqlite3.Row
        return connection

    @staticmethod
    def _row(row: sqlite3.Row) -> dict[str, Any]:
        value = dict(row)
        value["response"] = json.loads(value.pop("response_json") or "null")
        return value

    def begin(
        self,
        project_id: str,
        turn_id: str | None,
        actor: str,
        message: str,
        request_hash: str,
    ) -> tuple[dict[str, Any], bool]:
        stable_turn_id = turn_id or f"turn-{uuid4().hex}"
        with self._connect() as connection:
            cursor = connection.execute(
                """
                insert or ignore into orchestration_conversation_turns(
                    project_id, turn_id, actor, message, request_hash, status, created_at
                ) values (?, ?, ?, ?, ?, 'received', ?)
                """,
                (
                    project_id,
                    stable_turn_id,
                    actor,
                    message,
                    request_hash,
                    datetime.now(UTC).isoformat(),
                ),
            )
            row = connection.execute(
                """
                select * from orchestration_conversation_turns
                where project_id=? and turn_id=?
                """,
                (project_id, stable_turn_id),
            ).fetchone()
            if row is None:
                raise RuntimeError("conversation journal write did not persist")
            if row["actor"] != actor or row["request_hash"] != request_hash:
                raise ValueError("同一消息编号对应了不同内容，请使用新的消息编号。")
            return self._row(row), cursor.rowcount == 1

    def update(
        self,
        project_id: str,
        turn_id: str,
        *,
        status: str,
        response: dict[str, Any] | None = None,
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                update orchestration_conversation_turns
                set status=?, response_json=coalesce(?, response_json)
                where project_id=? and turn_id=?
                """,
                (
                    status,
                    json.dumps(response, ensure_ascii=False) if response is not None else None,
                    project_id,
                    turn_id,
                ),
            )

    def list(self, project_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                select * from orchestration_conversation_turns
                where project_id=? order by ordinal asc limit ?
                """,
                (project_id, min(max(limit, 1), 200)),
            ).fetchall()
        return [self._row(row) for row in rows]

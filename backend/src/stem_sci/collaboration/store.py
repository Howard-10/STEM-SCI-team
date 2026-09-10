"""Durable storage for the researcher-facing belief graph."""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from .models import ResearchBranch, ResearchGraph, utc_now


class SQLiteResearchGraphStore:
    """Store a compact versioned graph without requiring a graph database."""

    def __init__(self, database: Path) -> None:
        self.database = database
        self.database.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database)
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def _init_db(self) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                create table if not exists research_belief_graphs (
                    project_id text primary key,
                    version integer not null,
                    graph_json text not null,
                    updated_at text not null,
                    branches_json text not null default '[]'
                )
                """
            )
            columns = {
                str(row[1])
                for row in connection.execute("pragma table_info(research_belief_graphs)").fetchall()
            }
            if "branches_json" not in columns:
                connection.execute(
                    "alter table research_belief_graphs add column branches_json text not null default '[]'"
                )

    def get(self, project_id: str) -> ResearchGraph:
        with self._connect() as connection:
            row = connection.execute(
                "select graph_json from research_belief_graphs where project_id=?",
                (project_id,),
            ).fetchone()
        if row is None:
            return ResearchGraph(project_id=project_id)
        return ResearchGraph.model_validate_json(str(row[0]))

    def save(self, graph: ResearchGraph, *, expected_version: int) -> ResearchGraph:
        """Optimistically save one graph revision."""

        if graph.version != expected_version + 1:
            raise ValueError("graph version must advance by exactly one")
        payload = graph.model_dump_json()
        with self._connect() as connection:
            current = connection.execute(
                "select version from research_belief_graphs where project_id=?",
                (graph.project_id,),
            ).fetchone()
            actual_version = int(current[0]) if current is not None else 0
            if actual_version != expected_version:
                raise ValueError(
                    "research graph revision conflict: "
                    f"expected {expected_version}, got {actual_version}"
                )
            connection.execute(
                """
                insert into research_belief_graphs(project_id, version, graph_json, updated_at)
                values (?, ?, ?, ?)
                on conflict(project_id) do update set
                    version=excluded.version,
                    graph_json=excluded.graph_json,
                    updated_at=excluded.updated_at
                """,
                (graph.project_id, graph.version, payload, graph.updated_at.isoformat()),
            )
        return graph

    def list_branches(self, project_id: str) -> list[ResearchBranch]:
        with self._connect() as connection:
            row = connection.execute(
                "select branches_json from research_belief_graphs where project_id=?",
                (project_id,),
            ).fetchone()
        if row is None or not row[0]:
            return []
        try:
            import json

            payload = json.loads(str(row[0]))
            return [ResearchBranch.model_validate(item) for item in payload]
        except (TypeError, ValueError):
            return []

    def save_branch(self, branch: ResearchBranch) -> ResearchBranch:
        import json

        branches = [item for item in self.list_branches(branch.project_id) if item.branch_id != branch.branch_id]
        if branch.status == "selected":
            branches = [
                item.model_copy(update={"status": "parked", "updated_at": utc_now()})
                if item.status == "selected" else item
                for item in branches
            ]
        branches.append(branch.model_copy(update={"updated_at": utc_now()}))
        payload = json.dumps([item.model_dump(mode="json") for item in branches], ensure_ascii=False)
        with self._connect() as connection:
            connection.execute(
                """
                insert into research_belief_graphs(project_id, version, graph_json, updated_at, branches_json)
                values (?, 0, ?, ?, ?)
                on conflict(project_id) do update set branches_json=excluded.branches_json
                """,
                (branch.project_id, ResearchGraph(project_id=branch.project_id).model_dump_json(), utc_now().isoformat(), payload),
            )
        return branch

    def get_branch(self, project_id: str, branch_id: str) -> ResearchBranch | None:
        return next((item for item in self.list_branches(project_id) if item.branch_id == branch_id), None)

"""The index statements the Memgraph connection sends."""

from __future__ import annotations

from typing import Any

import pytest

from graflo.db.memgraph.conn import _create_vertex_index, edge_property_index_query


def test_an_edge_index_is_an_edge_type_index() -> None:
    assert (
        edge_property_index_query("REVIEWS", "rating")
        == "CREATE EDGE INDEX ON :REVIEWS(rating)"
    )


class _Cursor:
    def __init__(self, statements: list[str]) -> None:
        self._statements = statements
        self.close_calls = 0

    def execute(self, query: str, params: object = None) -> None:
        if self.close_calls:
            raise RuntimeError("Cannot execute a closed cursor")
        self._statements.append(" ".join(query.split()))

    def close(self) -> None:
        self.close_calls += 1


class _Conn:
    def __init__(self) -> None:
        self.statements: list[str] = []
        self.cursors: list[_Cursor] = []
        self.autocommit = False

    def cursor(self) -> _Cursor:
        cursor = _Cursor(self.statements)
        self.cursors.append(cursor)
        return cursor


@pytest.mark.parametrize(
    "error_message", [None, "Index already exists", "Database busy"]
)
def test_vertex_index_cursor_closes_after_every_outcome(
    monkeypatch: pytest.MonkeyPatch, error_message: str | None
) -> None:
    """Close the index cursor once, including ignored and propagated errors."""
    fake = _Conn()
    execute = _Cursor.execute
    error = RuntimeError(error_message) if error_message is not None else None

    def execute_index(self: _Cursor, query: str, params: object = None) -> None:
        """Record the attempted DDL before simulating a driver error."""
        execute(self, query, params)
        if error is not None:
            raise error

    monkeypatch.setattr(_Cursor, "execute", execute_index)
    if error_message == "Database busy":
        with pytest.raises(RuntimeError, match="Database busy") as caught:
            _create_vertex_index(fake, "person", ["tenant", "id"])
        assert caught.value is error
    else:
        _create_vertex_index(fake, "person", ["tenant", "id"])

    assert fake.statements == ["CREATE INDEX ON :person(tenant, id)"]
    assert len(fake.cursors) == 1
    assert fake.cursors[0].close_calls == 1


def test_an_upsert_creates_its_merge_index_once_per_connection(monkeypatch) -> None:
    from graflo.connections.onto import MemgraphConfig
    from graflo.db.memgraph import conn as memgraph_conn

    fake = _Conn()
    monkeypatch.setattr(memgraph_conn.mgclient, "connect", lambda **kwargs: fake)
    db = memgraph_conn.MemgraphConnection(MemgraphConfig(uri="bolt://localhost:7687"))

    for batch in range(3):
        db.upsert_docs_batch([{"id": str(batch)}], "person", match_keys=["id"])

    assert [s for s in fake.statements if s.startswith("CREATE INDEX")] == [
        "CREATE INDEX ON :person(id)"
    ]


def _memgraph(monkeypatch) -> tuple[Any, _Conn]:
    from graflo.connections.onto import MemgraphConfig
    from graflo.db.memgraph import conn as memgraph_conn

    fake = _Conn()
    monkeypatch.setattr(memgraph_conn.mgclient, "connect", lambda **kwargs: fake)
    return memgraph_conn.MemgraphConnection(
        MemgraphConfig(uri="bolt://localhost:7687")
    ), fake


def test_a_vertex_identity_is_indexed_and_constrained_unique(monkeypatch) -> None:
    from graflo.architecture.schema import Schema

    schema = Schema.model_validate(
        {
            "metadata": {"name": "people"},
            "core_schema": {
                "vertex_config": {
                    "vertices": [
                        {
                            "name": "person",
                            "properties": ["name", "born"],
                            "identity": ["name", "born"],
                        }
                    ]
                },
                "edge_config": {"edges": []},
            },
            "db_profile": {"db_flavor": "memgraph"},
        }
    )
    db, fake = _memgraph(monkeypatch)

    db.define_vertex_indexes(schema.core_schema.vertex_config, schema)

    assert fake.statements == [
        "CREATE INDEX ON :person(name, born)",
        "CREATE CONSTRAINT ON (n:person) ASSERT n.name, n.born IS UNIQUE",
    ]


@pytest.mark.parametrize("tuple_keys", [False, True])
def test_composite_merge_indexes_distinguish_field_order(
    monkeypatch: pytest.MonkeyPatch, tuple_keys: bool
) -> None:
    """Reversing the same fields creates a distinct index, each ensured once."""
    db, fake = _memgraph(monkeypatch)

    for fields in [["tenant", "id"], ["id", "tenant"]] * 2:
        db.upsert_docs_batch(
            [{"tenant": "acme", "id": "1"}],
            "person",
            match_keys=tuple(fields) if tuple_keys else fields,
        )
        assert all(cursor.close_calls == 1 for cursor in fake.cursors)

    assert [s for s in fake.statements if s.startswith("CREATE INDEX")] == [
        "CREATE INDEX ON :person(tenant, id)",
        "CREATE INDEX ON :person(id, tenant)",
    ]
    assert sum(s.startswith("UNWIND") for s in fake.statements) == 4


@pytest.mark.parametrize("already_exists", [False, True])
def test_only_successful_merge_indexes_are_cached(
    monkeypatch: pytest.MonkeyPatch, already_exists: bool
) -> None:
    """Retry failed DDL without interrupting ingestion or retrying existing indexes."""
    db, fake = _memgraph(monkeypatch)
    execute = _Cursor.execute
    attempts: list[str] = []

    def fail_first_index(self: _Cursor, query: str, params: object = None) -> None:
        """Simulate a catalogue failure on the first index request."""
        if query.startswith("CREATE INDEX"):
            attempts.append(query)
            if len(attempts) == 1:
                raise RuntimeError("Index already exists" if already_exists else "busy")
        execute(self, query, params)

    monkeypatch.setattr(_Cursor, "execute", fail_first_index)
    for _ in range(3):
        db.upsert_docs_batch([{"id": "1"}], "person", match_keys=["id"])
        assert all(cursor.close_calls == 1 for cursor in fake.cursors)

    assert len(attempts) == (1 if already_exists else 2)
    assert sum(s.startswith("UNWIND") for s in fake.statements) == 3


def test_merge_indexes_distinguish_field_groups(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An existing simple index does not stand in for a composite one."""
    db, fake = _memgraph(monkeypatch)

    for fields in [["id"], ["tenant", "id"], ["id"], ["tenant", "id"]]:
        db.upsert_docs_batch(
            [{"tenant": "acme", "id": "1"}], "person", match_keys=fields
        )

    assert [s for s in fake.statements if s.startswith("CREATE INDEX")] == [
        "CREATE INDEX ON :person(id)",
        "CREATE INDEX ON :person(tenant, id)",
    ]


def test_composite_indexes_quote_each_identifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A comma or backtick in a property name remains part of that name."""
    db, fake = _memgraph(monkeypatch)

    db.upsert_docs_batch(
        [{"tenant, id": "acme", "external`id": "1"}],
        "work item",
        match_keys=["tenant, id", "external`id"],
    )

    assert fake.statements[0] == (
        "CREATE INDEX ON :`work item`(`tenant, id`, `external``id`)"
    )


class _CatalogCursor(_Cursor):
    """Answers ``SHOW CONSTRAINT INFO`` with a fixed catalogue."""

    description = [
        type("Column", (), {"name": name})()
        for name in ("constraint type", "label", "properties", "data_type")
    ]

    def fetchall(self) -> list[tuple]:
        return [
            ("unique", "person", ["name", "born"], ""),
            ("exists", "person", "name", ""),
            ("unique", "org", ["code"], ""),
        ]


class _CatalogConn(_Conn):
    def cursor(self) -> _Cursor:
        cursor = _CatalogCursor(self.statements)
        self.cursors.append(cursor)
        return cursor


def _memgraph_with_catalog(monkeypatch) -> tuple[Any, _Conn]:
    from graflo.connections.onto import MemgraphConfig
    from graflo.db.memgraph import conn as memgraph_conn

    fake = _CatalogConn()
    monkeypatch.setattr(memgraph_conn.mgclient, "connect", lambda **kwargs: fake)
    return memgraph_conn.MemgraphConnection(
        MemgraphConfig(uri="bolt://localhost:7687")
    ), fake


def test_deleting_everything_drops_the_unique_constraints(monkeypatch) -> None:
    db, fake = _memgraph_with_catalog(monkeypatch)

    db.delete_graph_structure(delete_all=True)

    assert [s for s in fake.statements if s.startswith("DROP")] == [
        "DROP CONSTRAINT ON (n:person) ASSERT n.name, n.born IS UNIQUE",
        "DROP CONSTRAINT ON (n:org) ASSERT n.code IS UNIQUE",
    ]


def test_deleting_a_label_drops_only_its_unique_constraints(monkeypatch) -> None:
    db, fake = _memgraph_with_catalog(monkeypatch)

    db.delete_graph_structure(vertex_types=("org",))

    assert [s for s in fake.statements if s.startswith("DROP")] == [
        "DROP CONSTRAINT ON (n:org) ASSERT n.code IS UNIQUE",
    ]

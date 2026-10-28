"""Tests for Memgraph index creation operations.

Schema-driven vertex index creation is shared from cypher_cases.
"""

import pytest

from graflo.architecture.schema import Schema
from graflo.connections.onto import MemgraphConfig
from graflo.db.manager import ConnectionManager
from test.db.cypher_cases.lifecycle import (
    test_create_vertex_index,
)

__all__ = [
    "test_create_vertex_index",
]


def test_composite_vertex_indexes(
    conn_conf: MemgraphConfig, test_graph_name: str, clean_db: None
) -> None:
    """Schema and upserts preserve composite indexes and enforce the identity."""
    label = test_graph_name
    schema = Schema.model_validate(
        {
            "metadata": {"name": "composite_indexes"},
            "core_schema": {
                "vertex_config": {
                    "vertices": [
                        {
                            "name": label,
                            "properties": ["tenant", "id", "name", "born"],
                            "identity": ["tenant", "id"],
                        }
                    ]
                },
                "edge_config": {"edges": []},
            },
            "db_profile": {
                "db_flavor": "memgraph",
                "vertex_indexes": {label: [{"fields": ["name", "born"]}]},
            },
        }
    )
    with ConnectionManager(connection_config=conn_conf) as db:
        # Repeating schema definition must also accept existing composite indexes.
        for _ in range(2):
            db.define_vertex_indexes(schema.core_schema.vertex_config, schema)
        db.upsert_docs_batch(
            [
                {"tenant": "acme", "id": "1", "name": "Alice", "born": 1990},
                {"tenant": "other", "id": "1", "name": "Bob", "born": 1991},
            ],
            label,
            match_keys=["tenant", "id"],
        )
        db.upsert_docs_batch(
            [{"tenant": "acme", "id": "1", "name": "Alicia"}],
            label,
            match_keys=["tenant", "id"],
        )

        catalog = db.execute("SHOW INDEX INFO")
        indexes = [dict(zip(catalog.columns, row)) for row in catalog]
        assert {
            tuple(row["property"])
            for row in indexes
            if row["label"] == label and row["index type"] == "label+property"
        } == {("tenant", "id"), ("name", "born")}
        assert sorted(db.fetch_docs(label), key=lambda doc: doc["tenant"]) == [
            {"tenant": "acme", "id": "1", "name": "Alicia", "born": 1990},
            {"tenant": "other", "id": "1", "name": "Bob", "born": 1991},
        ]
        with pytest.raises(Exception, match="[Uu]nique"):
            db.execute(
                f"CREATE (:{label} {{tenant: $tenant, id: $id}})", tenant="acme", id="1"
            )
        assert len(db.fetch_docs(label)) == 2


def test_create_edge_index(conn_conf, test_graph_name, schema_obj):
    """Test creating edge indexes from schema."""
    schema_o = schema_obj("review")

    with ConnectionManager(connection_config=conn_conf) as db_client:
        db_client.define_edge_indexes(
            list(schema_o.core_schema.edge_config.values()), schema=schema_o
        )

    with ConnectionManager(connection_config=conn_conf) as db_client:
        rows = list(db_client.execute("SHOW INDEX INFO"))
    declared = {
        (edge.relation, field)
        for edge in schema_o.core_schema.edge_config.values()
        for index in schema_o.db_profile.edge_secondary_indexes(edge.edge_id)
        for field in index.fields
    }
    # Each row reads (index type, label or edge type, property, count).
    edge_indexes = {
        (row[1], row[2]) for row in rows if str(row[0]).startswith("edge-type")
    }
    assert declared <= edge_indexes


def test_manual_index_creation(conn_conf, test_graph_name, clean_db):
    """Test manual index creation on a label."""
    _ = clean_db

    with ConnectionManager(connection_config=conn_conf) as db_client:
        # Create some test data first (indexes require the label to exist)
        db_client.upsert_docs_batch(
            [{"id": "1", "email": "test@test.com"}],
            "User",
            match_keys=["id"],
        )

        # Create index on email field using Memgraph syntax
        try:
            db_client.execute("CREATE INDEX ON :User(email)")
        except Exception:
            # Index may already exist
            pass

        # Verify we can still query using the indexed field
        result = db_client.fetch_docs("User", filters=["==", "test@test.com", "email"])
        assert len(result) == 1


def test_show_indexes(conn_conf, test_graph_name, clean_db):
    """Test listing existing indexes."""
    _ = clean_db

    with ConnectionManager(connection_config=conn_conf) as db_client:
        # Create test data and index
        db_client.upsert_docs_batch(
            [{"id": "1", "name": "Test"}],
            "IndexTest",
            match_keys=["id"],
        )

        try:
            db_client.execute("CREATE INDEX ON :IndexTest(name)")
        except Exception:
            pass

        # Query indexes - Memgraph uses SHOW INDEX INFO
        result = db_client.execute("SHOW INDEX INFO")
        # Just verify the query works, result format varies by version
        assert result is not None

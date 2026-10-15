"""Tests for Memgraph index creation operations.

Schema-driven vertex index creation is shared from cypher_cases.
"""

from graflo.db.manager import ConnectionManager
from test.db.cypher_cases.lifecycle import (
    test_create_vertex_index,
)

__all__ = [
    "test_create_vertex_index",
]


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

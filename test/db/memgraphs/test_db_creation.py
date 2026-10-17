"""Tests for Memgraph database/graph creation and deletion operations.

Engine-agnostic connection and CRUD tests are shared from cypher_cases.
"""

from graflo.db.manager import ConnectionManager
from test.db.cypher_cases.lifecycle import (
    test_connection_initialization,
    test_delete_graph_structure,
    test_fetch_docs_with_filter,
    test_fetch_docs_with_limit,
    test_fetch_docs_with_projection,
    test_insert_edges,
    test_upsert_single_node,
    test_upsert_updates_existing_node,
)

__all__ = [
    "test_connection_initialization",
    "test_delete_graph_structure",
    "test_fetch_docs_with_filter",
    "test_fetch_docs_with_limit",
    "test_fetch_docs_with_projection",
    "test_insert_edges",
    "test_upsert_single_node",
    "test_upsert_updates_existing_node",
]


def test_create_database(conn_conf, test_graph_name):
    """Test that create_database is a no-op (Memgraph is single-database)."""
    with ConnectionManager(connection_config=conn_conf) as db_client:
        # create_database is a no-op for Memgraph
        db_client.create_database(test_graph_name)
        # Connection should still work
        assert db_client.conn is not None

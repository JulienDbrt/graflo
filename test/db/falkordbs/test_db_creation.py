"""Tests for FalkorDB database/graph creation and deletion operations.

Engine-agnostic connection and CRUD tests are shared from cypher_cases.
"""

from graflo.db.manager import ConnectionManager
from test.db.cypher_cases.lifecycle import (
    test_connection_initialization,
    test_fetch_docs_with_filter,
    test_fetch_docs_with_limit,
    test_fetch_docs_with_projection,
    test_insert_edges,
    test_upsert_single_node,
    test_upsert_updates_existing_node,
)
from test.db.cypher_cases.lifecycle import (
    test_delete_graph_structure as test_delete_graph,
)

__all__ = [
    "test_connection_initialization",
    "test_delete_graph",
    "test_fetch_docs_with_filter",
    "test_fetch_docs_with_limit",
    "test_fetch_docs_with_projection",
    "test_insert_edges",
    "test_upsert_single_node",
    "test_upsert_updates_existing_node",
]


def test_create_graph(conn_conf, test_graph_name):
    """Test that a graph can be created."""
    with ConnectionManager(connection_config=conn_conf) as db_client:
        # Graph is created implicitly when selected
        db_client.create_database(test_graph_name)
        assert db_client._graph_name == test_graph_name

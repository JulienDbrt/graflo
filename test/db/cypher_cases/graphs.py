"""Pathological graph topologies and state-corruption cases.

Backend-agnostic Cypher cases, shared by the Memgraph and FalkorDB suites.

These are mixins, not tests: the module is outside any ``test_*.py`` so pytest
never collects them directly. Each backend's ``test_edge_cases.py`` subclasses
them, which is what supplies the ``conn_conf`` / ``test_graph_name`` /
``clean_db`` fixtures -- both backend conftests expose that same trio.
"""

from __future__ import annotations

import threading
from typing import Any, cast

import pytest

from graflo.db.manager import ConnectionManager
from graflo.onto import AggregationType


class PathologicalGraphsCases:
    """Tests for pathological graph structures."""

    def test_bidirectional_edges(self, conn_conf, test_graph_name, clean_db):
        """Test bidirectional edges between same nodes."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            db.upsert_docs_batch(
                [{"id": "1"}, {"id": "2"}], "BiNode", match_keys=["id"]
            )

            # Create edge A -> B
            db.insert_edges_batch(
                [[{"id": "1"}, {"id": "2"}, {"dir": "forward"}]],
                source_class="BiNode",
                target_class="BiNode",
                relation_name="BIDI",
                match_keys_source=["id"],
                match_keys_target=["id"],
            )

            # Create edge B -> A
            db.insert_edges_batch(
                [[{"id": "2"}, {"id": "1"}, {"dir": "backward"}]],
                source_class="BiNode",
                target_class="BiNode",
                relation_name="BIDI",
                match_keys_source=["id"],
                match_keys_target=["id"],
            )

            result = db.execute("MATCH ()-[r:BIDI]->() RETURN count(r)")
            assert result.result_set[0][0] == 2

    def test_long_chain(self, conn_conf, test_graph_name, clean_db):
        """Test long chain of nodes."""
        _ = clean_db
        chain_length = 100

        with ConnectionManager(connection_config=conn_conf) as db:
            # Create nodes
            nodes = [{"id": str(i)} for i in range(chain_length)]
            db.upsert_docs_batch(nodes, "ChainNode", match_keys=["id"])

            # Create chain edges
            edges = [
                [{"id": str(i)}, {"id": str(i + 1)}, {}]
                for i in range(chain_length - 1)
            ]
            db.insert_edges_batch(
                edges,
                source_class="ChainNode",
                target_class="ChainNode",
                relation_name="NEXT",
                match_keys_source=["id"],
                match_keys_target=["id"],
            )

            # Verify chain
            result = db.execute(
                f"MATCH p=(a:ChainNode {{id: '0'}})-[:NEXT*..{chain_length}]->(b) "
                f"RETURN length(p) ORDER BY length(p) DESC LIMIT 1"
            )
            assert result.result_set[0][0] == chain_length - 1

    def test_star_topology(self, conn_conf, test_graph_name, clean_db):
        """Test star topology (hub with many spokes)."""
        _ = clean_db
        num_spokes = 100

        with ConnectionManager(connection_config=conn_conf) as db:
            # Create hub and spokes
            nodes = [{"id": "hub"}]
            nodes.extend([{"id": f"spoke_{i}"} for i in range(num_spokes)])
            db.upsert_docs_batch(nodes, "StarNode", match_keys=["id"])

            # Create edges from hub to all spokes
            edges = [
                [{"id": "hub"}, {"id": f"spoke_{i}"}, {"index": i}]
                for i in range(num_spokes)
            ]
            db.insert_edges_batch(
                edges,
                source_class="StarNode",
                target_class="StarNode",
                relation_name="SPOKE",
                match_keys_source=["id"],
                match_keys_target=["id"],
            )

            # Verify star
            result = db.execute(
                "MATCH (h:StarNode {id: 'hub'})-[:SPOKE]->(s) RETURN count(s)"
            )
            assert result.result_set[0][0] == num_spokes


class StateCorruptionCases:
    """Test state handling and connection management."""

    def test_operations_after_close(self, conn_conf, test_graph_name):
        """Attempt operations after connection is closed."""
        db = ConnectionManager(connection_config=conn_conf)
        db.__enter__()
        db.__exit__(None, None, None)

        # These should fail gracefully
        with pytest.raises(Exception):
            fetch_docs = cast(Any, db).fetch_docs
            fetch_docs("SomeLabel")

    def test_double_close(self, conn_conf, test_graph_name):
        """Close connection twice."""
        db = ConnectionManager(connection_config=conn_conf)
        db.__enter__()
        db.__exit__(None, None, None)
        # Second close should not crash
        db.__exit__(None, None, None)

    def test_nested_context_managers(self, conn_conf, test_graph_name, clean_db):
        """Test nested connection managers."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db1:
            docs = [{"id": "outer"}]
            db1.upsert_docs_batch(docs, "Nested", match_keys=["id"])

            with ConnectionManager(connection_config=conn_conf) as db2:
                # Inner connection should see outer's data
                result = db2.fetch_docs("Nested")
                assert len(result) == 1

                docs = [{"id": "inner"}]
                db2.upsert_docs_batch(docs, "Nested", match_keys=["id"])

            # Outer should see inner's data
            result = db1.fetch_docs("Nested")
            assert len(result) == 2


class GraphAlgorithmCases:
    """Topologies that stress traversal algorithms."""

    def test_lollipop_graph(self, conn_conf, test_graph_name, clean_db):
        """Lollipop graph - pathological for certain algorithms."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            # Clique (the candy)
            clique_size = 10
            docs = [{"id": f"clique_{i}"} for i in range(clique_size)]
            db.upsert_docs_batch(docs, "Lollipop", match_keys=["id"])

            # Path (the stick)
            stick_length = 20
            docs = [{"id": f"stick_{i}"} for i in range(stick_length)]
            db.upsert_docs_batch(docs, "Lollipop", match_keys=["id"])

            # Clique edges (complete graph)
            edges = []
            for i in range(clique_size):
                for j in range(i + 1, clique_size):
                    edges.append([{"id": f"clique_{i}"}, {"id": f"clique_{j}"}, {}])

            # Stick edges (path)
            for i in range(stick_length - 1):
                edges.append([{"id": f"stick_{i}"}, {"id": f"stick_{i + 1}"}, {}])

            # Connect stick to clique
            edges.append([{"id": "stick_0"}, {"id": "clique_0"}, {}])

            db.insert_edges_batch(
                edges,
                source_class="Lollipop",
                target_class="Lollipop",
                relation_name="CONNECTED",
                match_keys_source=["id"],
                match_keys_target=["id"],
            )

            # Verify structure
            result = db.execute("MATCH ()-[r:CONNECTED]->() RETURN count(r)")
            expected = (clique_size * (clique_size - 1)) // 2 + stick_length
            assert result.result_set[0][0] == expected


class LockOrderingCases:
    """Opposite-order updates and reads during inserts."""

    def test_circular_update_dependency(self, conn_conf, test_graph_name, clean_db):
        """Create circular update patterns that could deadlock."""
        _ = clean_db
        errors = []

        def update_a_then_b():
            """Update node A then node B in a loop to test lock ordering."""
            try:
                with ConnectionManager(connection_config=conn_conf) as db:
                    for _ in range(10):
                        db.upsert_docs_batch(
                            [{"id": "A", "by": "thread1"}],
                            "Deadlock",
                            match_keys=["id"],
                        )
                        db.upsert_docs_batch(
                            [{"id": "B", "by": "thread1"}],
                            "Deadlock",
                            match_keys=["id"],
                        )
            except Exception as e:
                errors.append(str(e))

        def update_b_then_a():
            """Update node B then node A in opposite order to provoke deadlock."""
            try:
                with ConnectionManager(connection_config=conn_conf) as db:
                    for _ in range(10):
                        db.upsert_docs_batch(
                            [{"id": "B", "by": "thread2"}],
                            "Deadlock",
                            match_keys=["id"],
                        )
                        db.upsert_docs_batch(
                            [{"id": "A", "by": "thread2"}],
                            "Deadlock",
                            match_keys=["id"],
                        )
            except Exception as e:
                errors.append(str(e))

        t1 = threading.Thread(target=update_a_then_b, daemon=True)
        t2 = threading.Thread(target=update_b_then_a, daemon=True)

        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        # Should complete without deadlock
        assert not t1.is_alive(), "Thread 1 appears deadlocked"
        assert not t2.is_alive(), "Thread 2 appears deadlocked"

    def test_phantom_read_scenario(self, conn_conf, test_graph_name, clean_db):
        """Scenario that could cause phantom reads."""
        _ = clean_db
        phantoms_detected = []

        def inserter():
            """Insert 100 documents sequentially to create growing dataset."""
            with ConnectionManager(connection_config=conn_conf) as db:
                for i in range(100):
                    db.upsert_docs_batch(
                        [{"id": f"phantom_{i}"}], "Phantom", match_keys=["id"]
                    )

        def reader():
            """Count documents repeatedly to detect non-monotonic phantom reads."""
            with ConnectionManager(connection_config=conn_conf) as db:
                counts = []
                for _ in range(20):
                    count = db.aggregate("Phantom", AggregationType.COUNT)
                    counts.append(count)
                # Check for non-monotonic reads (would indicate phantoms)
                for i in range(1, len(counts)):
                    if counts[i] < counts[i - 1]:
                        phantoms_detected.append((counts[i - 1], counts[i]))

        t1 = threading.Thread(target=inserter, daemon=True)
        t2 = threading.Thread(target=reader, daemon=True)

        t1.start()
        t2.start()
        # Bounded like the sibling deadlock test above: this class exists to catch
        # a hung backend, so it must not itself hang the run when it finds one.
        t1.join(timeout=30)
        t2.join(timeout=30)

        assert not t1.is_alive(), "Inserter thread appears stuck"
        assert not t2.is_alive(), "Reader thread appears stuck"

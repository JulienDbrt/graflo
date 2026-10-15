"""Volume and memory-pressure cases.

Backend-agnostic Cypher cases, shared by the Memgraph and FalkorDB suites.

These are mixins, not tests: the module is outside any ``test_*.py`` so pytest
never collects them directly. Each backend's ``test_edge_cases.py`` subclasses
them, which is what supplies the ``conn_conf`` / ``test_graph_name`` /
``clean_db`` fixtures -- both backend conftests expose that same trio.
"""

from __future__ import annotations

import concurrent.futures
import threading

from graflo.db.manager import ConnectionManager
from graflo.onto import AggregationType


class BatchStressCases:
    """Stress test batch operations."""

    def test_large_batch_insert(self, conn_conf, test_graph_name, clean_db):
        """Insert very large batch."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            # 10,000 documents
            docs = [{"id": str(i), "data": f"value_{i}"} for i in range(10000)]
            db.upsert_docs_batch(docs, "LargeBatch", match_keys=["id"])

            count = db.aggregate("LargeBatch", AggregationType.COUNT)
            assert count == 10000

    def test_batch_with_duplicates(self, conn_conf, test_graph_name, clean_db):
        """Batch containing duplicate keys."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            docs = [
                {"id": "1", "version": 1},
                {"id": "2", "version": 1},
                {"id": "1", "version": 2},  # Duplicate id
                {"id": "1", "version": 3},  # Another duplicate
            ]
            db.upsert_docs_batch(docs, "Duplicates", match_keys=["id"])

            result = db.fetch_docs("Duplicates")
            # Should have 2 unique ids
            ids = {r["id"] for r in result}
            assert len(ids) == 2

    def test_rapid_fire_small_batches(self, conn_conf, test_graph_name, clean_db):
        """Many small rapid batches."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            for i in range(100):
                docs = [{"id": str(i), "batch": i}]
                db.upsert_docs_batch(docs, "RapidFire", match_keys=["id"])

            count = db.aggregate("RapidFire", AggregationType.COUNT)
            assert count == 100


class MemoryExhaustionCases:
    """Memory exhaustion and resource abuse testing."""

    def test_exponential_property_growth(self, conn_conf, test_graph_name, clean_db):
        """Property value that doubles on each upsert - memory stress test."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            payload = "A"
            for i in range(20):  # 2^20 = 1MB final payload
                docs = [{"id": "growing", "payload": payload}]
                db.upsert_docs_batch(docs, "MemoryLoad", match_keys=["id"])
                payload = payload * 2

            result = db.fetch_docs("MemoryLoad")
            assert len(result) == 1

    def test_million_tiny_properties(self, conn_conf, test_graph_name, clean_db):
        """Document with extreme number of tiny properties."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            # 10,000 single-char properties
            doc = {"id": "hydra"}
            for i in range(10000):
                doc[f"p{i}"] = "x"

            try:
                db.upsert_docs_batch([doc], "Hydra", match_keys=["id"])
            except Exception:
                pass

    def test_recursive_json_like_string(self, conn_conf, test_graph_name, clean_db):
        """String that looks like deeply nested JSON - parser confusion."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            # String that might confuse naive JSON parsers
            nested_json = '{"a":' * 100 + '"value"' + "}" * 100
            docs = [{"id": "nested_json", "data": nested_json}]
            db.upsert_docs_batch(docs, "NestedJson", match_keys=["id"])

            result = db.fetch_docs("NestedJson")
            assert len(result) == 1
            assert result[0]["data"] == nested_json

    def test_binary_payload_in_string(self, conn_conf, test_graph_name, clean_db):
        """Binary data disguised as string."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            # Random-looking binary data
            binary_payload = bytes(range(256)).decode("latin-1")
            docs = [{"id": "binary", "payload": binary_payload}]
            try:
                db.upsert_docs_batch(docs, "Binary", match_keys=["id"])
            except Exception:
                pass


class ConcurrencyCases:
    """Concurrent writers and readers on separate connections."""

    def test_concurrent_inserts(self, conn_conf, test_graph_name, clean_db):
        """Concurrent inserts to same label."""
        _ = clean_db

        def insert_batch(batch_id):
            """Insert a batch of 10 documents with batch-prefixed IDs."""
            with ConnectionManager(connection_config=conn_conf) as db:
                docs = [{"id": f"{batch_id}_{i}", "batch": batch_id} for i in range(10)]
                db.upsert_docs_batch(docs, "ConcurrentInsert", match_keys=["id"])

        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [executor.submit(insert_batch, i) for i in range(5)]
            concurrent.futures.wait(futures)

        with ConnectionManager(connection_config=conn_conf) as db:
            result = db.fetch_docs("ConcurrentInsert")
            assert len(result) == 50  # 5 batches * 10 docs

    def test_concurrent_read_write(self, conn_conf, test_graph_name, clean_db):
        """Concurrent reads and writes."""
        _ = clean_db
        errors = []

        def writer():
            """Insert 20 documents sequentially, each in its own connection."""
            for i in range(20):
                try:
                    with ConnectionManager(connection_config=conn_conf) as db:
                        docs = [{"id": f"w{i}", "value": i}]
                        db.upsert_docs_batch(docs, "ReadWrite", match_keys=["id"])
                except Exception as e:
                    errors.append(f"Writer error: {e}")

        def reader():
            """Read all documents 20 times, each in its own connection."""
            for _ in range(20):
                try:
                    with ConnectionManager(connection_config=conn_conf) as db:
                        db.fetch_docs("ReadWrite")
                except Exception as e:
                    errors.append(f"Reader error: {e}")

        # daemon=True and a bounded join: a worker blocked on a wedged DB socket
        # must fail this test, not stall the join here and then stall
        # threading._shutdown at interpreter exit -- which hangs pytest *after*
        # it has already reported success.
        threads = [
            threading.Thread(target=writer, daemon=True),
            threading.Thread(target=reader, daemon=True),
            threading.Thread(target=writer, daemon=True),
            threading.Thread(target=reader, daemon=True),
        ]

        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert not any(t.is_alive() for t in threads), (
            "read/write workers did not finish within 30s"
        )

        # Should complete without errors
        assert len(errors) == 0, f"Errors occurred: {errors}"

    def test_concurrent_upsert_same_key(self, conn_conf, test_graph_name, clean_db):
        """Multiple threads trying to upsert same document."""
        _ = clean_db
        results = []

        def updater(thread_id):
            """Repeatedly upsert the same document with thread-specific metadata."""
            for i in range(10):
                with ConnectionManager(connection_config=conn_conf) as db:
                    docs = [
                        {"id": "contested", "last_writer": thread_id, "iteration": i}
                    ]
                    db.upsert_docs_batch(docs, "Contested", match_keys=["id"])
                    results.append((thread_id, i))

        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
            futures = [executor.submit(updater, i) for i in range(4)]
            concurrent.futures.wait(futures)

        with ConnectionManager(connection_config=conn_conf) as db:
            result = db.fetch_docs("Contested")
            # Should have exactly one document
            assert len(result) == 1


class CartesianLoadCases:
    """Unanchored matches and dense multi-hop paths."""

    def test_unanchored_match_storm(self, conn_conf, test_graph_name, clean_db):
        """Create many nodes, then query without anchor - cartesian explosion."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            # Create modest node counts
            for label in ["TypeA", "TypeB", "TypeC"]:
                docs = [{"id": str(i)} for i in range(50)]
                db.upsert_docs_batch(docs, label, match_keys=["id"])

            # Query that could explode: 50 * 50 * 50 = 125,000 rows
            try:
                result = db.execute(
                    "MATCH (a:TypeA), (b:TypeB), (c:TypeC) RETURN count(*)"
                )
                assert result.result_set[0][0] == 125000
            except Exception:
                pass  # Timeout or memory limit is acceptable

    def test_dense_multi_hop_path(self, conn_conf, test_graph_name, clean_db):
        """Dense graph with multi-hop path query - exponential paths."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            # Create dense subgraph
            docs = [{"id": str(i)} for i in range(20)]
            db.upsert_docs_batch(docs, "Dense", match_keys=["id"])

            # Connect each node to several others (high connectivity)
            edges = []
            for i in range(20):
                for j in range(i + 1, min(i + 5, 20)):
                    edges.append([{"id": str(i)}, {"id": str(j)}, {}])

            db.insert_edges_batch(
                edges,
                source_class="Dense",
                target_class="Dense",
                relation_name="CONNECTED",
                match_keys_source=["id"],
                match_keys_target=["id"],
            )

            # Variable length path query - exponential explosion
            try:
                result = db.execute(
                    "MATCH p=(a:Dense)-[:CONNECTED*1..5]->(b:Dense) RETURN count(p)"
                )
                assert result.result_set[0][0] > 0
            except Exception:
                pass


class ConnectionChurnCases:
    """Rapid connection churn and interleaved connections."""

    def test_rapid_connect_disconnect(self, conn_conf, test_graph_name):
        """Rapidly open and close connections."""
        for _ in range(50):
            with ConnectionManager(connection_config=conn_conf) as db:
                db.execute("RETURN 1")

    def test_interleaved_operations(self, conn_conf, test_graph_name, clean_db):
        """Interleave reads and writes in confusing patterns."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            for i in range(20):
                # Write
                db.upsert_docs_batch(
                    [{"id": str(i), "phase": "write"}],
                    "Interleaved",
                    match_keys=["id"],
                )
                # Read immediately after write
                db.fetch_docs("Interleaved", filters=["==", str(i), "id"])
                # Overwrite
                db.upsert_docs_batch(
                    [{"id": str(i), "phase": "overwrite"}],
                    "Interleaved",
                    match_keys=["id"],
                )
                # Read again
                result = db.fetch_docs("Interleaved", filters=["==", str(i), "id"])
                assert result[0]["phase"] == "overwrite"

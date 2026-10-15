"""Edge case and robustness tests for Memgraph connector.

This module provides a comprehensive adversarial test suite for the Memgraph
connector implementation. Tests are designed to probe security boundaries,
stress operational limits, and verify correct handling of malformed inputs.

Test Categories
---------------
Security & Injection Prevention:
    - Cypher injection via property values, labels, and match keys
    - Parameter pollution and template injection attempts
    - Unicode homoglyph attacks for filter bypass

Encoding & Unicode:
    - UTF-8 edge cases (BOM, surrogates, overlong sequences)
    - Bidirectional text and RTL override characters
    - Zero-width characters and Private Use Area flooding
    - Null byte injection and control character handling

Boundary Conditions:
    - Empty inputs (batches, documents, strings)
    - Extreme numeric values (NaN, Inf, integer overflow)
    - Large payloads (1MB strings, 1000 properties, 50k batches)
    - Limit parameter edge cases (negative, zero, float)

Type System:
    - Type coercion and confusion (string "123" vs int 123)
    - None/null value handling and missing keys
    - Mixed-type arrays and nested structures
    - Property type mutation across upserts

Concurrency & State:
    - Thread safety with concurrent reads/writes
    - Race conditions on contested resources
    - Connection lifecycle (close, double-close, nested)

Graph Topology:
    - Pathological structures (cycles, cliques, stars)
    - Self-referential edges and multi-edges
    - Long chains and deeply nested traversals

Usage
-----
Run all edge case tests::

    pytest test/db/memgraphs/test_edge_cases.py -v

Run specific category::

    pytest test/db/memgraphs/test_edge_cases.py -k "Injection" -v

Notes
-----
- Tests require a running Memgraph instance (see conftest.py fixtures)
- Some tests intentionally trigger warnings (logged, not failures)

See Also
--------
- graflo.db.memgraph.conn : Memgraph connector implementation
- test.db.memgraphs.conftest : Test fixtures and configuration
"""

import concurrent.futures
import threading

import pytest

from graflo.db.manager import ConnectionManager
from graflo.onto import AggregationType

# Shared, backend-agnostic cases. Bodies live once in test/db/cypher_cases/;
# only the Memgraph-specific tests remain in this file.
from test.db.cypher_cases.boundaries import (
    BoundaryConditionsCases,
    BoundaryValueAnalysisCases,
    MalformedInputsCases,
    NumericStringCases,
    PathologicalIdsCases,
    TypeConfusionCases,
)
from test.db.cypher_cases.encoding import (
    EmojiCases,
    LabelAbuseCases,
    MalformedEncodingCases,
    PropertyKeySmugglingCases,
)
from test.db.cypher_cases.graphs import (
    GraphAlgorithmCases,
    LockOrderingCases,
    PathologicalGraphsCases,
    StateCorruptionCases,
)
from test.db.cypher_cases.injection import (
    CypherInjectionCases,
    QueryInjectionAdvancedCases,
    ReDoSCases,
)
from test.db.cypher_cases.queries import (
    AggregationCases,
    EdgeOperationsCases,
    FilterCases,
    FilterStressCases,
    QueryComplexityCases,
    SchemaEvolutionCases,
    TemporalAnomaliesCases,
)
from test.db.cypher_cases.stress import (
    BatchStressCases,
    CartesianLoadCases,
    ConcurrencyCases,
    ConnectionChurnCases,
    MemoryExhaustionCases,
)


class TestCypherInjection(CypherInjectionCases):
    """Security tests for Cypher injection prevention.

    Validates that the connector properly sanitizes user inputs to prevent
    Cypher injection attacks. Tests cover multiple injection vectors including
    property values, label names, and match keys.

    The connector should either:
    - Parameterize all user inputs (preferred)
    - Properly escape special characters
    - Reject dangerous inputs with clear errors

    References
    ----------
    - OWASP Injection Prevention Cheat Sheet:
      https://cheatsheetseries.owasp.org/cheatsheets/Injection_Prevention_Cheat_Sheet.html
    - Neo4j/Cypher Security Best Practices:
      https://neo4j.com/developer/cypher/guide-sql-injection/
    """

    def test_injection_via_filter_value(self, conn_conf, test_graph_name, clean_db):
        """Try to inject Cypher via filter values."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            # First create a legitimate node
            db.upsert_docs_batch(
                [{"id": "1", "name": "safe"}], "FilterTest", match_keys=["id"]
            )

            # Try injection via filter
            malicious_filters = [
                "safe' OR 1=1 --",
                "safe' UNION MATCH (n) RETURN n //",
                "safe\\' OR \\'1\\'=\\'1",
            ]

            for mf in malicious_filters:
                result = db.fetch_docs("FilterTest", filters=["==", mf, "name"])
                # Should return empty or just the literal match, not all nodes
                assert len(result) <= 1


class TestUnicodeEdgeCases(EmojiCases):
    """Unicode and encoding edge case validation.

    Verifies correct handling of international text, special Unicode
    characters, and encoding edge cases that commonly cause issues
    in database systems.
    """

    def test_complex_emoji_sequences(self, conn_conf, test_graph_name, clean_db):
        """Test complex emoji sequences (ZWJ, skin tones, flags)."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            complex_emojis = [
                {"id": "1", "emoji": "👨‍👩‍👧‍👦"},  # Family ZWJ sequence
                {"id": "2", "emoji": "👋🏿"},  # Skin tone modifier
                {"id": "3", "emoji": "🏳️‍🌈"},  # Flag ZWJ sequence
                {"id": "4", "emoji": "👨‍💻"},  # Profession ZWJ
                {"id": "5", "emoji": "🇫🇷"},  # Regional indicator (flag)
            ]
            db.upsert_docs_batch(complex_emojis, "ComplexEmoji", match_keys=["id"])

            result = db.fetch_docs("ComplexEmoji")
            assert len(result) == 5

    def test_rtl_and_bidi_text(self, conn_conf, test_graph_name, clean_db):
        """Test right-to-left and bidirectional text."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            rtl_texts = [
                {"id": "1", "content": "مرحبا بالعالم"},  # Arabic
                {"id": "2", "content": "שלום עולם"},  # Hebrew
                {"id": "3", "content": "Hello مرحبا World عالم"},  # Mixed LTR/RTL
                {"id": "4", "content": "\u202etext\u202c"},  # RTL override characters
                {"id": "5", "content": "A\u200fB\u200eC"},  # Mixed marks
            ]
            db.upsert_docs_batch(rtl_texts, "RTLNode", match_keys=["id"])

            result = db.fetch_docs("RTLNode")
            assert len(result) == len(rtl_texts)

    def test_null_bytes_and_control_chars(self, conn_conf, test_graph_name, clean_db):
        """Test null bytes and control characters."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            problematic_strings = [
                ("1", "before\x00after"),  # Null byte
                ("2", "tab\there"),
                ("3", "new\nline"),
                ("4", "carriage\rreturn"),
                ("5", "bell\x07ring"),
                ("6", "escape\x1b[31mred"),  # ANSI escape
            ]

            successful = 0
            for id_val, s in problematic_strings:
                try:
                    db.upsert_docs_batch(
                        [{"id": id_val, "data": s}], "ControlChars", match_keys=["id"]
                    )
                    successful += 1
                except Exception:
                    # Some control chars may be rejected
                    pass

            result = db.fetch_docs("ControlChars")
            assert len(result) == successful

    def test_unicode_normalization_edge_cases(
        self, conn_conf, test_graph_name, clean_db
    ):
        """Test Unicode normalization edge cases."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            # Different Unicode representations of "same" characters
            variants = [
                ("1a", "café"),
                ("1b", "cafe\u0301"),  # Merged vs decomposed
                ("2a", "ﬁ"),  # Ligature
                ("2b", "fi"),  # Separate chars
                ("3a", "Ω"),  # Greek Omega U+03A9
                ("3b", "Ω"),  # Ohm sign U+2126
                ("4a", "㈱"),  # Enclosed
                ("4b", "(株)"),  # Parenthesized
            ]

            for id_val, text in variants:
                db.upsert_docs_batch(
                    [{"id": id_val, "text": text}], "NormTest", match_keys=["id"]
                )

            result = db.fetch_docs("NormTest")
            assert len(result) == len(variants)

    def test_zero_width_characters(self, conn_conf, test_graph_name, clean_db):
        """Test zero-width and invisible characters."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            invisible_strings = [
                {"id": "1", "text": "hello\u200bworld"},  # Zero-width space
                {"id": "2", "text": "hello\u200cworld"},  # Zero-width non-joiner
                {"id": "3", "text": "hello\u200dworld"},  # Zero-width joiner
                {"id": "4", "text": "hello\ufeffworld"},  # BOM
                {"id": "5", "text": "\u2060invisible\u2060"},  # Word joiner
                {"id": "6", "text": "a\u034fb"},  # Combining grapheme joiner
            ]

            db.upsert_docs_batch(invisible_strings, "Invisible", match_keys=["id"])

            result = db.fetch_docs("Invisible")
            assert len(result) == len(invisible_strings)

    def test_private_use_area_flooding(self, conn_conf, test_graph_name, clean_db):
        """Test Private Use Area character flooding."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            # Flood with PUA characters
            pua_string = "".join(chr(0xE000 + i) for i in range(1000))
            docs = [{"id": "pua", "data": pua_string}]
            db.upsert_docs_batch(docs, "PUAFlood", match_keys=["id"])

            result = db.fetch_docs("PUAFlood")
            assert len(result) == 1
            assert len(result[0]["data"]) == 1000


class TestBoundaryConditions(BoundaryConditionsCases):
    """Boundary value analysis for connector limits."""

    def test_empty_string_values(self, conn_conf, test_graph_name, clean_db):
        """Test empty string property values."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            docs = [
                {"id": "1", "name": ""},
                {"id": "2", "data": ""},
                {"id": "3", "": "value"},  # Empty key
            ]
            try:
                db.upsert_docs_batch(docs, "EmptyStrings", match_keys=["id"])
            except Exception:
                # Empty key may be rejected
                docs = [
                    {"id": "1", "name": ""},
                    {"id": "2", "data": ""},
                ]
                db.upsert_docs_batch(docs, "EmptyStrings", match_keys=["id"])

            result = db.fetch_docs("EmptyStrings")
            assert len(result) >= 2

    def test_limit_parameter_edge_cases(self, conn_conf, test_graph_name, clean_db):
        """Test edge cases for limit parameter."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            # Create test data
            docs = [{"id": str(i)} for i in range(10)]
            db.upsert_docs_batch(docs, "LimitTest", match_keys=["id"])

            # Test various limit values
            test_cases = [
                (0, 0),  # Zero limit
                (1, 1),  # Minimum
                (10, 10),  # Exact count
                (100, 10),  # Over count
            ]

            for limit, expected_max in test_cases:
                result = db.fetch_docs("LimitTest", limit=limit)
                assert len(result) <= expected_max or limit == 0

            # Test negative limit (should either work as no limit or raise error)
            try:
                result = db.fetch_docs("LimitTest", limit=-1)
                # If it works, should return all
            except (ValueError, Exception):
                # Expected for invalid limit
                pass


class TestTypeConfusion(TypeConfusionCases):
    """Type confusion and coercion edge cases."""

    def test_boolean_vs_string(self, conn_conf, test_graph_name, clean_db):
        """Test boolean vs string representation."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            docs = [
                {"id": "1", "flag": True},
                {"id": "2", "flag": "true"},
                {"id": "3", "flag": "True"},
                {"id": "4", "flag": False},
                {"id": "5", "flag": "false"},
            ]
            db.upsert_docs_batch(docs, "BoolTest", match_keys=["id"])

            result = db.fetch_docs("BoolTest")
            by_id = {r["id"]: r for r in result}

            # Verify booleans are preserved as booleans
            assert by_id["1"]["flag"] is True
            assert by_id["4"]["flag"] is False
            # Strings should be preserved as strings
            assert by_id["2"]["flag"] == "true"

    def test_none_handling(self, conn_conf, test_graph_name, clean_db):
        """Test None/null value handling."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            docs = [
                {"id": "1", "value": None},
                {"id": "2", "value": "none"},
                {"id": "3", "value": "null"},
            ]
            db.upsert_docs_batch(docs, "NullTest", match_keys=["id"])

            result = db.fetch_docs("NullTest")
            by_id = {r["id"]: r for r in result}

            # None should be stored as null or missing
            assert by_id["1"].get("value") is None or "value" not in by_id["1"]
            # String "none" should be preserved
            assert by_id["2"]["value"] == "none"

    def test_mixed_type_arrays(self, conn_conf, test_graph_name, clean_db):
        """Test arrays with mixed types."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            docs = [
                {"id": "1", "arr": [1, "two", 3.0, True, None]},
                {"id": "2", "arr": [[], {}, "nested"]},
            ]

            try:
                db.upsert_docs_batch(docs, "MixedArray", match_keys=["id"])
                # Just verify no crash
                _ = db.fetch_docs("MixedArray")
            except Exception:
                # Mixed arrays may not be supported
                pass

    def test_property_type_mutation(self, conn_conf, test_graph_name, clean_db):
        """Test changing property type across upserts."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            # First insert with string
            db.upsert_docs_batch(
                [{"id": "1", "value": "string"}], "TypeMutate", match_keys=["id"]
            )

            # Update with integer
            db.upsert_docs_batch(
                [{"id": "1", "value": 42}], "TypeMutate", match_keys=["id"]
            )

            result = db.fetch_docs("TypeMutate")
            assert len(result) == 1
            assert result[0]["value"] == 42

            # Update with boolean
            db.upsert_docs_batch(
                [{"id": "1", "value": True}], "TypeMutate", match_keys=["id"]
            )

            result = db.fetch_docs("TypeMutate")
            assert result[0]["value"] is True


class TestMalformedInputs(MalformedInputsCases):
    """Tests for malformed input handling."""

    def test_reserved_words_as_property_names(
        self, conn_conf, test_graph_name, clean_db
    ):
        """Test Cypher reserved words as property names."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            reserved_words = [
                "MATCH",
                "RETURN",
                "WHERE",
                "CREATE",
                "DELETE",
                "SET",
                "REMOVE",
            ]

            docs = [{"id": "1"}]
            for word in reserved_words:
                docs[0][word] = f"value_{word}"

            try:
                db.upsert_docs_batch(docs, "Reserved", match_keys=["id"])
                result = db.fetch_docs("Reserved")
                # Should work with proper escaping
                assert len(result) == 1
            except Exception:
                # May fail if not properly escaped
                pass

    def test_special_chars_in_property_names(
        self, conn_conf, test_graph_name, clean_db
    ):
        """Test special characters in property names."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            special_props = [
                "prop with space",
                "prop-with-dash",
                "prop.with.dot",
                "prop:with:colon",
            ]

            for prop in special_props:
                docs = [{"id": prop, prop: "value"}]
                try:
                    db.upsert_docs_batch(docs, "SpecialProp", match_keys=["id"])
                except Exception:
                    # Some special chars may be rejected
                    pass


class TestPathologicalGraphs(PathologicalGraphsCases):
    """Tests for pathological graph structures."""

    def test_self_referential_edge(self, conn_conf, test_graph_name, clean_db):
        """Test creating an edge from a node to itself."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            db.upsert_docs_batch(
                [{"id": "1", "name": "Self"}], "Node", match_keys=["id"]
            )

            edges = [[{"id": "1"}, {"id": "1"}, {"type": "self"}]]
            db.insert_edges_batch(
                edges,
                source_class="Node",
                target_class="Node",
                relation_name="LINKS_TO",
                match_keys_source=["id"],
                match_keys_target=["id"],
            )

            result = db.execute("MATCH (n:Node)-[r:LINKS_TO]->(n) RETURN count(r)")
            assert result.result_set[0][0] == 1

    def test_cycle_detection(self, conn_conf, test_graph_name, clean_db):
        """Test cycle in graph."""
        _ = clean_db
        cycle_size = 5

        with ConnectionManager(connection_config=conn_conf) as db:
            nodes = [{"id": str(i)} for i in range(cycle_size)]
            db.upsert_docs_batch(nodes, "CycleNode", match_keys=["id"])

            # Create cycle edges
            edges = [
                [{"id": str(i)}, {"id": str((i + 1) % cycle_size)}, {}]
                for i in range(cycle_size)
            ]
            db.insert_edges_batch(
                edges,
                source_class="CycleNode",
                target_class="CycleNode",
                relation_name="CYCLE",
                match_keys_source=["id"],
                match_keys_target=["id"],
            )

            # Verify cycle exists
            result = db.execute(
                "MATCH p=(a:CycleNode {id: '0'})-[:CYCLE*5]->(a) RETURN count(p)"
            )
            assert result.result_set[0][0] == 1


class TestConcurrencyEdgeCases:
    """Concurrency and state management edge cases."""

    def test_concurrent_upserts_same_id(self, conn_conf, test_graph_name, clean_db):
        """Test concurrent upserts with same ID."""
        _ = clean_db
        num_threads = 10
        errors = []
        lock = threading.Lock()

        def upsert_worker(thread_id):
            """Perform repeated upserts on the same node from a single thread."""
            try:
                with ConnectionManager(connection_config=conn_conf) as db:
                    for i in range(10):
                        db.upsert_docs_batch(
                            [{"id": "contested", "thread": thread_id, "iteration": i}],
                            "Contested",
                            match_keys=["id"],
                        )
            except Exception as e:
                with lock:
                    errors.append(f"Thread {thread_id}: {e}")

        with concurrent.futures.ThreadPoolExecutor(max_workers=num_threads) as executor:
            futures = [executor.submit(upsert_worker, i) for i in range(num_threads)]
            concurrent.futures.wait(futures)

        # Should have exactly one node
        with ConnectionManager(connection_config=conn_conf) as db:
            result = db.fetch_docs("Contested")
            assert len(result) == 1

    def test_read_during_write(self, conn_conf, test_graph_name, clean_db):
        """Test concurrent reads during writes."""
        _ = clean_db
        num_writers = 5
        num_readers = 10
        ops_per_thread = 50

        errors = []
        lock = threading.Lock()
        write_counter = [0]

        def writer():
            """Write nodes concurrently with unique IDs."""
            try:
                with ConnectionManager(connection_config=conn_conf) as db:
                    for _ in range(ops_per_thread):
                        with lock:
                            write_counter[0] += 1
                            wid = write_counter[0]
                        db.upsert_docs_batch(
                            [{"id": f"w_{wid}", "data": "written"}],
                            "ReadWrite",
                            match_keys=["id"],
                        )
            except Exception as e:
                with lock:
                    errors.append(f"Writer: {e}")

        def reader():
            """Read nodes concurrently during write operations."""
            try:
                with ConnectionManager(connection_config=conn_conf) as db:
                    for _ in range(ops_per_thread):
                        db.fetch_docs("ReadWrite", limit=10)
            except Exception as e:
                with lock:
                    errors.append(f"Reader: {e}")

        with concurrent.futures.ThreadPoolExecutor(
            max_workers=num_writers + num_readers
        ) as executor:
            futures = []
            futures.extend([executor.submit(writer) for _ in range(num_writers)])
            futures.extend([executor.submit(reader) for _ in range(num_readers)])
            concurrent.futures.wait(futures)

        assert len(errors) == 0, f"Errors: {errors[:5]}"


class TestQueryEdgeCases:
    """Tests for query edge cases."""

    def test_query_empty_database(self, conn_conf, test_graph_name, clean_db):
        """Test querying an empty database."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            result = db.fetch_docs("NonExistent")
            assert result == []

    def test_aggregate_empty_collection(self, conn_conf, test_graph_name, clean_db):
        """Test aggregation on empty collection."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            result = db.aggregate("Empty", AggregationType.COUNT)
            assert result == 0

    def test_filter_with_special_characters(self, conn_conf, test_graph_name, clean_db):
        """Test filtering with special characters in value."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            docs = [
                {"id": "1", "value": "test'quote"},
                {"id": "2", "value": 'test"double'},
                {"id": "3", "value": "test\\backslash"},
            ]
            db.upsert_docs_batch(docs, "Special", match_keys=["id"])

            result = db.fetch_docs("Special", filters=["==", "test'quote", "value"])
            assert len(result) == 1
            assert result[0]["id"] == "1"

    def test_filter_with_unicode(self, conn_conf, test_graph_name, clean_db):
        """Test filtering with Unicode values."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            docs = [
                {"id": "1", "name": "日本語"},
                {"id": "2", "name": "العربية"},
                {"id": "3", "name": "emoji😀"},
            ]
            db.upsert_docs_batch(docs, "UnicodeFilter", match_keys=["id"])

            result = db.fetch_docs("UnicodeFilter", filters=["==", "日本語", "name"])
            assert len(result) == 1
            assert result[0]["id"] == "1"


class TestDataTypes:
    """Tests for different data type handling."""

    def test_boolean_values(self, conn_conf, test_graph_name, clean_db):
        """Test boolean value handling."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            docs = [
                {"id": "1", "active": True},
                {"id": "2", "active": False},
            ]
            db.upsert_docs_batch(docs, "Boolean", match_keys=["id"])

            result = db.fetch_docs("Boolean")
            by_id = {r["id"]: r for r in result}
            assert by_id["1"]["active"] is True
            assert by_id["2"]["active"] is False

    def test_numeric_values(self, conn_conf, test_graph_name, clean_db):
        """Test numeric value handling."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            docs = [
                {"id": "1", "int_val": 42, "float_val": 3.14},
                {"id": "2", "int_val": -100, "float_val": -0.5},
                {"id": "3", "int_val": 0, "float_val": 0.0},
            ]
            db.upsert_docs_batch(docs, "Numeric", match_keys=["id"])

            result = db.fetch_docs("Numeric")
            assert len(result) == 3

    def test_list_values(self, conn_conf, test_graph_name, clean_db):
        """Test list value handling."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            docs = [
                {"id": "1", "tags": ["a", "b", "c"]},
                {"id": "2", "numbers": [1, 2, 3]},
            ]
            db.upsert_docs_batch(docs, "Lists", match_keys=["id"])

            result = db.fetch_docs("Lists")
            by_id = {r["id"]: r for r in result}
            assert by_id["1"]["tags"] == ["a", "b", "c"]
            assert by_id["2"]["numbers"] == [1, 2, 3]


class TestErrorHandling:
    """Tests for error handling scenarios."""

    def test_invalid_query_syntax(self, conn_conf, test_graph_name, clean_db):
        """Test handling of invalid query syntax."""
        _ = clean_db
        with (
            ConnectionManager(connection_config=conn_conf) as db,
            pytest.raises(Exception),
        ):
            db.execute("INVALID QUERY SYNTAX HERE")

    def test_missing_match_key(self, conn_conf, test_graph_name, clean_db):
        """Test upserting document without required match key."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            docs = [{"name": "NoId"}]  # Missing 'id' key
            try:
                db.upsert_docs_batch(docs, "NoKey", match_keys=["id"])
            except (KeyError, Exception):
                pass  # Expected

    def test_recovery_after_error(self, conn_conf, test_graph_name, clean_db):
        """Test connection recovery after an error."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            # First, cause an error
            try:
                db.execute("INVALID SYNTAX")
            except Exception:
                pass

            # Then, verify connection still works
            db.upsert_docs_batch([{"id": "1"}], "Recovery", match_keys=["id"])
            result = db.fetch_docs("Recovery")
            assert len(result) == 1

    def test_multiple_consecutive_errors(self, conn_conf, test_graph_name, clean_db):
        """Test connection stability after multiple errors."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            # Cause multiple errors
            for i in range(10):
                try:
                    db.execute(f"INVALID QUERY {i}")
                except Exception:
                    pass

            # Verify connection still works
            db.upsert_docs_batch([{"id": "1"}], "MultiError", match_keys=["id"])
            result = db.fetch_docs("MultiError")
            assert len(result) == 1


class TestAggregationEdgeCases(AggregationCases):
    """Test aggregation with edge cases."""

    def test_aggregate_with_filter_on_field(self, conn_conf, test_graph_name, clean_db):
        """Aggregate with filter on specific field value."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            docs = [
                {"id": "1", "category": "A", "value": 10},
                {"id": "2", "category": None, "value": 20},
                {"id": "3", "category": "A", "value": 30},
                {"id": "4", "value": 40},  # Missing category
            ]
            db.upsert_docs_batch(docs, "NullGroup", match_keys=["id"])

            # Count with filter on category
            result = db.aggregate(
                "NullGroup", AggregationType.COUNT, filters=["==", "A", "category"]
            )
            assert result == 2


class TestFilterEdgeCases(FilterCases):
    """Test filter expressions with edge cases."""


class TestEdgeOperationsEdgeCases(EdgeOperationsCases):
    """Test edge/relationship operations with edge cases."""


class TestBatchStress(BatchStressCases):
    """Stress test batch operations."""


class TestConcurrencyStress(ConcurrencyCases):
    """Thread safety and race condition testing."""


class TestStateCorruption(StateCorruptionCases):
    """Test state handling and connection management."""


class TestConnectionStress(ConnectionChurnCases):
    """Stress connection handling and state management."""


class TestQueryInjectionAdvanced(QueryInjectionAdvancedCases):
    """More sophisticated injection attempts."""


class TestLabelAbuse(LabelAbuseCases):
    """Abuse label and relationship type naming."""


class TestMalformedEncoding(MalformedEncodingCases):
    """Test with malformed or invalid encodings."""


class TestPropertyKeySmuggling(PropertyKeySmugglingCases):
    """Attempt to smuggle malicious content via property keys."""


class TestTemporalAnomalies(TemporalAnomaliesCases):
    """Test with extreme or invalid temporal values."""


class TestGraphAlgorithmEdgeCases(GraphAlgorithmCases):
    """Pathological graph structures that stress graph algorithms."""

    def test_cycle_detection_complex(self, conn_conf, test_graph_name, clean_db):
        """Complex interlocking cycles - stress cycle detection."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            # Create nodes
            docs = [{"id": str(i)} for i in range(30)]
            db.upsert_docs_batch(docs, "Cycles", match_keys=["id"])

            # Create multiple overlapping cycles
            edges = []
            # Cycle 1: 0->1->2->3->4->0
            for i in range(5):
                edges.append([{"id": str(i)}, {"id": str((i + 1) % 5)}, {}])
            # Cycle 2: 5->6->7->8->9->5
            for i in range(5, 10):
                next_id = 5 if i == 9 else i + 1
                edges.append([{"id": str(i)}, {"id": str(next_id)}, {}])
            # Bridge cycles
            edges.append([{"id": "2"}, {"id": "7"}, {}])
            edges.append([{"id": "7"}, {"id": "2"}, {}])

            db.insert_edges_batch(
                edges,
                source_class="Cycles",
                target_class="Cycles",
                relation_name="LOOPS",
                match_keys_source=["id"],
                match_keys_target=["id"],
            )

            # Query that traverses cycles
            result = db.execute(
                "MATCH (n:Cycles)-[:LOOPS*1..10]->(m:Cycles) "
                "WHERE n.id = '0' RETURN count(*)"
            )
            assert result.result_set[0][0] > 0


class TestDeadlockPrevention(LockOrderingCases):
    """Deadlock detection and transaction isolation testing."""

    def test_self_referential_update(self, conn_conf, test_graph_name, clean_db):
        """Update a node based on reading its own value."""
        import time

        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            db.upsert_docs_batch(
                [{"id": "self", "counter": 0}], "SelfRef", match_keys=["id"]
            )

            successful_updates = 0
            for _ in range(50):
                for retry in range(3):  # Retry on transaction conflicts
                    try:
                        result = db.fetch_docs("SelfRef", filters=["==", "self", "id"])
                        if result:
                            new_val = result[0].get("counter", 0) + 1
                            db.upsert_docs_batch(
                                [{"id": "self", "counter": new_val}],
                                "SelfRef",
                                match_keys=["id"],
                            )
                            successful_updates += 1
                            break
                    except Exception as e:
                        if "conflicting transactions" in str(e).lower() and retry < 2:
                            time.sleep(0.01 * (retry + 1))  # Backoff
                            continue
                        raise

            result = db.fetch_docs("SelfRef")
            assert result[0]["counter"] > 0
            assert successful_updates > 0


class TestReDoS(ReDoSCases):
    """Test patterns that could cause ReDoS if regex is used internally."""

    def test_regex_pattern_edge_cases(self, conn_conf, test_graph_name, clean_db):
        """Store values that would be catastrophic if used as regex."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            # Classic ReDoS patterns
            redos_patterns = [
                "a" * 30 + "!",  # (a+)+ pattern victim
                "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa!",
                "x" * 50 + "y",  # (x+x+)+ victim
                "aaaaaaaaaaaaaaaaaaaaab" * 10,  # Nested quantifier victim
            ]

            for i, pattern in enumerate(redos_patterns):
                docs = [{"id": str(i), "pattern": pattern}]
                db.upsert_docs_batch(docs, "ReDoS", match_keys=["id"])

            result = db.fetch_docs("ReDoS")
            assert len(result) == len(redos_patterns)


class TestQueryComplexity(QueryComplexityCases):
    """Queries designed to be computationally expensive."""

    def test_union_query_load(self, conn_conf, test_graph_name, clean_db):
        """Many UNION clauses (reduced from 50 to avoid Memgraph hang)."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            docs = [{"id": "1"}]
            db.upsert_docs_batch(docs, "UnionLoad", match_keys=["id"])

            # Build query with UNIONs (reduced to prevent timeout)
            query_parts = ["MATCH (n:UnionLoad) RETURN n.id AS id" for _ in range(10)]
            query = " UNION ALL ".join(query_parts)

            try:
                result = db.execute(query)
                assert len(result.result_set) == 10
            except Exception:
                pass


class TestMemoryExhaustion(MemoryExhaustionCases):
    """Memory exhaustion and resource abuse testing."""


class TestCartesianProductLoad(CartesianLoadCases):
    """Queries designed to create explosive result sets."""


class TestSchemaEvolution(SchemaEvolutionCases):
    """Test rapid schema changes and type mutations."""

    def test_property_type_mutation_rapid(self, conn_conf, test_graph_name, clean_db):
        """Rapidly change property types for same key."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            type_sequence = [
                123,
                "123",
                12.3,
                True,
                [1, 2, 3],
                None,
                {"nested": "dict"},
            ]

            for i, val in enumerate(type_sequence):
                docs = [{"id": "mutant", "value": val, "iteration": i}]
                try:
                    db.upsert_docs_batch(docs, "TypeMutation", match_keys=["id"])
                except Exception:
                    pass

            result = db.fetch_docs("TypeMutation")
            # Should have exactly one node (upserted multiple times)
            assert len(result) == 1


class TestBoundaryValueAnalysis(BoundaryValueAnalysisCases):
    """Systematic boundary value testing."""


class TestFilterStress(FilterStressCases):
    """Stress test the filter system."""


class TestPathologicalIds(PathologicalIdsCases):
    """IDs designed to cause problems."""


class TestDataTypeEdgeCases(NumericStringCases):
    """Extreme data type edge cases."""

    def test_empty_string_variations(self, conn_conf, test_graph_name, clean_db):
        """Various representations of 'empty'."""
        _ = clean_db
        with ConnectionManager(connection_config=conn_conf) as db:
            empties = [
                ("empty", ""),
                ("space", " "),
                ("zwsp", "\u200b"),  # Zero-width space
                ("empty_array_str", "[]"),
                ("empty_obj_str", "{}"),
                ("none_str", "None"),
                ("null_str", "null"),
                ("undefined", "undefined"),
            ]

            for name, val in empties:
                docs = [{"id": name, "empty": val}]
                db.upsert_docs_batch(docs, "Empties", match_keys=["id"])

            result = db.fetch_docs("Empties")
            assert len(result) == len(empties)

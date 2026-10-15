"""Engine traits the shared Cypher cases assert against.

Each backend conftest returns one ``CypherTraits`` from a session-scoped
``cypher_traits`` fixture. A shared case reads a trait instead of naming a
backend, so a field here is a real behavioural difference between engines.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CypherTraits:
    """Per-engine behaviour and performance floors for the shared cases.

    Attributes:
        connection_handle: Attribute of the live connection that holds the
            driver handle (checked to be set after connecting).
        upsert_null_removes_property: Upserting ``None`` drops the stored
            property; otherwise the property is kept with a null value.
        orders_mixed_types: ``ORDER BY`` over a mix of string and int values
            succeeds; otherwise the engine raises, so the cases skip ordering.
        min_single_insert_ops: Floor for single-document upserts per second.
        min_read_ops: Floor for ``fetch_docs`` calls per second.
        max_batch_sizes: Batch sizes probed by the max-batch-size limit test.
    """

    connection_handle: str
    upsert_null_removes_property: bool
    orders_mixed_types: bool
    min_single_insert_ops: int
    min_read_ops: int
    max_batch_sizes: tuple[int, ...]

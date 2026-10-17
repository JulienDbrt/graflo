"""Performance and load tests for the Memgraph connector.

Throughput, scalability, concurrency, batch sizing, sustained load, limits and
graph operations. Bodies live in ``test.db.cypher_cases.performance``; floors
come from the ``cypher_traits`` fixture in this directory's conftest. Every test
here is marked ``performance`` and runs only with ``--run-performance``.
"""

import pytest

from test.db.cypher_cases.performance import (
    BatchSizingCases,
    ConcurrentLoadCases,
    GraphOperationsLoadCases,
    LimitsCases,
    ScalabilityCases,
    SustainedLoadCases,
    ThroughputCases,
)

pytestmark = pytest.mark.performance


class TestThroughput(ThroughputCases):
    """Throughput tests - operations per second measurements."""


class TestScalability(ScalabilityCases):
    """Scalability tests - behavior with increasing data volumes."""


class TestConcurrency(ConcurrentLoadCases):
    """Concurrency tests - parallel access patterns."""


class TestBatchSizing(BatchSizingCases):
    """Tests to find optimal batch size."""


class TestSustainedLoad(SustainedLoadCases):
    """Sustained load tests - stability over time."""


class TestLimits(LimitsCases):
    """System limits tests."""


class TestGraphOperationsLoad(GraphOperationsLoadCases):
    """Graph-specific operation load tests."""

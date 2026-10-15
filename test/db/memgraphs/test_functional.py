"""Functional tests for the Memgraph connector.

Data coherence, relationships, ETL scenarios, query semantics and transactional
robustness. Bodies live in ``test.db.cypher_cases.functional``; engine-specific
outcomes come from the ``cypher_traits`` fixture in this directory's conftest.
"""

import pytest

from test.db.cypher_cases.functional import (
    CommonMistakesCases,
    DataCoherenceCases,
    DataQualityCases,
    ETLScenariosCases,
    FunctionalQueryCases,
    FunctionalSchemaEvolutionCases,
    MultiSourceSyncCases,
    OperationConsistencyCases,
    PerformancePitfallCases,
    PolymorphicRelationshipsCases,
    RelationshipsCases,
    TransactionalRobustnessCases,
    TraversalCases,
)


class TestDataCoherence(DataCoherenceCases):
    """Tests for data consistency in various update scenarios.

    These tests validate that the connector correctly handles complex
    data update patterns that commonly occur in production systems.
    """


class TestMultiSourceSync(MultiSourceSyncCases):
    """Tests for multi-source data synchronization scenarios."""


class TestRelationships(RelationshipsCases):
    """Tests for graph relationship operations."""


class TestPolymorphicRelationships(PolymorphicRelationshipsCases):
    """Tests for relationships with heterogeneous target types."""


class TestETLScenarios(ETLScenariosCases):
    """Tests for real-world ETL scenarios."""


class TestSchemaEvolution(FunctionalSchemaEvolutionCases):
    """Tests for schema migration scenarios."""


class TestQueryEdgeCases(FunctionalQueryCases):
    """Tests for query edge cases and unusual patterns."""


class TestTraversalEdgeCases(TraversalCases):
    """Tests for graph traversal edge cases."""


class TestTransactionalRobustness(TransactionalRobustnessCases):
    """Tests for transactional behavior and error recovery."""


@pytest.mark.performance
class TestPerformanceEdgeCases(PerformancePitfallCases):
    """Tests for performance-related edge cases."""


class TestCommonMistakes(CommonMistakesCases):
    """Tests documenting common user mistakes and their effects."""


class TestDataQuality(DataQualityCases):
    """Tests for data quality scenarios."""


class TestComplexOperationConsistency(OperationConsistencyCases):
    """Tests for consistency after complex operations."""

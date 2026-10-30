"""Local probes against an isolated FalkorDB container, never a shared graph."""

import json
import time
import uuid

from graflo.architecture.graph_types import Index
from graflo.architecture.schema import Schema
from graflo.connections.onto import FalkordbConfig
from graflo.db.falkordb.conn import FalkordbConnection


def emit(**values):
    print(json.dumps(values, default=str), flush=True)


for size, indexed in [(100, False), (1000, False), (50000, True)]:
    graph_name = "graflo_probe_" + uuid.uuid4().hex
    db = FalkordbConnection(FalkordbConfig(uri="redis://localhost:6379", database=graph_name))
    try:
        if indexed:
            db._add_index("Item", Index(fields=["id"]))
        started = time.monotonic()
        db.upsert_docs_batch([{"id": str(i)} for i in range(size)], "Item", ["id"])
        emit(kind="batch", size=size, indexed=indexed, seconds=time.monotonic() - started)
    finally:
        db.delete_database(graph_name)
        db.close()

graph_name = "graflo_probe_" + uuid.uuid4().hex
db = FalkordbConnection(FalkordbConfig(uri="redis://localhost:6379", database=graph_name))
try:
    schema = Schema.model_validate({
        "metadata": {"name": "composite"},
        "core_schema": {
            "vertex_config": {"vertices": [{"name": "person", "properties": ["tenant", "id", "name", "born"], "identity": ["tenant", "id"]}]},
            "edge_config": {"edges": []},
        },
        "db_profile": {"db_flavor": "falkordb", "vertex_indexes": {"person": [{"fields": ["name", "born"], "unique": True}]}},
    })
    for _ in range(2):
        db.define_indexes(schema)
    emit(kind="catalog", constraints=db.graph.list_constraints(), indexes=db.execute("CALL db.indexes()").result_set)
    db.upsert_docs_batch([
        {"tenant": "a", "id": "1", "name": "Alice", "born": 1990},
        {"tenant": "b", "id": "1", "name": "Alice", "born": 1991},
    ], "person", ["tenant", "id"])
    for label, query in [
        ("identity", "CREATE (:person {tenant: 'a', id: '1'})"),
        ("secondary", "CREATE (:person {tenant: 'c', id: '2', name: 'Alice', born: 1990})"),
    ]:
        try:
            db.execute(query)
        except Exception as error:
            emit(kind="constraint", name=label, rejected=True, error=str(error))
        else:
            emit(kind="constraint", name=label, rejected=False)
    emit(kind="rows", rows=db.fetch_docs("person"))
    db.delete_graph_structure(vertex_types=["person"])
    emit(kind="deleted", constraints=db.graph.list_constraints(), rows=db.fetch_docs("person"))
finally:
    db.delete_database(graph_name)
    db.close()

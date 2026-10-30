"""Compare exact numeric parameter boundaries on both server engines."""

import json
import uuid

from graflo.connections.onto import FalkordbConfig
from graflo.db.falkordb.conn import FalkordbConnection

name = "graflo_numeric_probe_" + uuid.uuid4().hex
db = FalkordbConnection(FalkordbConfig(uri="redis://localhost:6379", database=name))
try:
    for value in [2**63-1, -(2**63), 2**63, -(2**63)-1, 2**64-1, 1e-308, 1e308, -0.0]:
        for mode, query, params in [
            ("scalar", "RETURN $value", {"value": value}),
            ("list", "UNWIND $data AS row RETURN row.value", {"data": [{"value": value}]}),
            ("literal", f"RETURN {value}", {}),
        ]:
            try:
                rows = db.execute(query, **params).result_set
                result = {"rows": rows}
            except Exception as error:
                result = {"error": str(error), "type": type(error).__name__}
            print(json.dumps({"value": value, "mode": mode, **result}), flush=True)
finally:
    db.delete_database(name)

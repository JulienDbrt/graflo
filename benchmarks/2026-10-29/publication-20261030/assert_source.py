"""Pytest provenance guard for validation runs using a mounted worktree."""

import hashlib
import json
import os
from pathlib import Path


def pytest_sessionstart(session):
    import graflo.architecture.graph_types.merge as fusion
    expected=Path(os.environ['EXPECTED_SOURCE_ROOT']).resolve()
    actual=Path(fusion.__file__).resolve()
    assert actual==expected/'graflo/architecture/graph_types/merge.py',(expected,actual)
    record={'module':str(actual),'sha256':hashlib.sha256(actual.read_bytes()).hexdigest()}
    path=Path(os.environ['SOURCE_AUDIT_OUT'])
    path=path.with_name(path.stem+'-'+str(os.getpid())+path.suffix)
    path.write_text(json.dumps(record)+'\n')

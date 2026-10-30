"""Check the actual imported connector and keep per-process provenance."""
import hashlib
import json
import os
from pathlib import Path

import graflo.db.falkordb.conn as module


def pytest_configure(config):
    source=Path(module.__file__).resolve()
    assert source==Path('/repo/graflo/db/falkordb/conn.py')
    digest=hashlib.sha256(source.read_bytes()).hexdigest()
    assert digest==os.environ['EXPECTED_CONNECTOR_SHA'],(source,digest)
    out=Path(os.environ['SOURCE_AUDIT_OUT'])
    out=out.with_name(out.stem+'-'+str(os.getpid())+out.suffix)
    out.write_text(json.dumps({'source':str(source),'sha256':digest},indent=2)+'\n')

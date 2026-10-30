import hashlib
import importlib.metadata as md
import json
import os
from pathlib import Path
import platform
import sys

packages=['graflo','numpy','pandas','pydantic','falkordb','redis','hypothesis','pytest','ty','pre-commit']
record={'python':sys.version,'executable':sys.executable,'platform':platform.platform(),
        'machine':platform.machine(),'affinity_probe':sorted(os.sched_getaffinity(0)),
        'packages':{name:md.version(name) for name in packages},
        'cgroup':{name:Path('/sys/fs/cgroup',name).read_text().strip() for name in ['cpu.max','cpuset.cpus.effective','memory.max']},
        'source_locks':{root:hashlib.sha256(Path(root,'uv.lock').read_bytes()).hexdigest() for root in ['/repo','/candidate']},
        'editable_metadata_caveat':'Installed editable distribution metadata is 1.24.0, but imported source is the frozen 1.24.1 baseline or candidate, checked explicitly. Between these upstream versions pyproject.toml and uv.lock only change the Graflo version string; dependencies are unchanged. The venv is mounted read-only and identical on both sides.'}
Path('/evidence/environment-final.json').write_text(json.dumps(record,indent=2)+'\n')
print(json.dumps(record))

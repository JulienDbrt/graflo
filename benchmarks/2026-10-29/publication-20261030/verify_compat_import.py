import hashlib
import json
from pathlib import Path
import graflo.db.falkordb.conn as module

path=Path(module.__file__).resolve()
assert path==Path('/repo/graflo/db/falkordb/conn.py')
assert hasattr(module,'_validate_integer_parameters')
result={'source':str(path),'sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'guard_present':True}
Path('/evidence/compat-module-import.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))

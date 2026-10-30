import json
import sys
import graflo
import graflo.architecture.graph_types.merge as fusion

print(json.dumps({'graflo':graflo.__file__,'fusion':fusion.__file__,'sys_path':sys.path,
                  'fast_path_present':'several empty transform' in open(fusion.__file__).read()}))

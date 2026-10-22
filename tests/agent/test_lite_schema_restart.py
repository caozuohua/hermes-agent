"""Restart must reproduce the same exposed schemas with unchanged configuration."""
import json
import os
import subprocess
import sys
from pathlib import Path


def test_schema_stability_across_fresh_processes(tmp_path):
    (tmp_path / 'config.yaml').write_text('security:\n  allow_lazy_installs: false\n')
    code = '''
import json
from model_tools import get_tool_definitions
from plugins.memory.mem0 import Mem0MemoryProvider
schemas = get_tool_definitions(enabled_toolsets=['file', 'memory'], quiet_mode=True)
provider = Mem0MemoryProvider()
schemas += [{'type': 'function', 'function': s} for s in provider.get_tool_schemas()]
print('SCHEMAS=' + json.dumps(schemas, sort_keys=True))
'''
    env = {**os.environ, 'HERMES_HOME': str(tmp_path)}
    runs = []
    for _ in range(2):
        result = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[2],
                                env=env, capture_output=True, text=True, check=True, timeout=60)
        runs.append(json.loads(next(line[8:] for line in result.stdout.splitlines() if line.startswith('SCHEMAS='))))
    assert runs[0] == runs[1]
    names = [s['function']['name'] for s in runs[0]]
    assert names and len(names) == len(set(names))
    assert {'mem0_search', 'mem0_add', 'mem0_update', 'mem0_delete'} <= set(names)

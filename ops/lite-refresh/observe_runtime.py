"""One lightweight sample, called by the existing five-minute systemd monitor."""
import argparse
import json
import sqlite3
import subprocess
import time
from pathlib import Path


def sample(home, service):
    fields = 'MainPID,MemoryCurrent,MemoryPeak,NRestarts,ActiveState,Result,ControlGroup,ExecMainStartTimestampMonotonic'
    props = dict(line.split('=', 1) for line in subprocess.check_output(
        ['systemctl', 'show', service, '--property=' + fields], text=True).splitlines() if '=' in line)
    row = {'timestamp': time.time(), 'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(), **props}
    pid = int(props.get('MainPID') or 0)
    if pid:
        try:
            status = dict(line.split(':', 1) for line in Path(f'/proc/{pid}/status').read_text().splitlines() if ':' in line)
            row.update(threads=int(status['Threads']), rss_bytes=int(status['VmRSS'].split()[0]) * 1024)
        except (FileNotFoundError, ProcessLookupError):
            row['process_changed_during_sample'] = True
    events = Path('/sys/fs/cgroup') / props.get('ControlGroup', '').lstrip('/') / 'memory.events'
    if events.exists():
        row['memory_events'] = dict(line.split() for line in events.read_text().splitlines())
    state_path = home / 'gateway_state.json'
    if state_path.exists():
        state = json.loads(state_path.read_text())
        row.update(code_sha=state.get('code_sha'), active_agents=state.get('active_agents'),
                   platforms={k: v.get('state') for k, v in state.get('platforms', {}).items()})
    journal = home / 'mem0-delivery.db'
    if journal.exists():
        db = sqlite3.connect(journal.as_uri() + '?mode=ro', uri=True, timeout=1)
        try:
            row['memory_delivery'] = dict(db.execute('SELECT state,count(*) FROM writes GROUP BY state'))
        finally:
            db.close()
    return row


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--service', default='hermes-gateway.service')
    args = parser.parse_args()
    result = sample(args.home.resolve(), args.service)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('a', encoding='utf-8') as output:
        output.write(json.dumps(result) + '\n')

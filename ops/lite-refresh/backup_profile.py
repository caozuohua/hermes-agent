"""Consistent profile recovery point; run under the shared maintenance flock."""
import argparse
import hashlib
import json
import os
import sqlite3
import tarfile
import tempfile
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path


def backup(home, destination):
    destination.mkdir(parents=True, exist_ok=False, mode=0o700)
    os.chmod(destination, 0o700)
    counts = {}
    for name in ('state.db', 'mem0-delivery.db'):
        source = home / name
        if not source.exists():
            continue
        with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True)) as src:
            with closing(sqlite3.connect(destination / name)) as dst:
                src.backup(dst)
                assert dst.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
                tables = [r[0] for r in dst.execute("SELECT name FROM sqlite_master WHERE type='table'")]
                counts[name] = {t: dst.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
                                for t in ('sessions', 'messages', 'writes') if t in tables}
        os.chmod(destination / name, 0o600)
    with tarfile.open(destination / 'profile.tar.gz', 'w:gz') as archive:
        for name in ('config.yaml', '.env', '.env.lark', 'mem0.json', 'memories', 'skills',
                     'sessions', 'workspace', 'bin', 'cron', 'hooks', 'plugins', 'qpc-receipts'):
            source = home / name
            if source.exists():
                archive.add(source, arcname=name)
    os.chmod(destination / 'profile.tar.gz', 0o600)
    with tempfile.TemporaryDirectory(prefix='hermes-restore-') as restored:
        with tarfile.open(destination / 'profile.tar.gz') as archive:
            archive.extractall(restored, filter='data')
        for name in ('config.yaml', 'memories/MEMORY.md', 'memories/USER.md'):
            if (home / name).is_file():
                assert (Path(restored) / name).read_bytes() == (home / name).read_bytes()
    manifest = {'created_at': datetime.now(timezone.utc).isoformat(), 'counts': counts,
                'sha256': {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in destination.iterdir() if p.is_file()},
                'restore_check': 'passed'}
    (destination / 'manifest.json').write_text(json.dumps(manifest, indent=2))
    os.chmod(destination / 'manifest.json', 0o600)
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--home', required=True, type=Path)
    parser.add_argument('--destination', required=True, type=Path)
    args = parser.parse_args()
    print(json.dumps(backup(args.home.resolve(), args.destination.resolve())))

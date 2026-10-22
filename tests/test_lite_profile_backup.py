import importlib.util
import sqlite3
from pathlib import Path


def test_backup_includes_committed_wal_rows_and_restorable_profile(tmp_path):
    module_path = Path(__file__).resolve().parents[1] / 'ops/lite-refresh/backup_profile.py'
    spec = importlib.util.spec_from_file_location('lite_backup', module_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    home = tmp_path / 'profile'
    home.mkdir()
    (home / 'config.yaml').write_text('memory: {}')
    (home / 'memories').mkdir()
    (home / 'memories/MEMORY.md').write_text('retained source')
    source = sqlite3.connect(home / 'state.db')
    try:
        source.execute('PRAGMA journal_mode=WAL')
        source.execute('CREATE TABLE messages(content TEXT)')
        source.execute("INSERT INTO messages VALUES ('committed while live')")
        source.commit()
        report = module.backup(home, tmp_path / 'recovery')
        assert report['restore_check'] == 'passed'
        assert report['counts']['state.db']['messages'] == 1
        restored = sqlite3.connect(tmp_path / 'recovery/state.db')
        try:
            assert restored.execute('SELECT content FROM messages').fetchone()[0] == 'committed while live'
        finally:
            restored.close()
    finally:
        source.close()

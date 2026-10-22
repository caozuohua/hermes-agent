"""Durable self-hosted writes. An ambiguous HTTP outcome is never replayed.

The queue stores already-scrubbed requests, outside the conversation database.
SQLite claims serialize writers across provider instances and processes.
"""
import hashlib
import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path


class DeliveryJournal:
    def __init__(self, path, max_pending=100):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.max_pending = max_pending
        with self.db() as db:
            db.execute("CREATE TABLE IF NOT EXISTS writes (id TEXT PRIMARY KEY, fingerprint TEXT, "
                       "payload TEXT NOT NULL, state TEXT NOT NULL, result TEXT, updated REAL NOT NULL)")
            db.execute("CREATE INDEX IF NOT EXISTS writes_fingerprint ON writes(fingerprint)")
        os.chmod(self.path, 0o600)

    @contextmanager
    def db(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def stage(self, payload):
        body = json.dumps(payload, sort_keys=True, ensure_ascii=False)
        fingerprint = hashlib.sha256(body.encode()).hexdigest()
        with self.db() as db:
            db.execute('BEGIN IMMEDIATE')
            # Repeated explicit add and a retried sync for the same source are idempotent.
            row = db.execute("SELECT id FROM writes WHERE fingerprint=? AND state != 'superseded' ORDER BY updated DESC LIMIT 1",
                             (fingerprint,)).fetchone()
            if row:
                return row['id']
            count = db.execute("SELECT count(*) FROM writes WHERE state NOT IN ('confirmed','superseded')").fetchone()[0]
            if count >= self.max_pending:
                raise RuntimeError('Mem0 delivery backlog full; nothing submitted. Conversation remains the recovery source.')
            request_id = uuid.uuid4().hex
            payload = {**payload, 'metadata': {**payload.get('metadata', {}), 'request_id': request_id}}
            db.execute('INSERT INTO writes VALUES (?,?,?,?,?,?)',
                       (request_id, fingerprint, json.dumps(payload, ensure_ascii=False), 'queued', None, time.time()))
            return request_id

    def status(self, request_id):
        with self.db() as db:
            row = db.execute('SELECT state,result FROM writes WHERE id=?', (request_id,)).fetchone()
        return {'request_id': request_id, 'delivery_status': row['state'],
                **(json.loads(row['result']) if row['result'] else {})}

    def supersede(self, request_id):
        """A confirmed receipt no longer describes the remote state; retain its history."""
        with self.db() as db:
            db.execute("UPDATE writes SET state='superseded',updated=? WHERE id=? AND state='confirmed'",
                       (time.time(), request_id))

    def drain(self, send, should_stop=lambda: False):
        """Drain definitely-unsent jobs only. No retries after dispatch, even on restart."""
        while not should_stop():
            with self.db() as db:
                db.execute('BEGIN IMMEDIATE')
                # A prior process may have died mid-request. It may still commit remotely.
                db.execute("UPDATE writes SET state='unknown',updated=? WHERE state='inflight' AND updated<?",
                           (time.time(), time.time() - 120))
                if db.execute("SELECT 1 FROM writes WHERE state='inflight' LIMIT 1").fetchone():
                    return
                row = db.execute("SELECT * FROM writes WHERE state='queued' ORDER BY updated LIMIT 1").fetchone()
                if row is None:
                    return
                db.execute("UPDATE writes SET state='inflight',updated=? WHERE id=?", (time.time(), row['id']))
            state, result = 'unknown', None
            try:
                result = send(json.loads(row['payload']))
                if not isinstance(result, dict) or not isinstance(result.get('results'), list):
                    raise ValueError('Mem0 response has no results receipt')
                state = 'confirmed'
            except Exception as exc:
                # Do not store exception messages: URLs/headers can contain credentials.
                result = {'error_type': type(exc).__name__, 'result': 'Write outcome unknown; verify before retrying.'}
            with self.db() as db:
                db.execute('UPDATE writes SET state=?,result=?,updated=? WHERE id=?',
                           (state, json.dumps(result), time.time(), row['id']))

    def reconcile(self, list_memories, check_mutation=None):
        """Observe late receipts by metadata; inferred multi-fact writes remain ambiguous."""
        with self.db() as db:
            rows = db.execute("SELECT * FROM writes WHERE state IN ('unknown','observed')").fetchall()
        by_user = {}
        for row in rows:
            payload = json.loads(row['payload'])
            if payload.get('operation'):
                receipt = check_mutation(payload) if check_mutation else None
                if receipt is not None:
                    with self.db() as db:
                        db.execute("UPDATE writes SET state='confirmed',result=?,updated=? WHERE id=?",
                                   (json.dumps(receipt), time.time(), row['id']))
                continue
            user = payload['user_id']
            if user not in by_user:
                by_user[user] = list_memories(user)
            found = [m for m in by_user[user] if (m.get('metadata') or {}).get('request_id') == row['id']]
            if found:
                state = 'observed' if payload.get('infer') else 'confirmed'
                with self.db() as db:
                    db.execute('UPDATE writes SET state=?,result=?,updated=? WHERE id=?',
                               (state, json.dumps({'results': found}), time.time(), row['id']))

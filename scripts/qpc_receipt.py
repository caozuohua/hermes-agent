"""QPC record writer: schema validation, durable intent, and read-back receipt.

Run with --env-file and --record-file; --dry-run performs reads only.
No schema mutation. A timed-out create is reconciled, never blindly retried.
"""
import argparse
import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

import httpx
from dotenv import dotenv_values
from utils import atomic_json_write

FIELDS = {'个人知识类型', '标题', '原始记录', '状态'}


class QPCWriter:
    def __init__(self, client, app, table, journal):
        self.client = client
        self.root = f'/bitable/v1/apps/{app}/tables/{table}'
        self.journal = Path(journal)

    def call(self, method, suffix, **kwargs):
        response = self.client.request(method, self.root + suffix, **kwargs)
        response.raise_for_status()
        body = response.json()
        if body.get('code') != 0:
            raise RuntimeError(f'QPC API rejected request: code={body.get("code")}')
        return body.get('data') or {}

    def items(self, suffix):
        token = None
        while True:
            data = self.call('GET', suffix, params={'page_size': 500, **({'page_token': token} if token else {})})
            yield from data.get('items', [])
            if not data.get('has_more'):
                return
            next_token = data.get('page_token')
            if not next_token or next_token == token:
                raise RuntimeError('QPC pagination did not advance')
            token = next_token

    @staticmethod
    def normalized(value):
        if isinstance(value, list) and all(isinstance(v, dict) and 'text' in v for v in value):
            return ''.join(v['text'] for v in value)
        return value

    def matches(self, record, fields):
        return all(self.normalized(record.get('fields', {}).get(k)) == v for k, v in fields.items())

    def write(self, fields, dry_run=False):
        self.journal.mkdir(parents=True, exist_ok=True, mode=0o700)
        # A SQLite write transaction serializes competing processes on every supported OS.
        with closing(sqlite3.connect(self.journal / 'writer-lock.db', timeout=1)) as lock, lock:
            lock.execute('BEGIN IMMEDIATE')
            return self._write(fields, dry_run)

    def _write(self, fields, dry_run=False):
        if set(fields) != FIELDS or not all(isinstance(v, str) and v.strip() for v in fields.values()):
            raise ValueError('Exactly the four QPC fields with nonempty text are required')
        if len(fields['标题']) > 50:
            raise ValueError('QPC title must be at most 50 characters')
        schema = {x['field_name']: x for x in self.items('/fields')}
        for key in fields:
            if key not in schema:
                raise ValueError(f'Missing QPC field: {key}')
            if schema[key].get('type') == 3:
                options = {o['name'] for o in schema[key].get('property', {}).get('options', [])}
                if fields[key] not in options:
                    raise ValueError(f'Unknown select value for {key}; schema was not modified')
        if dry_run:
            return {'status': 'validated', 'written': False}
        digest = hashlib.sha256(json.dumps([self.root, fields], sort_keys=True, ensure_ascii=False).encode()).hexdigest()
        self.journal.mkdir(parents=True, exist_ok=True)
        path = self.journal / (digest + '.json')
        existing = [r for r in self.items('/records') if self.matches(r, fields)]
        if len(existing) > 1:
            raise RuntimeError('Multiple matching QPC records; reconcile manually')
        if existing:
            record_id = existing[0]['record_id']
        elif path.exists():
            return {'status': 'pending_confirmation', 'request_id': digest, 'written': None}
        else:
            atomic_json_write(path, {'status': 'pending_confirmation', 'fields': fields}, mode=0o600)
            try:
                record_id = self.call('POST', '/records', json={'fields': fields})['record']['record_id']
            except Exception as exc:
                # Record the uncertainty before propagating; another invocation will read before writing.
                return {'status': 'pending_confirmation', 'request_id': digest, 'written': None,
                        'error_type': type(exc).__name__}
        record = self.call('GET', '/records/' + record_id)['record']
        if not self.matches(record, fields):
            raise RuntimeError('QPC read-back differs from requested fields; not confirmed')
        receipt = {'status': 'confirmed', 'record_id': record_id, 'request_id': digest, 'written': True}
        atomic_json_write(path, receipt, mode=0o600)
        return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--env-file', required=True)
    parser.add_argument('--record-file', required=True)
    parser.add_argument('--dry-run', action='store_true')
    args = parser.parse_args()
    env = dotenv_values(args.env_file)
    domain = 'https://open.feishu.cn' if env.get('FEISHU_DOMAIN') == 'feishu' else 'https://open.larksuite.com'
    with httpx.Client(base_url=domain + '/open-apis', timeout=20) as client:
        response = client.post('/auth/v3/tenant_access_token/internal', json={
            'app_id': env['FEISHU_APP_ID'], 'app_secret': env['FEISHU_APP_SECRET']})
        response.raise_for_status()
        body = response.json()
        if body.get('code') != 0:
            raise RuntimeError('QPC authentication failed')
        client.headers['Authorization'] = 'Bearer ' + body['tenant_access_token']
        from hermes_constants import get_hermes_home
        writer = QPCWriter(client, env['FEISHU_BITABLE_APP_TOKEN'], env['FEISHU_BITABLE_TABLE_ID'],
                           get_hermes_home() / 'qpc-receipts')
        print(json.dumps(writer.write(json.loads(Path(args.record_file).read_text(encoding='utf-8')), args.dry_run), ensure_ascii=False))


if __name__ == '__main__':
    main()

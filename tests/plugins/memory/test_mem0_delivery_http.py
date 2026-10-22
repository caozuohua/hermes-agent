import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from plugins.memory.mem0._backend import SelfHostedBackend


@pytest.fixture
def api():
    state = {'records': {}, 'posts': 0, 'lost_reply': False, 'mutations': 0}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, body):
            data = json.dumps(body).encode()
            self.send_response(200)
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def read(self):
            return json.loads(self.rfile.read(int(self.headers.get('Content-Length', '0'))) or '{}')

        def do_GET(self):
            self.reply({'results': list(state['records'].values())} if self.path.startswith('/memories?') else state['records'].get(self.path.rsplit('/', 1)[-1]))

        def do_POST(self):
            body = self.read()
            if self.path == '/search':
                self.reply({'results': list(state['records'].values())})
                return
            state['posts'] += 1
            record = {'id': str(state['posts']), 'memory': body['messages'][0]['content'], 'metadata': body.get('metadata', {})}
            state['records'][record['id']] = record
            if state['lost_reply']:
                self.close_connection = True
            else:
                self.reply({'results': [record]})

        def do_PUT(self):
            body = self.read()
            state['mutations'] += 1
            state['records'][self.path.rsplit('/', 1)[-1]]['memory'] = body['text']
            if state['lost_reply']:
                self.close_connection = True
            else:
                self.reply({'message': 'updated'})

        def do_DELETE(self):
            state['mutations'] += 1
            state['records'].pop(self.path.rsplit('/', 1)[-1], None)
            if state['lost_reply']:
                self.close_connection = True
            else:
                self.reply({'message': 'deleted'})
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}', state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(2)


def test_real_http_lost_receipts_reconcile_across_restart(api, tmp_path, monkeypatch):
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    host, state = api
    settings = {'durable_writes': True}
    backend = SelfHostedBackend('synthetic', host, settings=settings)
    state['lost_reply'] = True
    args = {'user_id': 'isolated', 'agent_id': 'test', 'infer': False}
    messages = [{'role': 'user', 'content': 'likes violet notebooks'}]
    pending = backend.add(messages, **args)
    assert pending['delivery_status'] == 'unknown'
    backend.close()
    restored = SelfHostedBackend('synthetic', host, settings=settings)
    try:
        restored.reconcile_pending()
        assert restored.add(messages, **args)['delivery_status'] == 'confirmed'
        assert state['posts'] == 1
        updated = restored.update('1', 'likes green notebooks')
        assert updated['delivery_status'] == 'unknown'
        restored.reconcile_pending()
        assert restored.update('1', 'likes green notebooks')['delivery_status'] == 'confirmed'
        assert state['mutations'] == 1
        deleted = restored.delete('1')
        assert deleted['delivery_status'] == 'unknown'
        restored.reconcile_pending()
        assert restored.delete('1')['delivery_status'] == 'confirmed'
        assert state['mutations'] == 2
        state['lost_reply'] = False
        assert restored.add(messages, **args)['delivery_status'] == 'confirmed'
        assert state['posts'] == 2  # a deleted fact can be explicitly re-added
    finally:
        restored.close()


def test_shutdown_leaves_unsent_queue_recoverable(api, tmp_path, monkeypatch):
    monkeypatch.setenv('HERMES_HOME', str(tmp_path))
    host, state = api
    backend = SelfHostedBackend('synthetic', host, settings={'durable_writes': True})
    try:
        request = backend.stage_add([{'role': 'user', 'content': 'durable'}], user_id='test', agent_id='test')
        backend.drain_pending(lambda: True)
        assert state['posts'] == 0
        assert backend._journal.status(request)['delivery_status'] == 'queued'
        backend.drain_pending()
        assert state['posts'] == 1
    finally:
        backend.close()

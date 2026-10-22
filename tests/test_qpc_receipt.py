import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest

from scripts.qpc_receipt import QPCWriter


@pytest.fixture
def qpc_server():
    state = {'records': [], 'posts': 0, 'mode': 'success'}
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def reply(self, data, code=0):
            body = json.dumps({'code': code, 'data': data}).encode()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            path = self.path.split('?')[0]
            if path.endswith('/fields'):
                self.reply({'items': [{'field_name': k, 'type': 1} for k in ['个人知识类型', '标题', '原始记录', '状态']]})
            elif path.endswith('/records'):
                self.reply({'items': state['records']})
            else:
                record = dict(state['records'][0])
                if state['mode'] == 'mismatch':
                    record['fields'] = {**record['fields'], '标题': 'wrong'}
                self.reply({'record': record})

        def do_POST(self):
            state['posts'] += 1
            body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            if state['mode'] == 'denied':
                self.reply({}, code=99991672)
                return
            record = {'record_id': 'test-record', **body}
            state['records'].append(record)
            if state['mode'] == 'lost_reply':
                self.close_connection = True
                return
            self.reply({'record': record})
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with httpx.Client(base_url=f'http://127.0.0.1:{server.server_port}', timeout=2) as client:
            yield client, state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=3)


@pytest.mark.parametrize('mode', ['success', 'lost_reply', 'denied', 'mismatch'])
def test_real_http_requires_readback_and_never_blindly_reposts(qpc_server, tmp_path, mode):
    client, state = qpc_server
    state['mode'] = mode
    writer = QPCWriter(client, 'isolated-app', 'isolated-table', tmp_path)
    fields = {'个人知识类型': '事实C', '标题': 'test', '原始记录': 'isolated content', '状态': '待整理'}
    if mode == 'mismatch':
        with pytest.raises(RuntimeError, match='read-back differs'):
            writer.write(fields)
        return
    result = writer.write(fields)
    assert result['status'] == ('confirmed' if mode == 'success' else 'pending_confirmation')
    result = writer.write(fields)
    assert state['posts'] == 1
    assert result['status'] == ('pending_confirmation' if mode == 'denied' else 'confirmed')

import json
from concurrent.futures import ThreadPoolExecutor

from plugins.memory.mem0._delivery import DeliveryJournal


def test_timeout_is_durable_and_late_receipt_never_replays(tmp_path):
    path = tmp_path / 'delivery.db'
    journal = DeliveryJournal(path)
    body = {'user_id': 'test', 'agent_id': 'test', 'infer': False,
            'messages': [{'role': 'user', 'content': 'durable fact'}]}
    request = journal.stage(body)
    sent = []
    def timed_out(payload):
        sent.append(payload)
        raise TimeoutError()
    journal.drain(timed_out)
    restored = DeliveryJournal(path)
    assert restored.stage(body) == request
    restored.drain(timed_out)
    assert len(sent) == 1
    assert restored.status(request)['delivery_status'] == 'unknown'
    restored.reconcile(lambda _: [{'id': 'receipt', 'metadata': {'request_id': request}}])
    assert restored.status(request)['delivery_status'] == 'confirmed'


def test_concurrent_drains_and_restart_preserve_queued_work(tmp_path):
    path = tmp_path / 'delivery.db'
    journal = DeliveryJournal(path)
    requests = [journal.stage({'user_id': 'u', 'messages': [{'role': 'user', 'content': str(i)}]}) for i in range(5)]
    sent = []
    def send(payload):
        sent.append(payload)
        return {'results': [{'id': payload['metadata']['request_id']}]}
    with ThreadPoolExecutor(2) as executor:
        list(executor.map(lambda _: DeliveryJournal(path).drain(send), range(2)))
    assert len(sent) == len(requests)
    assert all(journal.status(r)['delivery_status'] == 'confirmed' for r in requests)

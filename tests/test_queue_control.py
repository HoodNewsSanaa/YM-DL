import queue
import threading
import pytest

from queue_control import QueueCancelled, choose_error_action, wait_for_decision


def test_decision_blocks_and_ignores_stale_responses():
    commands, events = queue.Queue(), queue.Queue()
    results = []
    worker = threading.Thread(target=lambda: results.append(wait_for_decision(
        lambda *event: events.put(event), commands, {'scope': 'track', 'error': '403'})), daemon=True)
    worker.start()
    event, details = events.get(timeout=2)
    assert event == 'queue_error' and worker.is_alive() and not results
    commands.put({'request_id': 'old-request', 'action': 'skip'})
    commands.put({'request_id': details['request_id'], 'action': 'retry'})
    worker.join(timeout=2)
    assert results == ['retry'] and not worker.is_alive()


def test_cancel_decision_stops_queue():
    with pytest.raises(QueueCancelled):
        choose_error_action(lambda details: 'cancel', {'scope': 'URL'})

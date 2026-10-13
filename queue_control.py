"""Blocking worker-side decisions with a responsive, asynchronous GUI."""
import uuid


class QueueCancelled(Exception):
    pass


def choose_error_action(handler, details):
    action = handler(details) if handler else "skip"
    if action == "cancel":
        raise QueueCancelled("Download queue cancelled; completed files are kept.")
    if action not in {"retry", "skip"}:
        raise ValueError("Unknown queue error decision.")
    return action


def wait_for_decision(emit, commands, details):
    request_id = uuid.uuid4().hex
    emit("queue_error", {**details, "request_id": request_id})
    while True:
        response = commands.get()
        if response.get("request_id") == request_id:
            return response.get("action", "cancel")

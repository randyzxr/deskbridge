"""Bounded logs and coalesced, non-droppable lifecycle events."""
from collections import deque
import queue
import threading
import time


class EventMailbox:
    def __init__(self, max_logs=256):
        self.logs = deque(maxlen=max_logs)
        self.control = {}
        self.condition = threading.Condition()

    def put_nowait(self, item):
        kind, text = item
        with self.condition:
            if kind == "log":
                self.logs.append(item)
            elif kind in ("status", "exit", "start_error", "ready"):
                # At most one event of each fixed kind; logs cannot evict it.
                self.control[kind] = text
            else:
                raise ValueError("Unsupported lifecycle event")
            self.condition.notify()

    def get(self, timeout=None):
        with self.condition:
            deadline = time.monotonic() + timeout if timeout is not None else None
            while not self.control and not self.logs:
                remaining = None if deadline is None else deadline-time.monotonic()
                if remaining is not None and remaining <= 0:
                    raise queue.Empty
                self.condition.wait(remaining)
            if self.control:
                kind = next(iter(self.control))
                return kind, self.control.pop(kind)
            return self.logs.popleft()

    def get_nowait(self):
        return self.get(timeout=0)

    def empty(self):
        with self.condition:
            return not self.control and not self.logs

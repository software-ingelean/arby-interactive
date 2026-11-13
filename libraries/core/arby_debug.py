"""Bounded operational trace: never stores speech, prompts or credentials."""
from collections import deque
from pathlib import Path
import sys
import threading
import time


class DebugTrace:
    def __init__(self, limit=250):
        self._lock = threading.RLock()
        self._events = deque(maxlen=limit)
        self._stages = {}
        self._sequence = 0

    def event(self, source, message, level='info', **details):
        with self._lock:
            self._sequence += 1
            self._events.append(dict(id=self._sequence, at=time.time(), source=source,
                                     message=message, level=level, details=details))

    def stage(self, source, name, location, expected_seconds=None):
        with self._lock:
            self._stages[source] = dict(name=name, location=location, since=time.monotonic(),
                                        expected_seconds=expected_seconds)
            self.event(source, name, location=location)

    def snapshot(self):
        now = time.monotonic()
        with self._lock:
            stages = {source: {**stage, 'elapsed': round(now-stage['since'], 1),
                              'slow': stage['expected_seconds'] is not None and now-stage['since'] > stage['expected_seconds']}
                      for source, stage in self._stages.items()}
            for stage in stages.values():
                stage.pop('since')
            events = list(self._events)
        frames = sys._current_frames()
        threads = []
        for thread in threading.enumerate():
            frame = frames.get(thread.ident)
            if frame is None or (thread.name != 'MainThread' and not thread.name.startswith('arby-')):
                continue
            stack = []
            while frame is not None and len(stack) < 8:
                stack.append(f'{Path(frame.f_code.co_filename).name}:{frame.f_lineno} · {frame.f_code.co_name}')
                frame = frame.f_back
            threads.append(dict(name=thread.name, stack=stack))
        return dict(stages=stages, events=events, threads=threads, capacity=self._events.maxlen)

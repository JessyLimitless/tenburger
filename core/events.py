# core/events.py
"""
PyQt5 의존성 제거를 위한 경량 이벤트 시스템.
- EventEmitter: pyqtSignal 대체
- RepeatingTimer: QTimer 대체
"""

import threading
from typing import Any, Callable, List


class EventEmitter:
    """
    pyqtSignal 대체.

    사용법:
        account_update = EventEmitter()
        account_update.connect(my_handler)
        account_update.emit({"cash": 10000})
    """

    def __init__(self):
        self._callbacks: List[Callable] = []
        self._lock = threading.Lock()

    def connect(self, callback: Callable):
        with self._lock:
            if callback not in self._callbacks:
                self._callbacks.append(callback)

    def disconnect(self, callback: Callable):
        with self._lock:
            self._callbacks = [cb for cb in self._callbacks if cb is not callback]

    def emit(self, *args: Any):
        with self._lock:
            callbacks = list(self._callbacks)
        for cb in callbacks:
            try:
                cb(*args)
            except Exception as e:
                print(f"[EventEmitter] callback error: {e}")


class RepeatingTimer:
    """
    QTimer 대체. 지정된 간격(초)으로 콜백을 반복 실행.

    사용법:
        timer = RepeatingTimer(5.0, my_func)
        timer.start()
        timer.stop()
    """

    def __init__(self, interval_sec: float, callback: Callable):
        self._interval = interval_sec
        self._callback = callback
        self._timer: threading.Timer | None = None
        self._running = False
        self._lock = threading.Lock()

    @property
    def interval(self) -> float:
        return self._interval

    @interval.setter
    def interval(self, value: float):
        self._interval = value

    def start(self):
        with self._lock:
            self._running = True
        self._schedule()

    def stop(self):
        with self._lock:
            self._running = False
            if self._timer:
                self._timer.cancel()
                self._timer = None

    def is_active(self) -> bool:
        with self._lock:
            return self._running

    def _schedule(self):
        with self._lock:
            if not self._running:
                return
            self._timer = threading.Timer(self._interval, self._run)
            self._timer.daemon = True
            self._timer.start()

    def _run(self):
        try:
            self._callback()
        except Exception as e:
            print(f"[RepeatingTimer] callback error: {e}")
        self._schedule()

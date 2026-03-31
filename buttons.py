"""
buttons.py -- GPIO button handler for KindlePi.

STUB VERSION: reads from a named pipe /tmp/kindlepi_input
Send commands from a second terminal:
    echo n > /tmp/kindlepi_input   # next
    echo p > /tmp/kindlepi_input   # prev
    echo a > /tmp/kindlepi_input   # AI / confirm
    echo b > /tmp/kindlepi_input   # back
    echo q > /tmp/kindlepi_input   # quit
"""

import threading
from enum import Enum, auto
import os

PIPE_PATH = "/tmp/kindlepi_input"


class ButtonEvent(Enum):
    NEXT = auto()
    PREV = auto()
    AI   = auto()
    BACK = auto()
    QUIT = auto()


class ButtonHandler:
    def __init__(self):
        self._callback = None
        self._thread   = None
        self._running  = False

    def set_callback(self, fn):
        self._callback = fn

    def start(self):
        if not os.path.exists(PIPE_PATH):
            os.mkfifo(PIPE_PATH)
        self._running = True
        self._thread  = threading.Thread(target=self._poll_pipe, daemon=True)
        self._thread.start()

    def stop(self):
        self._running = False

    def _poll_pipe(self):
        while self._running:
            try:
                with open(PIPE_PATH, "r") as pipe:
                    for line in pipe:
                        ch    = line.strip().lower()
                        event = self._map_key(ch)
                        if event and self._callback:
                            self._callback(event)
                        if event == ButtonEvent.QUIT:
                            return
            except Exception:
                pass

    @staticmethod
    def _map_key(ch: str):
        return {
            "n": ButtonEvent.NEXT,
            "p": ButtonEvent.PREV,
            "a": ButtonEvent.AI,
            "b": ButtonEvent.BACK,
            "q": ButtonEvent.QUIT,
        }.get(ch)

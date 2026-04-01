import threading
import os
from enum import Enum, auto

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
        os.chmod(PIPE_PATH, 0o666)
        self._running = True
        self._thread  = threading.Thread(target=self._poll_pipe, daemon=True)
        self._thread.start()
        print(f"[buttons] thread started, watching {PIPE_PATH}")

    def stop(self):
        self._running = False

    def _poll_pipe(self):
        print("[buttons] poll thread running")
        while self._running:
            try:
                print("[buttons] opening pipe...")
                with open(PIPE_PATH, "r") as pipe:
                    print("[buttons] pipe opened, waiting for input")
                    for line in pipe:
                        ch = line.strip().lower()
                        print(f"[buttons] got: {ch!r}")
                        event = self._map_key(ch)
                        if event and self._callback:
                            self._callback(event)
                        if event == ButtonEvent.QUIT:
                            return
                print("[buttons] pipe closed, reopening")
            except Exception as e:
                print(f"[buttons] error: {e}")

    @staticmethod
    def _map_key(ch: str):
        return {
            "n": ButtonEvent.NEXT,
            "p": ButtonEvent.PREV,
            "a": ButtonEvent.AI,
            "b": ButtonEvent.BACK,
            "q": ButtonEvent.QUIT,
        }.get(ch)

"""Thread handoffs with no cross-thread Tk calls or controller lock ownership."""
import queue
import threading
from dataclasses import replace


class UiQueue:
    def __init__(self):
        self.pending = queue.SimpleQueue()

    def post(self, callback):
        self.pending.put(callback)

    def drain(self):
        # Bound work per Tk tick so an event storm cannot starve its event loop.
        for _ in range(64):
            try:
                callback = self.pending.get_nowait()
            except queue.Empty:
                break
            callback()


class PowerWorker:
    """Single serialized writer, coalesced latest intent and periodic renewal."""
    def __init__(self, client, changed=lambda: None):
        self.client, self.changed = client, changed
        self.condition = threading.Condition()
        self.settings = None
        self.stopping = False
        self.thread = threading.Thread(target=self._run, name="locklock-power-client", daemon=True)
        self.thread.start()

    def submit(self, settings, active):
        with self.condition:
            self.settings = replace(settings, ignore_lid_close=settings.ignore_lid_close and active)
            self.condition.notify()

    def _run(self):
        while True:
            with self.condition:
                if self.settings is None and not self.stopping:
                    self.condition.wait()
                if self.stopping:
                    break
                settings = self.settings
            try:
                self.client.sync(settings, force=True)
            except Exception:
                pass  # Client records the specific error for status and tray.
            self.changed()
            with self.condition:
                if self.settings is settings and not self.stopping:
                    self.condition.wait(20)
        try:
            self.client.restore_and_stop()
        except Exception as exc:
            self.client.last_error = str(exc)
        self.changed()

    def close(self):
        with self.condition:
            self.stopping = True
            self.condition.notify()
        # Input/UI shutdown does not wait for a non-responsive service. The
        # service's own 45-second lease is the crash recovery backstop.
        self.thread.join(timeout=.1)

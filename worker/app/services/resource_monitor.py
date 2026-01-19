import asyncio
from typing import Optional

try:
    import psutil
except Exception:
    psutil = None

from worker.app.config import (
    RESOURCE_POLL_INTERVAL,
    CPU_HIGH_THRESHOLD,
    CPU_LOW_THRESHOLD,
)


class ResourceMonitor:
    """
    Periodically monitors CPU load and exposes an asyncio.Event indicating when it
    is safe to start more CPU-bound work. Uses hysteresis to avoid thrashing.
    """

    def __init__(self, poll_interval: float = RESOURCE_POLL_INTERVAL):
        self.poll_interval = poll_interval
        self.cpu_ok_event = asyncio.Event()
        self.cpu_ok_event.set()

        self._task: Optional[asyncio.Task] = None
        self._stopping = False

        self.cpu_percent = 0.0

    async def _sample_cpu(self) -> float:
        """Return CPU percent (0-100). Uses psutil if present; otherwise returns 0."""
        if not psutil:
            return 0.0
        # psutil.cpu_percent can block to measure over an interval; call in thread
        return await asyncio.to_thread(psutil.cpu_percent, 1.0)

    async def _monitor_loop(self):
        try:
            while not self._stopping:
                # Sample CPU
                try:
                    cpu_val = await self._sample_cpu()
                except Exception:
                    cpu_val = 0.0

                self.cpu_percent = cpu_val

                # CPU hysteresis
                if cpu_val >= CPU_HIGH_THRESHOLD:
                    # too hot -> clear ok
                    if self.cpu_ok_event.is_set():
                        self.cpu_ok_event.clear()
                elif cpu_val <= CPU_LOW_THRESHOLD:
                    # cooled down -> set ok
                    if not self.cpu_ok_event.is_set():
                        self.cpu_ok_event.set()

                await asyncio.sleep(self.poll_interval)
        except asyncio.CancelledError:
            pass

    async def start(self):
        if self._task:
            return
        self._stopping = False
        self._task = asyncio.create_task(self._monitor_loop())

    async def stop(self):
        self._stopping = True
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def snapshot(self) -> dict:
        return {
            "cpu_percent": self.cpu_percent,
            "cpu_ok": self.cpu_ok_event.is_set(),
        }

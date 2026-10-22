"""Minimal in-process job runner for ad hoc work (discovery runs).

A :class:`Job` runs a callable on a small thread pool and exposes status,
progress, a log tail and cooperative cancellation. Jobs are keyed (one
discovery run per project): submitting a second job with the same key while
one is active raises :class:`JobBusy`. A hard time limit flips the cancel
event and, after a short grace period, marks the job ``timeout`` even if the
worker thread is still winding down, so a stuck probe can never block the
next run.

Nothing here schedules anything: a job exists only because somebody called
:func:`submit`. There is no queue persistence and no retry; the caller
persists whatever it needs (discovery writes ``run.json`` as it goes).

Under a multi-process server (gunicorn workers) every process has its own
runner; cross-process exclusivity is the caller's job (discovery uses a lock
file in the project directory and polls a cancel file).
"""

from __future__ import annotations

import collections
import secrets
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Deque, Dict, List, Optional

ACTIVE = ("queued", "running")
FINAL = ("done", "failed", "cancelled", "timeout")
MAX_LOG = 400


class JobBusy(Exception):
    """A job with this key is already active."""

    def __init__(self, job: "Job") -> None:
        super().__init__(f"job {job.id} ({job.kind}) is already {job.status} for {job.key}")
        self.job = job


class JobCancelled(Exception):
    """Raised inside the worker by :meth:`Job.check` once cancel was requested."""


class Job:
    def __init__(self, kind: str, key: str, time_limit: float, job_id: Optional[str] = None) -> None:
        self.id = job_id or ("job-" + secrets.token_hex(6))
        self.kind = kind
        self.key = key
        self.time_limit = float(time_limit)
        self.status = "queued"
        self.progress = 0.0
        self.stage = ""
        self.created = time.time()
        self.started: Optional[float] = None
        self.finished: Optional[float] = None
        self.result: Any = None
        self.error = ""
        self.cancel_reason = ""
        self._log: Deque[Dict[str, Any]] = collections.deque(maxlen=MAX_LOG)
        self._cancel = threading.Event()
        self._lock = threading.Lock()
        self._listeners: List[Callable[["Job"], None]] = []

    # ---- worker-side API

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    def check(self) -> None:
        """Raise :class:`JobCancelled` if cancel / time-out was requested."""
        if self._cancel.is_set():
            raise JobCancelled(self.cancel_reason or "cancelled")

    def wait(self, seconds: float) -> bool:
        """Sleep up to ``seconds`` but wake early on cancel. Returns True when cancelled."""
        return self._cancel.wait(max(0.0, seconds))

    def log(self, message: str, level: str = "info") -> None:
        with self._lock:
            self._log.append({"t": round(time.time(), 3), "level": level, "msg": str(message)})
        self._notify()

    def set_progress(self, progress: Optional[float] = None, stage: Optional[str] = None) -> None:
        with self._lock:
            if progress is not None:
                self.progress = max(0.0, min(1.0, float(progress)))
            if stage is not None:
                self.stage = str(stage)
        self._notify()

    def on_change(self, fn: Callable[["Job"], None]) -> None:
        self._listeners.append(fn)

    def _notify(self) -> None:
        for fn in list(self._listeners):
            try:
                fn(self)
            except Exception:  # listeners must never break the job
                pass

    # ---- control

    def request_cancel(self, reason: str = "cancelled") -> None:
        if self.status in FINAL:
            return
        self.cancel_reason = reason
        self._cancel.set()
        if self.status == "queued":
            self._finish("cancelled", error=reason)

    def _finish(self, status: str, error: str = "", result: Any = None) -> None:
        with self._lock:
            if self.status in FINAL:
                return
            self.status = status
            self.error = error
            self.result = result
            self.finished = time.time()
            if status == "done":
                self.progress = 1.0
        self._notify()

    @property
    def elapsed(self) -> float:
        start = self.started or self.created
        return (self.finished or time.time()) - start

    @property
    def remaining(self) -> float:
        if self.started is None:
            return self.time_limit
        return max(0.0, self.time_limit - (time.time() - self.started))

    def log_tail(self, n: int = 50) -> List[Dict[str, Any]]:
        with self._lock:
            items = list(self._log)
        return items[-n:]

    def to_dict(self, log_lines: int = 50) -> Dict[str, Any]:
        return {
            "id": self.id, "kind": self.kind, "key": self.key, "status": self.status, "active": self.status in ACTIVE,
            "progress": round(self.progress, 3), "stage": self.stage, "created": self.created, "started": self.started,
            "finished": self.finished, "elapsed": round(self.elapsed, 1), "time_limit": self.time_limit,
            "remaining": round(self.remaining, 1), "error": self.error, "log": self.log_tail(log_lines),
        }


class JobRunner:
    """Thread-pool runner with one active job per key."""

    def __init__(self, workers: int = 2, grace: float = 5.0) -> None:
        self.workers = workers
        self.grace = grace
        self._jobs: Dict[str, Job] = {}
        self._lock = threading.Lock()
        self._pool: Optional[ThreadPoolExecutor] = None

    def _executor(self) -> ThreadPoolExecutor:
        if self._pool is None:
            self._pool = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix="fathom-job")
        return self._pool

    def active(self, key: str) -> Optional[Job]:
        with self._lock:
            for j in self._jobs.values():
                if j.key == key and j.status in ACTIVE:
                    return j
        return None

    def get(self, job_id: str) -> Optional[Job]:
        with self._lock:
            return self._jobs.get(job_id)

    def list(self, key: Optional[str] = None, kind: Optional[str] = None) -> List[Job]:
        with self._lock:
            out = [j for j in self._jobs.values() if (key is None or j.key == key) and (kind is None or j.kind == kind)]
        return sorted(out, key=lambda j: j.created, reverse=True)

    def submit(self, kind: str, key: str, fn: Callable[[Job], Any], time_limit: float = 300.0, job_id: Optional[str] = None) -> Job:
        """Start ``fn(job)`` on the pool. Raises :class:`JobBusy` when ``key`` already has an active job."""
        with self._lock:
            for j in self._jobs.values():
                if j.key == key and j.status in ACTIVE:
                    raise JobBusy(j)
            job = Job(kind, key, time_limit, job_id=job_id)
            self._jobs[job.id] = job
            self._prune_locked()
        self._executor().submit(self._run, job, fn)
        return job

    def cancel(self, job_id: str, reason: str = "cancelled") -> Optional[Job]:
        job = self.get(job_id)
        if job is not None:
            job.request_cancel(reason)
        return job

    def _run(self, job: Job, fn: Callable[[Job], Any]) -> None:
        if job.status in FINAL:  # cancelled while queued
            return
        job.started = time.time()
        job.status = "running"
        job._notify()
        watchdog = threading.Timer(job.time_limit, self._timeout, args=(job,))
        watchdog.daemon = True
        watchdog.start()
        try:
            result = fn(job)
        except JobCancelled as exc:
            job._finish("timeout" if job.cancel_reason == "time limit" else "cancelled", error=str(exc))
        except Exception as exc:  # the job's own error, never the server's
            job.log(f"{type(exc).__name__}: {exc}", "error")
            job.log(traceback.format_exc().strip().splitlines()[-1], "error")
            job._finish("failed", error=f"{type(exc).__name__}: {exc}")
        else:
            if job.cancelled:
                job._finish("timeout" if job.cancel_reason == "time limit" else "cancelled", error=job.cancel_reason, result=result)
            else:
                job._finish("done", result=result)
        finally:
            watchdog.cancel()

    def _timeout(self, job: Job) -> None:
        if job.status in FINAL:
            return
        job.log(f"time limit of {job.time_limit:.0f} s reached; stopping", "warn")
        job.request_cancel("time limit")
        # the worker should notice within a few seconds; if it does not, mark the job finished anyway
        t = threading.Timer(self.grace, lambda: job._finish("timeout", error="time limit"))
        t.daemon = True
        t.start()

    def _prune_locked(self, keep: int = 50) -> None:
        done = [j for j in self._jobs.values() if j.status in FINAL]
        if len(done) <= keep:
            return
        done.sort(key=lambda j: j.finished or 0)
        for j in done[: len(done) - keep]:
            self._jobs.pop(j.id, None)


RUNNER = JobRunner()

__all__ = ["ACTIVE", "FINAL", "Job", "JobBusy", "JobCancelled", "JobRunner", "RUNNER"]

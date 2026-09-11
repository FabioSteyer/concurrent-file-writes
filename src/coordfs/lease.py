"""A global write lease, held in a single file.

Only one process may hold the lease at a time. Acquisition relies on
``O_CREAT | O_EXCL``, which the operating system guarantees to be atomic:
either this process created the file or somebody else already had it. No
polling window, no read-then-write race.

Design decision: **there is no time based release.** A lease left behind by a
crashed process stays held until a human clears it. This trades availability
for correctness, and it is deliberate. A timeout would eventually hand the
lease to a second process while the first one might still be mid-write, which
is precisely the situation this whole mechanism exists to prevent. A stuck
lease is visible and annoying; a silently lost change is invisible and
permanent.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from pathlib import Path


class LeaseBusy(RuntimeError):
    """Somebody else holds the lease."""

    def __init__(self, holder: dict):
        self.holder = holder
        super().__init__(f"lease held by {holder.get('owner')!r} since {holder.get('acquired_at')}")


class LeaseLost(RuntimeError):
    """The lease we thought we held is gone or belongs to somebody else."""


@dataclass
class Lease:
    path: Path
    owner: str

    def acquire(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"owner": self.owner, "pid": os.getpid(), "acquired_at": time.time()}
        ).encode()
        try:
            fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            raise LeaseBusy(self._read_holder()) from None
        with os.fdopen(fd, "wb") as handle:
            handle.write(payload)

    def release(self, *, attempts: int = 100, pause: float = 0.01) -> None:
        holder = self._read_holder()
        if not holder:
            raise LeaseLost("lease file is gone")
        if holder.get("owner") != self.owner:
            raise LeaseLost(f"lease now held by {holder.get('owner')!r}")

        # Windows refuses to unlink a file that another process currently has
        # open, even for reading. A waiting process reading the holder name is
        # enough to make this fail, so the delete is retried rather than
        # treated as an error. On POSIX the first attempt always succeeds.
        for attempt in range(attempts):
            try:
                self.path.unlink()
                return
            except FileNotFoundError:
                raise LeaseLost("lease file vanished during release") from None
            except PermissionError:
                if attempt == attempts - 1:
                    raise
                time.sleep(pause)

    def _read_holder(self) -> dict:
        try:
            return json.loads(self.path.read_text())
        except (FileNotFoundError, json.JSONDecodeError):
            return {}
        except PermissionError:
            # Being written or deleted right now. Treat as "cannot tell".
            return {}

    def held_by(self) -> str | None:
        return self._read_holder().get("owner")

    def __enter__(self) -> "Lease":
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        # On an undeclared-change abort the caller releases nothing on purpose;
        # see coordinator.commit. Here we only release what we still own.
        if self.held_by() == self.owner:
            self.release()

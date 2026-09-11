"""Two workers doing the same job, one with the protocol and one without.

Both append a line to a shared file using read - modify - write, with a small
pause between reading and writing. That pause is not a trick to make the
naive version fail: it stands in for whatever real work happens between
reading a file and saving it, which in an agent is a model call lasting
seconds. Without coordination, any overlap in that window loses a write.
"""

from __future__ import annotations

import time
from pathlib import Path

from .coordinator import Coordinator, StaleExpectedHash, UndeclaredChange
from .journal import Journal, hash_file
from .lease import LeaseBusy

TARGET = "shared.txt"
THINK_TIME = 0.02


def _modify(text: str, worker_id: str, round_number: int) -> str:
    return text + f"{worker_id} round {round_number}\n"


def naive_round(root: Path, state_dir: Path, worker_id: str, round_number: int) -> str:
    """No lease, no hash check. Records what it did, so gaps become visible."""
    target = Path(root) / TARGET
    journal = Journal(Path(state_dir) / "journal.sqlite")

    before = hash_file(target)
    text = target.read_text(encoding="utf-8") if target.exists() else ""
    time.sleep(THINK_TIME)
    target.write_text(_modify(text, worker_id, round_number), encoding="utf-8")
    after = hash_file(target)

    journal.record(f"naive-{worker_id}-{round_number}", {TARGET: (before, after)})
    return "written"


def coordinated_round(
    root: Path, state_dir: Path, worker_id: str, round_number: int, attempts: int = 200
) -> str:
    """The protocol: declare, get permission, write, commit."""
    target = Path(root) / TARGET
    coordinator = Coordinator(Path(root), Path(state_dir), owner=worker_id)

    for _ in range(attempts):
        expected = {TARGET: hash_file(target)}
        try:
            txn = coordinator.begin([TARGET], expected)
        except LeaseBusy:
            time.sleep(0.005)
            continue
        except StaleExpectedHash:
            # Somebody committed between our read and our request. Read again.
            continue

        try:
            text = target.read_text(encoding="utf-8") if target.exists() else ""
            time.sleep(THINK_TIME)
            target.write_text(_modify(text, worker_id, round_number), encoding="utf-8")
        except BaseException:
            # Nothing may have been written yet; give the lease back if the
            # tree is still untouched, otherwise let the abort complain.
            coordinator.abort(txn)
            raise

        # Past this point the write happened. A failing commit must not be
        # turned into an abort: the tree has changed, and abort would only
        # report that change as undeclared and hide the real cause.
        coordinator.commit(txn)
        return "committed"

    return "gave up"

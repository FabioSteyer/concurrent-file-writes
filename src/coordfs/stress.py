"""Run several processes against the same file, with and without the protocol.

The comparison is the point of this repository. Both runs do exactly the same
work; only the coordination differs.
"""

from __future__ import annotations

import multiprocessing as mp
from pathlib import Path

from .journal import Journal
from .verify import find_gaps
from .worker import TARGET, coordinated_round, naive_round


def _run_worker(mode: str, root: str, state_dir: str, worker_id: str, rounds: int) -> list[str]:
    fn = coordinated_round if mode == "coordinated" else naive_round
    return [fn(Path(root), Path(state_dir), worker_id, r) for r in range(rounds)]


def run(mode: str, workspace: Path, workers: int = 4, rounds: int = 5) -> dict:
    """Start `workers` processes, each appending `rounds` lines."""
    root = workspace / "files"
    state_dir = workspace / "state"
    root.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    (root / TARGET).write_text("", encoding="utf-8")

    context = mp.get_context("spawn")
    with context.Pool(workers) as pool:
        pool.starmap(
            _run_worker,
            [
                (mode, str(root), str(state_dir), f"w{i}", rounds)
                for i in range(workers)
            ],
        )

    expected_lines = workers * rounds
    actual_lines = len(
        [line for line in (root / TARGET).read_text(encoding="utf-8").splitlines() if line]
    )
    journal = Journal(state_dir / "journal.sqlite")
    gaps = find_gaps(journal)

    return {
        "mode": mode,
        "workers": workers,
        "rounds": rounds,
        "expected_lines": expected_lines,
        "actual_lines": actual_lines,
        "lost_writes": expected_lines - actual_lines,
        "journal_entries": len(journal.entries_for(TARGET)),
        "gaps": len(gaps),
        "gap_detail": [str(g) for g in gaps[:5]],
    }

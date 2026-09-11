"""Check the journal for gaps.

For each path the entries must form a chain: the "before" hash of every entry
equals the "after" hash of the one before it, and the very first entry starts
from whatever the file was at the time (possibly nothing).

A gap is not a warning. It is proof that a write happened outside the
protocol, and that whatever the skipped state contained is gone.
"""

from __future__ import annotations

from dataclasses import dataclass

from .journal import Journal


@dataclass(frozen=True)
class Gap:
    path: str
    after_index: int
    expected_before: str | None
    actual_before: str | None

    def __str__(self) -> str:
        return (
            f"{self.path}: entry {self.after_index} starts from "
            f"{_short(self.actual_before)} but the previous entry left "
            f"{_short(self.expected_before)}"
        )


def _short(h: str | None) -> str:
    return "(absent)" if h is None else h[:12]


def find_gaps(journal: Journal) -> list[Gap]:
    gaps: list[Gap] = []
    for path in journal.paths():
        entries = journal.entries_for(path)
        for index in range(1, len(entries)):
            previous_after = entries[index - 1].after_hash
            this_before = entries[index].before_hash
            if this_before != previous_after:
                gaps.append(Gap(path, index, previous_after, this_before))
    return gaps


def summarise(journal: Journal) -> dict:
    gaps = find_gaps(journal)
    return {
        "paths": len(journal.paths()),
        "entries": sum(len(journal.entries_for(p)) for p in journal.paths()),
        "gaps": len(gaps),
        "detail": [str(g) for g in gaps],
    }

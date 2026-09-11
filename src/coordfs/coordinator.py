"""The write protocol.

    begin(paths, expected_hashes) -> Transaction
    ... the caller writes ...
    commit(transaction)   or   abort(transaction)

Three rules, and each of them is a decision that could have gone the other
way:

1. **Hashes, not timestamps.** A file's modification time is coarse (whole
   seconds on some filesystems), it can move backwards, and anything can set
   it. Content identity is the only thing that cannot lie about content.

2. **An undeclared change holds the lease.** If, at commit time, a file
   changed that nobody declared, the transaction fails *and the lease stays
   held*. Releasing it would let the next process build on a state nobody
   has looked at. Somebody has to look first.

3. **Only declared paths may change.** "It was only an internal file" is not
   an exception; an undeclared write is exactly the thing the protocol is
   supposed to make impossible.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path

from .journal import Journal, hash_file
from .lease import Lease


class StaleExpectedHash(RuntimeError):
    """A file changed between reading it and asking for permission."""


class UndeclaredChange(RuntimeError):
    """A file changed that was not part of the transaction."""

    def __init__(self, paths: list[str]):
        self.paths = paths
        super().__init__(f"undeclared change in: {', '.join(paths)}")


@dataclass
class Transaction:
    txn_id: str
    root: Path
    declared: dict[str, str | None]  # relative path -> hash at begin
    lease: Lease
    baseline: dict[str, str | None] = field(default_factory=dict)  # whole tree


class Coordinator:
    def __init__(self, root: Path, state_dir: Path, owner: str):
        self.root = Path(root)
        self.state_dir = Path(state_dir)
        self.owner = owner
        self.journal = Journal(self.state_dir / "journal.sqlite")
        self.lease = Lease(self.state_dir / "write.lease", owner)

    # -- helpers ----------------------------------------------------------

    def _scan(self) -> dict[str, str | None]:
        """Hash every file under the root. Small trees only - see README."""
        out: dict[str, str | None] = {}
        for path in sorted(self.root.rglob("*")):
            if path.is_file():
                out[path.relative_to(self.root).as_posix()] = hash_file(path)
        return out

    def current_hash(self, rel_path: str) -> str | None:
        return hash_file(self.root / rel_path)

    # -- protocol ---------------------------------------------------------

    def begin(self, paths: list[str], expected: dict[str, str | None]) -> Transaction:
        if not paths:
            raise ValueError("a transaction must declare at least one path")
        missing = set(paths) - set(expected)
        if missing:
            raise ValueError(f"no expected hash given for: {sorted(missing)}")

        self.lease.acquire()
        try:
            stale = {
                p: (expected[p], self.current_hash(p))
                for p in paths
                if expected[p] != self.current_hash(p)
            }
            if stale:
                raise StaleExpectedHash(
                    "expected hash no longer matches for: " + ", ".join(sorted(stale))
                )
            txn = Transaction(
                txn_id=uuid.uuid4().hex,
                root=self.root,
                declared={p: expected[p] for p in paths},
                lease=self.lease,
            )
            txn.baseline = self._scan()
            return txn
        except BaseException:
            # Nothing was written yet, so handing the lease on is safe.
            self.lease.release()
            raise

    def commit(self, txn: Transaction) -> dict[str, tuple[str | None, str]]:
        after = self._scan()
        declared = set(txn.declared)

        changed = {
            p
            for p in set(after) | set(txn.baseline)
            if after.get(p) != txn.baseline.get(p)
        }
        undeclared = sorted(changed - declared)
        if undeclared:
            # Rule 2: the lease stays held on purpose.
            raise UndeclaredChange(undeclared)

        written = {
            p: (txn.baseline.get(p), after[p])
            for p in declared
            if after.get(p) is not None and after.get(p) != txn.baseline.get(p)
        }
        if written:
            self.journal.record(txn.txn_id, written)
        self.lease.release()
        return written

    def abort(self, txn: Transaction) -> None:
        """Give the lease back without writing anything to the journal."""
        after = self._scan()
        changed = [
            p
            for p in set(after) | set(txn.baseline)
            if after.get(p) != txn.baseline.get(p)
        ]
        if changed:
            raise UndeclaredChange(sorted(changed))
        self.lease.release()

# Concurrent file writes

Several independent processes work on the same tree of files. There is no
database server to hand out locks — there are only files. Without an
agreement, the slower process silently overwrites what the faster one just
saved, and nobody notices.

This repository shows an agreement that makes that loss impossible, and then
proves it by breaking the rules on purpose and measuring the difference.

No runtime dependencies beyond the standard library.

## The measurement

```bash
python -m venv .venv
.venv/Scripts/activate        # Windows
# source .venv/bin/activate   # Linux, macOS
pip install -e ".[dev]"

python -m coordfs compare --workers 4 --rounds 5
pytest                        # 18 tests
```

Four processes, five appends each, twenty writes expected. Both runs do the
same work; only the coordination differs:

```
  mode            naive              mode            coordinated
  lines expected  20                 lines expected  20
  lines present   6                  lines present   20
  writes lost     14                 writes lost     0
  chain gaps      18                 chain gaps      0
```

Fourteen of twenty writes gone, in a run that reports no errors anywhere. That
is what makes this class of bug expensive: nothing crashes.

## How the loss is detected

Every committed write appends an entry to a journal: the hash of the file
before, and the hash after. A correct history forms an unbroken chain per
path — the *before* of each entry is the *after* of the previous one.

A gap in that chain is not a warning. It is proof that somebody wrote outside
the protocol, and that exactly one intermediate state is gone:

```
shared.txt: entry 3 starts from e3b0c44298fc but the previous entry left 3e327f5171ee
```

The file alone cannot tell you this. Its content simply looks shorter than it
should, and only if you happen to know what to expect.

## Three decisions, and why they went that way

**Hashes, not timestamps.** A modification time is coarse — whole seconds on
some filesystems — it can move backwards across a clock change, and any
process can set it to anything. Content identity is the only property that
cannot lie about content.

**No time based release.** A lease left behind by a crashed process stays held
until a person clears it. A timeout would eventually hand the lease to a
second process while the first might still be writing, which is exactly the
situation the mechanism exists to prevent. This trades availability for
correctness on purpose: a stuck lease is visible and annoying, a lost change
is invisible and permanent.

**An undeclared change holds the lease.** If a file changed at commit time
that nobody declared, the transaction fails *and the lease is not released*.
Handing it on would let the next process build on a state nobody has looked
at. Somebody has to look first. `tests/test_protocol.py` pins this down: after
such a failure, a second process is refused.

## The protocol

```python
expected = {"notes.md": hash_file(root / "notes.md")}
txn = coordinator.begin(["notes.md"], expected)   # acquires the lease
(root / "notes.md").write_text(new_text)
coordinator.commit(txn)                            # verifies, journals, releases
```

`begin` refuses if a declared file no longer matches the hash the caller saw
(`StaleExpectedHash`) — then the caller reads again and decides anew, because
the decision may no longer make sense against the new content. `commit`
refuses if anything outside the declared set changed (`UndeclaredChange`).

## A Windows problem that only the multi-process run found

The single-process tests passed while the four-process run crashed with
`PermissionError: [WinError 32]` on releasing the lease. Windows refuses to
delete a file that another process currently has open — and a waiting worker
reading the holder's name to report "busy" is enough to trigger it. On Linux
the same code would have run green forever.

The release now retries the unlink, and reading the holder treats a locked
file as "cannot tell" rather than as an error. The lesson is in the test
layout rather than in the fix: concurrency code tested only single threaded
has not been tested.

## What this does not show

- **Not a distributed system.** One machine, one filesystem. Coordination
  across hosts is a different problem with different failure modes.
- **Not a lock manager.** One global lease, not per-file locks. Simple, and it
  serialises everything — fine when writes are rare and reads are not, wrong
  when many processes write constantly.
- **The full-tree scan does not scale.** Detecting undeclared changes hashes
  every file under the root, twice per transaction. That is acceptable for
  hundreds of files and wrong for hundreds of thousands.
- **Crash recovery is manual by design.** See the second decision above.

## Layout

```
src/coordfs/
  journal.py      append-only record of before/after hashes
  lease.py        the global lease, O_CREAT|O_EXCL, no timeout
  coordinator.py  begin / commit / abort and the three rules
  verify.py       find gaps in the hash chain
  worker.py       the same job, with and without the protocol
  stress.py       run several processes and compare
  cli.py          compare
tests/
  test_protocol.py  12 cases: stale hash, undeclared change, held lease, crash
  test_stress.py     6 cases: the comparison itself, with real processes
```

## On AI assistance

This repository was written with AI assistance. The problem, the three
decisions recorded above and the review of the result are mine. The Windows
locking failure was found by running the multi-process comparison, not by
reasoning about it beforehand.

## Licence

MIT. See `LICENSE`.

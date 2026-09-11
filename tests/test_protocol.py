"""The protocol, case by case."""

import pytest

from coordfs.coordinator import Coordinator, StaleExpectedHash, UndeclaredChange
from coordfs.journal import hash_file
from coordfs.lease import LeaseBusy


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "files"
    root.mkdir()
    (root / "a.txt").write_text("one\n", encoding="utf-8")
    (root / "b.txt").write_text("two\n", encoding="utf-8")
    return root, tmp_path / "state"


def coord(workspace, owner="w1"):
    root, state = workspace
    return Coordinator(root, state, owner)


def test_a_clean_write_commits_and_is_journalled(workspace):
    root, _ = workspace
    c = coord(workspace)
    txn = c.begin(["a.txt"], {"a.txt": hash_file(root / "a.txt")})
    (root / "a.txt").write_text("one\nthree\n", encoding="utf-8")
    written = c.commit(txn)
    assert list(written) == ["a.txt"]
    assert len(c.journal.entries_for("a.txt")) == 1


def test_a_stale_expected_hash_is_refused(workspace):
    root, _ = workspace
    c = coord(workspace)
    stale = hash_file(root / "a.txt")
    (root / "a.txt").write_text("changed by somebody else\n", encoding="utf-8")
    with pytest.raises(StaleExpectedHash):
        c.begin(["a.txt"], {"a.txt": stale})


def test_a_refused_begin_leaves_the_lease_free(workspace):
    root, _ = workspace
    c = coord(workspace)
    stale = hash_file(root / "a.txt")
    (root / "a.txt").write_text("x\n", encoding="utf-8")
    with pytest.raises(StaleExpectedHash):
        c.begin(["a.txt"], {"a.txt": stale})
    assert c.lease.held_by() is None


def test_only_one_holder_at_a_time(workspace):
    root, _ = workspace
    first = coord(workspace, "w1")
    second = coord(workspace, "w2")
    first.begin(["a.txt"], {"a.txt": hash_file(root / "a.txt")})
    with pytest.raises(LeaseBusy):
        second.begin(["b.txt"], {"b.txt": hash_file(root / "b.txt")})


def test_an_undeclared_change_fails_the_commit(workspace):
    root, _ = workspace
    c = coord(workspace)
    txn = c.begin(["a.txt"], {"a.txt": hash_file(root / "a.txt")})
    (root / "a.txt").write_text("declared\n", encoding="utf-8")
    (root / "b.txt").write_text("NOT declared\n", encoding="utf-8")
    with pytest.raises(UndeclaredChange) as raised:
        c.commit(txn)
    assert raised.value.paths == ["b.txt"]


def test_an_undeclared_change_keeps_the_lease_held(workspace):
    """The decision that matters: nobody proceeds until a human has looked."""
    root, _ = workspace
    c = coord(workspace, "w1")
    txn = c.begin(["a.txt"], {"a.txt": hash_file(root / "a.txt")})
    (root / "b.txt").write_text("NOT declared\n", encoding="utf-8")
    with pytest.raises(UndeclaredChange):
        c.commit(txn)
    assert c.lease.held_by() == "w1"

    other = coord(workspace, "w2")
    with pytest.raises(LeaseBusy):
        other.begin(["a.txt"], {"a.txt": hash_file(root / "a.txt")})


def test_a_new_file_may_be_declared_with_a_none_hash(workspace):
    root, _ = workspace
    c = coord(workspace)
    txn = c.begin(["c.txt"], {"c.txt": None})
    (root / "c.txt").write_text("new\n", encoding="utf-8")
    written = c.commit(txn)
    assert written["c.txt"][0] is None


def test_abort_releases_the_lease_when_nothing_changed(workspace):
    root, _ = workspace
    c = coord(workspace)
    txn = c.begin(["a.txt"], {"a.txt": hash_file(root / "a.txt")})
    c.abort(txn)
    assert c.lease.held_by() is None
    assert c.journal.entries_for("a.txt") == []


def test_abort_refuses_when_something_did_change(workspace):
    root, _ = workspace
    c = coord(workspace)
    txn = c.begin(["a.txt"], {"a.txt": hash_file(root / "a.txt")})
    (root / "a.txt").write_text("half written\n", encoding="utf-8")
    with pytest.raises(UndeclaredChange):
        c.abort(txn)


def test_a_crashed_transaction_does_not_release_the_lease(workspace):
    """No time based release: a lease left behind stays until cleared."""
    root, state = workspace
    c = coord(workspace, "crashed")
    c.begin(["a.txt"], {"a.txt": hash_file(root / "a.txt")})
    del c  # the process is gone; nothing runs on its behalf

    revived = Coordinator(root, state, "somebody-else")
    assert revived.lease.held_by() == "crashed"
    with pytest.raises(LeaseBusy):
        revived.begin(["a.txt"], {"a.txt": hash_file(root / "a.txt")})


def test_a_transaction_must_declare_something(workspace):
    c = coord(workspace)
    with pytest.raises(ValueError):
        c.begin([], {})


def test_every_declared_path_needs_an_expected_hash(workspace):
    root, _ = workspace
    c = coord(workspace)
    with pytest.raises(ValueError):
        c.begin(["a.txt", "b.txt"], {"a.txt": hash_file(root / "a.txt")})

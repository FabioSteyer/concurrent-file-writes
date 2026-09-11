"""The comparison, as a test.

These are slower than the protocol tests because they start real processes.
That is the point: a mechanism for concurrent writes that is only ever tested
single threaded has not been tested.
"""

import pytest

from coordfs.stress import run

WORKERS = 4
ROUNDS = 4


@pytest.fixture(scope="module")
def naive_result(tmp_path_factory):
    return run("naive", tmp_path_factory.mktemp("naive"), workers=WORKERS, rounds=ROUNDS)


@pytest.fixture(scope="module")
def coordinated_result(tmp_path_factory):
    return run(
        "coordinated", tmp_path_factory.mktemp("coord"), workers=WORKERS, rounds=ROUNDS
    )


def test_the_coordinated_run_loses_nothing(coordinated_result):
    assert coordinated_result["lost_writes"] == 0
    assert coordinated_result["actual_lines"] == WORKERS * ROUNDS


def test_the_coordinated_chain_has_no_gaps(coordinated_result):
    assert coordinated_result["gaps"] == 0, coordinated_result["gap_detail"]


def test_every_coordinated_write_is_journalled(coordinated_result):
    assert coordinated_result["journal_entries"] == WORKERS * ROUNDS


def test_the_naive_run_loses_writes(naive_result):
    """If this ever passes with zero losses, the comparison proves nothing
    and the think-time window has to be widened."""
    assert naive_result["lost_writes"] > 0


def test_lost_writes_show_up_as_chain_gaps(naive_result):
    """The journal is supposed to make the loss visible, not just the file."""
    assert naive_result["gaps"] > 0


def test_the_two_runs_differ_in_the_way_that_matters(naive_result, coordinated_result):
    assert naive_result["lost_writes"] > coordinated_result["lost_writes"]
    assert naive_result["gaps"] > coordinated_result["gaps"]

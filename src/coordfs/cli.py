"""    python -m coordfs compare --workers 4 --rounds 5"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

from .stress import run


def _print(result: dict) -> None:
    print(f"  mode            {result['mode']}")
    print(f"  processes       {result['workers']} x {result['rounds']} rounds")
    print(f"  lines expected  {result['expected_lines']}")
    print(f"  lines present   {result['actual_lines']}")
    print(f"  writes lost     {result['lost_writes']}")
    print(f"  journal entries {result['journal_entries']}")
    print(f"  chain gaps      {result['gaps']}")
    for detail in result["gap_detail"]:
        print(f"      {detail}")


def cmd_compare(args) -> int:
    workspace = Path(args.workspace) if args.workspace else Path(tempfile.mkdtemp(prefix="coordfs-"))
    created = args.workspace is None
    try:
        results = []
        for mode in ("naive", "coordinated"):
            target = workspace / mode
            if target.exists():
                shutil.rmtree(target)
            print("=" * 60)
            result = run(mode, target, workers=args.workers, rounds=args.rounds)
            _print(result)
            results.append(result)
        print("=" * 60)

        naive, coordinated = results
        ok = coordinated["lost_writes"] == 0 and coordinated["gaps"] == 0
        print(
            f"naive lost {naive['lost_writes']} write(s) with {naive['gaps']} chain gap(s); "
            f"coordinated lost {coordinated['lost_writes']} with {coordinated['gaps']}"
        )
        if not ok:
            print("FAIL: the coordinated run is supposed to lose nothing")
        return 0 if ok else 1
    finally:
        if created:
            shutil.rmtree(workspace, ignore_errors=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="coordfs")
    sub = parser.add_subparsers(dest="command", required=True)

    c = sub.add_parser("compare", help="run both modes and report")
    c.add_argument("--workers", type=int, default=4)
    c.add_argument("--rounds", type=int, default=5)
    c.add_argument("--workspace", default=None, help="keep the run in this folder")
    c.set_defaults(func=cmd_compare)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

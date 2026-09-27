"""Generate a synthetic planning instance and write it to JSON.

    python scripts/generate.py [--seed 42] [--tasks 20] [--days 7] [-o PATH]
"""

from __future__ import annotations

import argparse
import pathlib
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from src.adapters import SyntheticDataSource  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--tasks", type=int, default=20)
    ap.add_argument("--days", type=int, default=7)
    ap.add_argument("--sections", type=int, default=5)
    ap.add_argument("-o", "--out", default="data/instance.json")
    args = ap.parse_args()

    source = SyntheticDataSource(
        seed=args.seed,
        n_tasks=args.tasks,
        horizon_days=args.days,
        n_sections=args.sections,
    )
    instance = source.load()

    out = pathlib.Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(instance.model_dump_json(indent=2))

    print(source.describe())
    print(f"wrote {out}  ({out.stat().st_size:,} bytes)")
    print(f"instance_id: {instance.instance_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

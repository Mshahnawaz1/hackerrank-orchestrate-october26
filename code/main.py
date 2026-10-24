"""CLI entry point: reads dataset/, writes output.csv at the repo root.

Usage:
  python3 code/main.py                  # full run -> output.csv
  python3 code/main.py --sample         # run the sample requests (add --out PATH to save)
  python3 code/main.py --case case_01   # one case, prints the row
  python3 code/main.py --ingest-report  # observation counts per evidence file
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent import config, ingest, io, pipeline, serialize  # noqa: E402


def ingest_report() -> None:
    store, counts = ingest.ingest_all()
    for file_id, n in counts.items():
        print(f"{file_id}\t{'deferred' if n is None else n}")
    print(f"total observations: {len(store)}")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sample", action="store_true", help="run on the sample requests")
    ap.add_argument("--case", help="run a single case_id")
    ap.add_argument("--out", type=Path, help="output path (default: repo-root output.csv; none for --sample)")
    ap.add_argument("--ingest-report", action="store_true", help="print observation counts per file")
    args = ap.parse_args()

    if args.ingest_report:
        ingest_report()
        return 0

    requests = io.load_requests(sample=args.sample)
    if args.case:
        requests = [r for r in requests if r["case_id"] == args.case]
        if not requests:
            print(f"unknown case {args.case}", file=sys.stderr)
            return 1
    rows = pipeline.run(requests)

    errors = serialize.validate_output(rows, [r["case_id"] for r in requests])
    if errors:
        print("\n".join(errors[:20]), file=sys.stderr)
        return 1
    if args.case:
        print(rows[0])
        return 0
    out = args.out or (None if args.sample else config.OUTPUT)
    if out:
        io.write_output(rows, out)
    print(f"{len(rows)} rows" + (f" written to {out}" if out else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())

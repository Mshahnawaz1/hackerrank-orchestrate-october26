"""CLI orchestrator: reads dataset/, writes output.csv at the repo root.

Usage:
  python3 code/main.py                # full run -> output.csv
  python3 code/main.py --sample       # sample requests -> stdout summary + sample_pred.csv
  python3 code/main.py --case case_01 # one case, prints the row
  python3 code/main.py --ingest-report # observation counts per evidence file
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from agent import config, ingest, intent, io, serialize  # noqa: E402


def solve_case(request: dict) -> dict:
    """Non-deletion requests are NOT_APPLICABLE; the rest fall back to INCOMPLETE until later stages land."""
    if intent.classify(request["request_text"]).authorizes_deletion is False:
        return {"case_id": request["case_id"], "deletion_status": "NOT_APPLICABLE", "steps_json": "[]"}
    return {
        "case_id": request["case_id"],
        "deletion_status": config.FALLBACK_STATUS,
        "steps_json": serialize.serialize_steps([]),
    }


def run(requests: list[dict]) -> list[dict]:
    rows = []
    for req in requests:
        try:
            rows.append(solve_case(req))
        except Exception as e:  # a valid row is always protected by the fallback
            print(f"{req['case_id']}: fallback after error: {e}", file=sys.stderr)
            rows.append({"case_id": req["case_id"],
                         "deletion_status": config.FALLBACK_STATUS,
                         "steps_json": "[]"})
    return sorted(rows, key=lambda r: r["case_id"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", action="store_true", help="run on sample requests")
    ap.add_argument("--case", help="run a single case_id")
    ap.add_argument("--out", type=Path, help="output path (default: repo-root output.csv)")
    ap.add_argument("--ingest-report", action="store_true", help="print observation counts per file")
    args = ap.parse_args()

    if args.ingest_report:
        store, counts = ingest.ingest_all()
        for file_id, n in counts.items():
            print(f"{file_id}\t{'deferred' if n is None else n}")
        print(f"total observations: {len(store)}")
        return 0

    requests = io.load_requests(sample=args.sample)
    if args.case:
        requests = [r for r in requests if r["case_id"] == args.case]
        if not requests:
            print(f"unknown case {args.case}", file=sys.stderr)
            return 1
    rows = run(requests)

    errs = serialize.validate_output(rows, [r["case_id"] for r in requests])
    if errs:
        print("\n".join(errs[:20]), file=sys.stderr)
        return 1
    if args.case:
        print(rows[0])
        return 0
    out = args.out or (config.REPO_ROOT / "code" / "cache" / "sample_pred.csv" if args.sample
                       else config.OUTPUT)
    io.write_output(rows, out)
    print(f"wrote {len(rows)} rows to {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

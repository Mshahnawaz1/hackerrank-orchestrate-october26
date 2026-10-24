"""Evaluation harness: status accuracy, step P/R/F1, field accuracy, sequence accuracy.

Usage: python3 code/evaluation/main.py [--pred PATH] [--gold PATH] [--diff]
Defaults: runs the pipeline on the sample requests and scores against sample_output.csv.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import config, io  # noqa: E402
import main as pipeline  # noqa: E402

KEY = ("phase", "system_id", "resource_id", "operation", "state", "evidence_id")


def load(path: Path) -> dict:
    return {r["case_id"]: (r["deletion_status"], json.loads(r["steps_json"]))
            for r in io.read_csv(path)}


def tup(s: dict) -> tuple:
    return tuple(s[k] for k in KEY)


def score(pred: dict, gold: dict, show_diff: bool = False) -> dict:
    n = len(gold)
    status_ok = seq_ok = 0
    tp = fp = fn = 0
    field_hits = {k: 0 for k in KEY}
    aligned = 0
    for cid, (gst, gsteps) in sorted(gold.items()):
        pst, psteps = pred.get(cid, ("MISSING", []))
        status_ok += pst == gst
        gt = [tup(s) for s in gsteps]
        pt = [tup(s) for s in psteps]
        seq_ok += pst == gst and gt == pt
        gset, pset = set(gt), set(pt)
        tp += len(gset & pset)
        fp += len(pset - gset)
        fn += len(gset - pset)
        # field accuracy over steps aligned by (phase, resource_id, operation)
        pidx = {(s["phase"], s["resource_id"], s["operation"]): s for s in psteps}
        for s in gsteps:
            p = pidx.get((s["phase"], s["resource_id"], s["operation"]))
            if p:
                aligned += 1
                for k in KEY:
                    field_hits[k] += p[k] == s[k]
        if show_diff and (pst != gst or gt != pt):
            print(f"{cid}: status {pst} vs {gst}; missing={sorted(gset - pset)} extra={sorted(pset - gset)}")
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {
        "cases": n,
        "status_accuracy": status_ok / n,
        "step_precision": prec, "step_recall": rec, "step_f1": f1,
        "field_accuracy": {k: (field_hits[k] / aligned if aligned else 0.0) for k in KEY},
        "sequence_accuracy": seq_ok / n,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred", type=Path)
    ap.add_argument("--gold", type=Path, default=config.DATASET / "sample_output.csv")
    ap.add_argument("--diff", action="store_true")
    args = ap.parse_args()

    if args.pred:
        pred = load(args.pred)
    else:
        sample = io.load_requests(sample=True)
        pred = {r["case_id"]: (r["deletion_status"], json.loads(r["steps_json"]))
                for r in pipeline.run(sample)}
    print(json.dumps(score(pred, load(args.gold), args.diff), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

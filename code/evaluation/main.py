"""Evaluation harness: status accuracy, step P/R/F1, field accuracy, sequence accuracy.

Usage: python3 code/evaluation/main.py [--pred PATH] [--gold PATH] [--requests PATH] [--diff]
Defaults: runs the pipeline on the sample requests and scores against sample_output.csv.
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent import config, io, pipeline  # noqa: E402

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
    aligned = gold_steps = 0
    confusion = {}
    for cid, (gst, gsteps) in sorted(gold.items()):
        pst, psteps = pred.get(cid, ("MISSING", []))
        status_ok += pst == gst
        confusion[f"{gst} -> {pst}"] = confusion.get(f"{gst} -> {pst}", 0) + 1
        gt = [tup(s) for s in gsteps]
        pt = [tup(s) for s in psteps]
        seq_ok += pst == gst and gt == pt
        gset, pset = set(gt), set(pt)
        tp += len(gset & pset)
        fp += len(pset - gset)
        fn += len(gset - pset)
        # field accuracy: pair each gold step with a predicted step of the same phase and resource
        # (in order), so a wrong operation / state / system / evidence shows up as a field error
        pool = {}
        for s in psteps:
            pool.setdefault((s["phase"], s["resource_id"]), []).append(s)
        gold_steps += len(gsteps)
        for s in gsteps:
            cands = pool.get((s["phase"], s["resource_id"]))
            if cands:
                p = cands.pop(0)
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
        "gold_steps": gold_steps, "aligned_steps": aligned,
        "field_accuracy": {k: (field_hits[k] / aligned if aligned else 0.0) for k in KEY},
        "field_accuracy_all_gold_steps": {k: (field_hits[k] / gold_steps if gold_steps else 0.0) for k in KEY},
        "status_confusion": dict(sorted(confusion.items())),
        "sequence_accuracy": seq_ok / n,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pred", type=Path)
    ap.add_argument("--gold", type=Path, default=config.DATASET / "sample_output.csv")
    ap.add_argument("--requests", type=Path, help="request CSV to run the pipeline on (default: sample requests)")
    ap.add_argument("--diff", action="store_true")
    args = ap.parse_args()

    if args.pred:
        pred = load(args.pred)
    else:
        sample = io.read_csv(args.requests) if args.requests else io.load_requests(sample=True)
        pred = {r["case_id"]: (r["deletion_status"], json.loads(r["steps_json"]))
                for r in pipeline.run(sample)}
    print(json.dumps(score(pred, load(args.gold), args.diff), indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())

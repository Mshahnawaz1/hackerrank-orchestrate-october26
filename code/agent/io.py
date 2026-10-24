"""CSV loaders and the output writer."""
import csv
from pathlib import Path

from . import config


def read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def load_requests(sample: bool = False) -> list[dict]:
    name = "sample_deletion_requests.csv" if sample else "deletion_requests.csv"
    return read_csv(config.DATASET / name)


def load_identities() -> list[dict]:
    return read_csv(config.DATASET / "user_identities.csv")


def load_audit_log() -> list[dict]:
    return read_csv(config.DATASET / "user_audit_log.csv")


def load_activity() -> list[dict]:
    return read_csv(config.DATASET / "system_activity.csv")


def load_rules() -> list[dict]:
    return read_csv(config.DATASET / "deletion_rules.csv")


def load_manifest() -> list[dict]:
    return read_csv(config.DATASET / "evidence_files.csv")


def write_output(rows: list[dict], path: Path = config.OUTPUT) -> None:
    """rows: dicts with case_id, deletion_status, steps_json (str). Sorted by case_id."""
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=config.OUTPUT_COLUMNS, lineterminator="\n")
        w.writeheader()
        for r in sorted(rows, key=lambda r: r["case_id"]):
            w.writerow({k: r[k] for k in config.OUTPUT_COLUMNS})

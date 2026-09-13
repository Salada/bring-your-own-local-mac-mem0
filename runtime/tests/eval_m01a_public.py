"""Optional network check of M01a candidate leads on public, out-of-domain pairs."""

from __future__ import annotations

import json
import runpy
import urllib.parse
import urllib.request
from collections import Counter
from pathlib import Path

RUNTIME = Path(__file__).resolve().parents[1]
CANDIDATE_REPORT = runpy.run_path(str(RUNTIME / "bin" / "mem0-admin"))["candidate_report"]
DATASETS = (
    (
        "klue/klue",
        "nli",
        "validation",
        "349481ec73fff722f88e0453ca05c77a447d967c",
        (0, 1000),
        ("premise", "hypothesis"),
        {0: "entailment", 1: "neutral", 2: "contradiction"},
        {"contradiction": (23, 67), "entailment": (28, 66), "neutral": (14, 67)},
    ),
    (
        "sentence-transformers/quora-duplicates",
        "pair-class",
        "train",
        "41f699770310302022a4dd75d4cf903bfef9ea46",
        (0, 10000),
        ("sentence1", "sentence2"),
        {0: "different", 1: "duplicate"},
        {"different": (57, 129), "duplicate": (57, 71)},
    ),
)


def fetch_rows(dataset: str, config: str, split: str, offset: int, revision: str) -> list[dict]:
    query = urllib.parse.urlencode(
        {"dataset": dataset, "config": config, "split": split, "offset": offset, "length": 100}
    )
    with urllib.request.urlopen(f"https://datasets-server.huggingface.co/rows?{query}", timeout=60) as response:
        if response.headers.get("x-revision") != revision:
            raise RuntimeError(f"{dataset}: dataset revision changed; do not compare old counts")
        payload = json.load(response)
    rows = payload["rows"]
    if payload.get("partial") or len(rows) != 100 or any(row.get("truncated_cells") for row in rows):
        raise RuntimeError(f"{dataset}: incomplete or truncated dataset-server rows")
    return [row["row"] for row in rows]


def flagged(left: str, right: str) -> bool:
    pair = [
        {"id": str(i), "memory": text, "user_id": "public-eval", "metadata": {"type": "decision"}}
        for i, text in enumerate((left, right))
    ]
    return any(CANDIDATE_REPORT(pair, None, 1)["candidate_counts"].values())


def main() -> None:
    for dataset, config, split, revision, offsets, fields, labels, expected in DATASETS:
        counts: dict[str, Counter[str]] = {label: Counter() for label in labels.values()}
        for offset in offsets:
            for row in fetch_rows(dataset, config, split, offset, revision):
                result = counts[labels[row["label"]]]
                result["total"] += 1
                result["flagged"] += flagged(row[fields[0]], row[fields[1]])
        actual = {label: (count["flagged"], count["total"]) for label, count in counts.items()}
        if actual != expected:
            raise RuntimeError(f"{dataset}: counts changed; inspect source and adapter before citing")
        print(json.dumps({"dataset": dataset, "revision": revision, "counts": actual}, sort_keys=True))


if __name__ == "__main__":
    main()

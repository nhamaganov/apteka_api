import csv
from typing import List, Dict
from pathlib import Path


def write_csv(path: Path, items: List[Dict]) -> None:
    """Берёт items и сохраняет их в CSV по пути path"""
    path.parent.mkdir(parents=True, exist_ok=True)
    if not items:
        path.write_text("", encoding="utf-8")
        return

    keys = set()
    for it in items:
        keys.update(it.keys())

    preferred = ["input_name", "title", "price", "input_qty", "found_qty", "message"]
    fieldnames = [k for k in preferred if k in keys] + sorted(k for k in keys if k not in preferred)

    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=fieldnames,
            extrasaction="ignore",
            delimiter=";"
        )
        writer.writeheader()
        writer.writerows(items)
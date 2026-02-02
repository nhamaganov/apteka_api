import csv
from typing import List, Dict
from pathlib import Path


def write_csv(path: Path, items: List[Dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not items:
        path.write_text("", encoding="utf-8")
        return

    fieldnames = list(items[0].keys()) 

    with path.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(items)
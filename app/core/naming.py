from pathlib import Path
import re

def make_display_name(filename: str) -> str:
    base = Path(filename).name
    stem = Path(base).stem
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem or base
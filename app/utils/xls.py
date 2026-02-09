import re
from typing import Optional, Tuple
import pandas as pd


def extract_queries_from_excel(path: str) -> list[dict]:
    """Из передаваемого excel-файла возвращает все названия и количества препаратов"""
    df = pd.read_excel(path, header=None)

    header_row = header_col = None

    for r in range(df.shape[0]):
        for c in range(df.shape[1]):
            cell = str(df.iat[r, c]).lower()
            if "наименование товара" in cell:
                header_row, header_col = r, c
                break
        if header_row is not None:
            break
    
    if header_row is None:
        raise ValueError("Не найден столбец 'Наименование товара'")
    
    col = (
        df.iloc[header_row + 1 :, header_col]
        .dropna()  # Удаляет пустые строки
        .astype(str)
    )
    
    seen = set()
    queries: list[dict] = []

    for raw in col.tolist():
        name = raw.split("(", 1)[0].strip()
        if not name:
            continue
        
        qty, qty_is_sum = extract_qty_from_xls_row(raw)

        key = (name.lower(), qty)
        if key in seen:
            continue
        seen.add(key)


        queries.append({
            "name": name,
            "qty": qty,
            "qty_is_sum": qty_is_sum,
            "row": raw, # потом можно убрать, для лога!!! 
        })

    return queries


def extract_qty_from_xls_row(text: str) -> Tuple[Optional[int], bool]:
    """Возвращает количество из передаваемого текста"""
    if not text:
        return None, False

    m = re.search(r"\bN\s*([\d+]+)\b", text, flags=re.IGNORECASE)
    if not m:
        return None, False

    raw = m.group(1)
    if "+" in raw:
        parts = [p for p in raw.split("+") if p.isdigit()]
        if not parts:
            return None, True
        return sum(int(p) for p in parts), True
    return int(raw), False
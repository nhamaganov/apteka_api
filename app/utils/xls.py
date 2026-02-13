import re
from typing import Optional, Tuple
import pandas as pd
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Side, Font, PatternFill
from openpyxl.utils import get_column_letter



def build_query_name(raw: str) -> str:

    base_name = raw.split("(", 1)[0].strip()
    if not base_name:
        return ""

    normalized = base_name.lower().replace("ё", "е")
    if "линдинет" not in normalized:
        return base_name
    
    variant_match = re.search(r"\b(20|30)\b", raw)
    if not variant_match:
        return base_name
    
    return f"{base_name} {variant_match.group(1)}"


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
        name = build_query_name(raw)
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


def build_enriched_xlsx(path: str, out_path: str, items: list[dict]) -> None:
    """Дополняет исходную таблицу результатами парсинга и сохраняет как XLSX."""
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

    def _is_empty(v) -> bool:
        if pd.isna(v):
            return True
        return str(v).strip() == ""

    def _key(name: str) -> str:
        return (name or "").strip().lower().replace("ё", "е")

    by_input_name: dict[str, list[dict]] = {}
    for item in items:
        key = _key(str(item.get("input_name") or ""))
        if not key:
            continue
        by_input_name.setdefault(key, []).append(item)

    extra_headers = [
        "Найденный товар",
        "Цена",
        "Сообщение",
    ]

    def _column_is_empty(col_idx: int) -> bool:
        if col_idx >= df.shape[1]:
            return True
        for row_idx in range(header_row, df.shape[0]):
            if not _is_empty(df.iat[row_idx, col_idx]):
                return False
        return True

    insert_col = header_col + 1
    while True:
        block_is_free = True
        for offset in range(len(extra_headers)):
            if not _column_is_empty(insert_col + offset):
                block_is_free = False
                break
        if block_is_free:
            break
        insert_col += 1

    required_cols = insert_col + len(extra_headers)
    while df.shape[1] < required_cols:
        df[df.shape[1]] = None

    for offset, name in enumerate(extra_headers):
        df.iat[header_row, insert_col + offset] = name

    for r in range(header_row + 1, df.shape[0]):
        raw = df.iat[r, header_col]
        if _is_empty(raw):
            continue

        raw_text = str(raw)
        query_name = build_query_name(raw_text)
        if not query_name:
            continue

        query_qty, _ = extract_qty_from_xls_row(raw_text)
        candidates = by_input_name.get(_key(query_name), [])
        if not candidates:
            continue

        item = None
        if query_qty is not None:
            for candidate in candidates:
                if candidate.get("input_qty") == query_qty:
                    item = candidate
                    break
            if item is None:
                # Если в строке есть явное количество, не подставляем запись
                # с другим количеством, чтобы не перепутать соседние позиции.
                continue
        else:
            for candidate in candidates:
                if candidate.get("input_qty") is None:
                    item = candidate
                    break
            if item is None:
                item = candidates[0]

        row_values = [
            item.get("title", ""),
            item.get("price", ""),
            item.get("message", ""),
        ]
        for offset, value in enumerate(row_values):
            df.iat[r, insert_col + offset] = value

    wb = Workbook()
    ws = wb.active

    source_side = Side(style="thin", color="000000")
    parsed_side = Side(style="thin", color="000000")

    ROW_OFFSET = 1 

    base_alignment = Alignment(vertical="top", wrap_text=True)

    for row_idx in range(df.shape[0]):
        for col_idx in range(df.shape[1]):
            value = df.iat[row_idx, col_idx]
            cell = ws.cell(row=row_idx + 1 + ROW_OFFSET, column=col_idx + 1)
            cell.value = "" if pd.isna(value) else value
            cell.alignment = base_alignment

    source_min_col = 1
    source_max_col = insert_col
    parsed_min_col = insert_col + 1
    parsed_max_col = insert_col + len(extra_headers)

    ws.merge_cells(
        start_row=1,
        start_column=source_min_col,
        end_row=1,
        end_column=source_max_col,
    )
    source_header_cell = ws.cell(row=1, column=source_min_col)
    source_header_cell.value = "Входящая информация"
    source_header_cell.alignment = Alignment(horizontal="center", vertical="center")
    source_header_cell.font = Font(size=18, bold=True)
    source_header_cell.fill = PatternFill(fill_type="solid", fgColor="D9EAD3")

    ws.merge_cells(
        start_row=1,
        start_column=parsed_min_col,
        end_row=1,
        end_column=parsed_max_col,
    )
    parsed_header_cell = ws.cell(row=1, column=parsed_min_col)
    parsed_header_cell.value = "Apteka Ru"
    parsed_header_cell.alignment = Alignment(horizontal="center", vertical="center")
    parsed_header_cell.font = Font(size=22, bold=True)
    parsed_header_cell.fill = PatternFill(fill_type="solid", fgColor="D0E0E3")

    def _max_line_len(value: object) -> int:
        text = "" if pd.isna(value) else str(value)
        if not text:
            return 0
        return max((len(line) for line in text.splitlines()), default=0)

    for col_idx in range(df.shape[1]):
        max_len = 0
        for row_idx in range(df.shape[0]):
            max_len = max(max_len, _max_line_len(df.iat[row_idx, col_idx]))

        width = min(max(max_len + 2, 6), 80)
        ws.column_dimensions[get_column_letter(col_idx + 1)].width = width

    def _apply_table_borders(min_row: int, max_row: int, min_col: int, max_col: int, side: Side) -> None:
        if min_row > max_row or min_col > max_col:
            return

        for r in range(min_row, max_row + 1):
            for c in range(min_col, max_col + 1):
                is_top = r == min_row
                is_bottom = r == max_row
                is_left = c == min_col
                is_right = c == max_col
                has_inner_vertical = c > min_col

                cell = ws.cell(row=r + 1 + ROW_OFFSET, column=c + 1)
                border = cell.border
                cell.border = Border(
                    left=side if (is_left or has_inner_vertical) else border.left,
                    right=side if (is_right or has_inner_vertical) else border.right,
                    top=side if is_top else border.top,
                    bottom=side if is_bottom else border.bottom,
                )

    last_row = df.shape[0] - 1
    if last_row >= header_row:
        _apply_table_borders(
            min_row=header_row,
            max_row=last_row,
            min_col=0,
            max_col=insert_col - 1,
            side=source_side,
        )
        _apply_table_borders(
            min_row=header_row,
            max_row=last_row,
            min_col=insert_col,
            max_col=insert_col + len(extra_headers) - 1,
            side=parsed_side,
        )

    wb.save(out_path)



def build_flat_xlsx(out_path: str, items: list[dict]) -> None:
    """Сохраняет плоский список результатов в XLSX без исходной таблицы."""
    columns = ["input_name", "title", "price", "message"]
    df = pd.DataFrame(items, columns=columns)
    df.to_excel(out_path, index=False)


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
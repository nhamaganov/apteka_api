import re
from copy import copy
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

    def _find_list_start_row(frame: pd.DataFrame) -> Optional[int]:
        for row_idx in range(header_row + 1, frame.shape[0]):
            name_cell = frame.iat[row_idx, header_col]
            if _is_empty(name_cell):
                continue

            if header_col > 0:
                order_cell = frame.iat[row_idx, header_col - 1]
                if _is_empty(order_cell):
                    continue

                order_text = str(order_cell).strip()
                if re.fullmatch(r"\d+(?:\.0+)?", order_text):
                    return row_idx
            else:
                return row_idx

        return None

    def _key(name: str) -> str:
        return (name or "").strip().lower().replace("ё", "е")

    def _to_number(value: object) -> Optional[float]:
        if value is None:
            return None
        text_value = str(value).strip()
        if not text_value:
            return None

        normalized = text_value.replace(" ", "").replace(" ", "").replace(",", ".")
        normalized = re.sub(r"[^0-9.\-]", "", normalized)
        if not normalized:
            return None
        try:
            return float(normalized)
        except ValueError:
            return None

    list_start_row = _find_list_start_row(df)

    if list_start_row is not None and list_start_row > header_row + 1:
        subheader_rows = range(header_row, list_start_row)
        for col_idx in range(df.shape[1]):
            parts: list[str] = []
            for row_idx in subheader_rows:
                cell_value = df.iat[row_idx, col_idx]
                if _is_empty(cell_value):
                    continue
                normalized = " ".join(str(cell_value).split())
                if normalized:
                    parts.append(normalized)

            if parts:
                df.iat[header_row, col_idx] = " ".join(parts)

        rows_to_remove = list(range(header_row + 1, list_start_row))
        if rows_to_remove:
            df = df.drop(index=rows_to_remove).reset_index(drop=True)

        list_start_row = header_row + 1

    by_input_name: dict[str, list[dict]] = {}
    for item in items:
        key = _key(str(item.get("input_name") or ""))
        if not key:
            continue
        by_input_name.setdefault(key, []).append(item)

    main_extra_headers = [
        "Цена",
        "Отклонение базовой цены",
        "Отклонение закупочной цены",
        "Отклонение цены нашего сайта",
    ]
    apteka_extra_headers = [
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
        for offset in range(len(main_extra_headers)):
            if not _column_is_empty(insert_col + offset):
                block_is_free = False
                break
        if block_is_free:
            break
        insert_col += 1

    required_cols = insert_col + len(main_extra_headers)
    while df.shape[1] < required_cols:
        df[df.shape[1]] = None

    for offset, name in enumerate(main_extra_headers):
        df.iat[header_row, insert_col + offset] = name

    apteka_rows: dict[int, list[object]] = {}

    base_price_col: Optional[int] = None
    purchase_price_col: Optional[int] = None
    site_price_col: Optional[int] = None
    for col_idx in range(df.shape[1]):
        header_value = str(df.iat[header_row, col_idx]).strip().lower()
        if base_price_col is None and "цена базовая" in header_value:
            base_price_col = col_idx
        if purchase_price_col is None and "цена закуп" in header_value:
            purchase_price_col = col_idx
        if site_price_col is None and "цена фг" in header_value:
            site_price_col = col_idx
        if base_price_col is not None and purchase_price_col is not None and site_price_col is not None:
            break

    base_markup_formula_rows: list[int] = []
    purchase_markup_formula_rows: list[int] = []
    site_markup_formula_rows: list[int] = []

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

        parsed_price = item.get("price", "")

        base_markup_value: object = ""
        purchase_markup_value: object = ""
        site_markup_value: object = ""
        parsed_price_num = _to_number(parsed_price)

        if base_price_col is not None:
            base_price = _to_number(df.iat[r, base_price_col])
            parsed_price_num = _to_number(parsed_price)
            if base_price is not None and parsed_price_num is not None:
                base_markup_formula_rows.append(r)

        if purchase_price_col is not None:
            purchase_price = _to_number(df.iat[r, purchase_price_col])
            if purchase_price is not None and parsed_price_num is not None:
                purchase_markup_formula_rows.append(r)

        if site_price_col is not None:
            site_price = _to_number(df.iat[r, site_price_col])
            if site_price is not None and parsed_price_num is not None:
                site_markup_formula_rows.append(r)

        row_values = [
            parsed_price,
            base_markup_value,
            purchase_markup_value,
            site_markup_value,
        ]

        for offset, value in enumerate(row_values):
            df.iat[r, insert_col + offset] = value

        apteka_rows[r] = [
            item.get("title", ""),
            item.get("price", ""),
            item.get("message", ""),
        ]

    wb = Workbook()
    ws = wb.active

    source_side = Side(style="thin", color="000000")
    parsed_side = Side(style="thin", color="000000")

    ROW_OFFSET = 1

    header_alignment = Alignment(vertical="top", wrap_text=True)
    content_alignment = Alignment(horizontal="left", vertical="top", wrap_text=True)

    for row_idx in range(df.shape[0]):
        for col_idx in range(df.shape[1]):
            value = df.iat[row_idx, col_idx]
            cell = ws.cell(row=row_idx + 1 + ROW_OFFSET, column=col_idx + 1)
            cell.value = "" if pd.isna(value) else value
            if row_idx == header_row:
                cell.alignment = header_alignment
            else:
                cell.alignment = content_alignment

    parsed_price_letter = get_column_letter(insert_col + 1)

    if base_price_col is not None:
        base_price_letter = get_column_letter(base_price_col + 1)
        base_markup_col = insert_col + 2
        for row_idx in base_markup_formula_rows:
            excel_row = row_idx + 1 + ROW_OFFSET
            base_markup_cell = ws.cell(row=excel_row, column=base_markup_col)
            base_markup_cell.value = (
                f"=IF(OR({parsed_price_letter}{excel_row}=0,{base_price_letter}{excel_row}=0),"
                f"0,{parsed_price_letter}{excel_row}/({base_price_letter}{excel_row}-1)-1)"
            )
            base_markup_cell.number_format = '0.00%'

    if purchase_price_col is not None:
        purchase_price_letter = get_column_letter(purchase_price_col + 1)
        purchase_markup_col = insert_col + 3
        for row_idx in purchase_markup_formula_rows:
            excel_row = row_idx + 1 + ROW_OFFSET
            purchase_markup_cell = ws.cell(row=excel_row, column=purchase_markup_col)
            purchase_markup_cell.value = (
                f"=IF(OR({parsed_price_letter}{excel_row}=0,{purchase_price_letter}{excel_row}=0),"
                f"0,{parsed_price_letter}{excel_row}/({purchase_price_letter}{excel_row}-1)-1)"
            )
            purchase_markup_cell.number_format = '0.00%'

    if site_price_col is not None:
        site_price_letter = get_column_letter(site_price_col + 1)
        site_markup_col = insert_col + 4
        for row_idx in site_markup_formula_rows:
            excel_row = row_idx + 1 + ROW_OFFSET
            site_markup_cell = ws.cell(row=excel_row, column=site_markup_col)
            site_markup_cell.value = (
                f"=IF(OR({parsed_price_letter}{excel_row}=0,{site_price_letter}{excel_row}=0),"
                f"0,{parsed_price_letter}{excel_row}/({site_price_letter}{excel_row}-1)-1)"
            )
            site_markup_cell.number_format = '0.00%'

    source_min_col = 1
    source_max_col = insert_col
    parsed_min_col = insert_col + 1
    parsed_max_col = insert_col + len(main_extra_headers)

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

    def _apply_outer_border(min_row: int, max_row: int, min_col: int, max_col: int, side: Side) -> None:
        if min_row > max_row or min_col > max_col:
            return

        for r in range(min_row, max_row + 1):
            for c in range(min_col, max_col + 1):
                is_top = r == min_row
                is_bottom = r == max_row
                is_left = c == min_col
                is_right = c == max_col

                if not (is_top or is_bottom or is_left or is_right):
                    continue

                cell = ws.cell(row=r + 1 + ROW_OFFSET, column=c + 1)
                border = cell.border
                cell.border = Border(
                    left=side if is_left else border.left,
                    right=side if is_right else border.right,
                    top=side if is_top else border.top,
                    bottom=side if is_bottom else border.bottom,
                )

    last_row = df.shape[0] - 1
    if last_row >= header_row:
        subheader_min_row = header_row
        subheader_max_row = (list_start_row - 1) if list_start_row is not None else header_row
        if subheader_min_row <= subheader_max_row:
            _apply_outer_border(
                min_row=subheader_min_row,
                max_row=subheader_max_row,
                min_col=0,
                max_col=df.shape[1] - 1,
                side=source_side,
            )

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
            max_col=insert_col + len(main_extra_headers) - 1,
            side=parsed_side,
        )

    ws.title = "Итог"

    apteka_sheet = wb.create_sheet("Apteka Ru")
    apteka_sheet.merge_cells(start_row=1, start_column=1, end_row=1, end_column=len(apteka_extra_headers))

    apteka_header_cell = apteka_sheet.cell(row=1, column=1)
    apteka_header_cell.value = "Apteka Ru"
    apteka_header_cell.alignment = Alignment(horizontal="center", vertical="center")
    apteka_header_cell.font = Font(size=22, bold=True)
    apteka_header_cell.fill = PatternFill(fill_type="solid", fgColor="D0E0E3")

    for col_idx, header in enumerate(apteka_extra_headers, start=1):
        cell = apteka_sheet.cell(row=2, column=col_idx)
        cell.value = header
        cell.alignment = header_alignment
        cell.border = Border(left=parsed_side, right=parsed_side, top=parsed_side, bottom=parsed_side)

    apteka_row = 3
    for r in range(header_row + 1, df.shape[0]):
        values = apteka_rows.get(r, ["", "", ""])
        for col_idx, value in enumerate(values, start=1):
            cell = apteka_sheet.cell(row=apteka_row, column=col_idx)
            cell.value = value
            cell.alignment = content_alignment
            cell.border = Border(left=parsed_side, right=parsed_side, top=parsed_side, bottom=parsed_side)
        apteka_row += 1

    for offset in range(len(apteka_extra_headers)):
        target_letter = get_column_letter(offset + 1)
        apteka_sheet.column_dimensions[target_letter].width = 40 if offset == 0 else 18

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
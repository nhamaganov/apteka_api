import pandas as pd
import re

from collections import defaultdict
from rapidfuzz import fuzz


UNITS_PATTERN = r"(мг|г|мкг|мл|ме|%|iu)"

MODIFIERS = {"микро", "плюс", "мини", "форте", "экстра", "лонг", "ретард", "квик", "дуо"}


def modifiers(tokens: set[str]) -> set[str]:
    """Возвращает модификаторы, присутствующие в наборе токенов."""
    return tokens & MODIFIERS


def cut_before_bracket(name: str) -> str:
    """Возвращает часть строки до первой открывающей скобки."""
    return name.split("(", 1)[0].strip()

def load_products_from_xls(path: str) -> list[str]:
    """Загружает названия товаров из Excel-файла."""
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

    products = (
        df.iloc[header_row + 1 :, header_col]
        .dropna()
        .astype(str)
        # .map(cut_before_bracket)
        .drop_duplicates()
        .tolist()
    )

    return products

def build_title_quantity_dict(items: list[str]):
    """Строит словарь соответствий названий и извлечённых количеств."""
    result = defaultdict(list)

    for text in items:
        # Название
        title = text.split("(", 1)[0].strip()

        # Ищем количество
        match = re.search(r'N\s*([\d+]+)', text, flags=re.IGNORECASE)

        if match:
            parts = match.group(1).split("+")
            quantity = sum(int(p) for p in parts)
        else:
            quantity = None

        result[title].append(quantity)

    return dict(result)


def extract_quantity(text: str) -> int | None:
    """
    Извлекает количество в штуках из строки.
    Возвращает число или None, если не найдено.
    """
    match = re.search(r'(\d+)\s*шт\.?', text, re.IGNORECASE)
    return int(match.group(1)) if match else None



def normalize(s: str) -> str:
    """Нормализует строку для нестрогого сравнения."""
    if not s:
        return ""
    s = s.strip().lower().replace("ё", "е")
    s = re.sub(r"[\"'`]", "", s)
    s = re.sub(r"\bспираль\b", " ", s)
    s = re.sub(r"\bв\s*/\s*м\b", " ", s) 
    s = re.sub(r"[•·/,_:;]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def extract_base_name(raw: str) -> str:
    """
    Берём только 'название' без скобок/дозировок/упаковок.
    Для XLS почти всегда достаточно части ДО '(' или ','.
    """
    s = normalize(raw)
    s = re.split(r"[\(\,]", s, maxsplit=1)[0].strip()

    # прибираем числа/дозировки/единицы/упаковку
    s = re.sub(rf"\b\d+(\.\d+)?\s*{UNITS_PATTERN}\b", " ", s)
    s = re.sub(r"\bn\s*\d+\b", " ", s)  # n28
    s = re.sub(r"\b\d+(\.\d+)?\b", " ", s)
    s = re.sub(r"[+×x]", " ", s)

    s = re.sub(r"\s+", " ", s).strip()
    return s


def is_name_match(xls_name: str, site_title: str,
                  min_token_set: int = 93,
                  min_partial: int = 95) -> bool:
    """
    Нестрогое сравнение RapidFuzz, но без склейки разных препаратов:
    - используем token_set_ratio + partial_ratio
    - блокируем совпадения, если на сайте есть модификатор (микро/плюс/форте...), а в запросе его нет
    """
    a = extract_base_name(xls_name)
    b = extract_base_name(site_title)

    if not a or not b:
        return False

    a_tokens = set(a.split())
    b_tokens = set(b.split())

    # защита от "анжелик" vs "анжелик микро"
    a_mod = modifiers(a_tokens)
    b_mod = modifiers(b_tokens)
    if b_mod and not b_mod.issubset(a_mod):
        return False

    score1 = fuzz.token_set_ratio(a, b)   # 0..100
    if score1 >= min_token_set:
        return True

    score2 = fuzz.partial_ratio(a, b)
    return score2 >= min_partial

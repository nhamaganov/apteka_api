import re

from collections import defaultdict
from rapidfuzz import fuzz
from app.utils.xls import read_spreadsheet


UNITS_PATTERN = r"(мг|г|гр|мкг|мл|ме|мe|me|ед|ле|le|%|iu)"

MODIFIERS = {"микро", "плюс", "мини", "форте", "экстра", "лонг", "ретард", "квик", "дуо"}

MANUFACTURER_NOISE_WORDS = {
    "ооо", "оао", "зао", "пао", "ао", "ип", "inc", "llc", "ltd", "gmbh", "ag",
    "co", "corp", "company", "sa", "srl", "plc", "фарма", "pharma", "фарм",
}

COUNTRY_WORDS = {
    "россия", "венгрия", "франция", "германия", "италия", "испания", "швейцария", "сша",
    "китай", "япония", "индия", "польша", "чехия", "сербия", "австрия", "бельгия", "ирландия",
    "великобритания", "пуэрто", "рико", "germany", "france", "russia", "hungary", "italy",
    "spain", "switzerland", "usa", "china", "japan", "india", "poland", "czech", "serbia",
    "austria", "belgium", "ireland", "uk",
}

_CYR_TO_LAT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh",
    "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o",
    "п": "p", "р": "r", "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts",
    "ч": "ch", "ш": "sh", "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu",
    "я": "ya",
})


def modifiers(tokens: set[str]) -> set[str]:
    """Возвращает модификаторы, присутствующие в наборе токенов."""
    return tokens & MODIFIERS


def cut_before_bracket(name: str) -> str:
    """Возвращает часть строки до первой открывающей скобки."""
    return name.split("(", 1)[0].strip()


def extract_query_manufacturer(raw: str) -> str:
    """Берёт производителя из запроса как хвост после последней ')' ."""
    if not raw:
        return ""
    idx = raw.rfind(")")
    if idx == -1:
        return ""
    return raw[idx + 1:].strip()


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
    s = re.sub(rf"\b\d+(\.\d+)?\s*{UNITS_PATTERN}(?!\w)", " ", s)
    s = re.sub(r"\bn\s*\d+\b", " ", s)  # n28
    s = re.sub(r"\b\d+(\.\d+)?\b", " ", s)
    s = re.sub(r"[+×x]", " ", s)

    s = re.sub(r"\s+", " ", s).strip()
    return s


def extract_lindinet_variant(raw: str) -> str | None:

    s = normalize(raw)
    if "линдинет" not in s:
        return None
    match = re.search(r"\b(20|30)\b", s)
    return match.group(1) if match else None


def _contains_cyrillic(s: str) -> bool:
    return bool(re.search(r"[а-яА-ЯёЁ]", s))


def _contains_latin(s: str) -> bool:
    return bool(re.search(r"[a-zA-Z]", s))


def _remove_manufacturer_noise_tokens(s: str) -> str:
    tokens = [t for t in s.split() if t not in MANUFACTURER_NOISE_WORDS and t not in COUNTRY_WORDS]
    return " ".join(tokens)


def normalize_manufacturer_name(s: str) -> str:
    """Нормализует производителя: чистка, удаление стран/орг-форм и лишних символов."""
    s = normalize(s)
    if not s:
        return ""
    s = s.replace("-", " ")
    s = re.sub(r"[()\[\]{}]", " ", s)
    s = re.sub(r"\b(и|and|&|ко|co)\.?\b", " ", s)
    s = _remove_manufacturer_noise_tokens(s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _transliterate_cyr_to_latin(s: str) -> str:
    return s.translate(_CYR_TO_LAT)


def manufacturer_match_details(
    query_raw: str,
    site_brand: str,
    query_manufacturer: str = "",
    min_score: int = 50,
) -> dict:
    """Возвращает детальный результат сравнения производителей."""
    source = query_manufacturer or extract_query_manufacturer(query_raw)
    expected = normalize_manufacturer_name(source)
    actual = normalize_manufacturer_name(site_brand)

    if not expected:
        return {
            "matched": True,
            "score": 100,
            "threshold": min_score,
            "mixed_alphabet": False,
            "query_source": source,
            "query_normalized": expected,
            "site_raw": site_brand or "",
            "site_normalized": actual,
            "query_compared": expected,
            "site_compared": actual,
            "reason": "query_manufacturer_empty",
        }

    if not actual:
        return {
            "matched": False,
            "score": 0,
            "threshold": min_score,
            "mixed_alphabet": False,
            "query_source": source,
            "query_normalized": expected,
            "site_raw": site_brand or "",
            "site_normalized": actual,
            "query_compared": expected,
            "site_compared": actual,
            "reason": "site_manufacturer_empty",
        }

    expected_has_cyr = _contains_cyrillic(expected)
    expected_has_lat = _contains_latin(expected)
    actual_has_cyr = _contains_cyrillic(actual)
    actual_has_lat = _contains_latin(actual)

    mixed_alphabet = (expected_has_cyr and actual_has_lat) or (expected_has_lat and actual_has_cyr)
    if mixed_alphabet:
        expected_cmp = _transliterate_cyr_to_latin(expected)
        actual_cmp = _transliterate_cyr_to_latin(actual)
    else:
        expected_cmp = expected
        actual_cmp = actual

    score = int(round(fuzz.token_set_ratio(expected_cmp, actual_cmp)))
    return {
        "matched": score >= min_score,
        "score": score,
        "threshold": min_score,
        "mixed_alphabet": mixed_alphabet,
        "query_source": source,
        "query_normalized": expected,
        "site_raw": site_brand or "",
        "site_normalized": actual,
        "query_compared": expected_cmp,
        "site_compared": actual_cmp,
        "reason": "ok",
    }


def is_manufacturer_match(query_raw: str, site_brand: str, min_score: int = 90) -> bool:
    details = manufacturer_match_details(query_raw=query_raw, site_brand=site_brand, min_score=min_score)
    return bool(details["matched"])


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

    lindinet_xls = extract_lindinet_variant(xls_name)
    lindinet_site = extract_lindinet_variant(site_title)
    if lindinet_xls is not None or lindinet_site is not None:
        return lindinet_xls is not None and lindinet_xls == lindinet_site

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

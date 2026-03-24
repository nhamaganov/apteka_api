import re

from rapidfuzz import fuzz

from app.utils.name_patterns import apply_name_patterns


UNITS_PATTERN = r"(мг|г|гр|мкг|мл|ме|мe|me|ед|ле|le|%|iu)"

MODIFIERS = {"микро", "плюс", "мини", "форте", "экстра", "лонг", "ретард", "квик", "дуо"}

MANUFACTURER_NOISE_WORDS = {
    "ооо", "оао", "зао", "пао", "ао", "ип", "inc", "llc", "ltd", "gmbh", "ag",
    "co", "corp", "company", "sa", "srl", "plc", "kg", "kgaa", "фарма", "pharma", "фарм",
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
    s = re.sub(r"\bв\s*/\s*м\b", " ", s) 
    s = re.sub(r"[•·/,_:;]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _log_name_normalization(job_id: str | None, message: str) -> None:
    if not job_id:
        return
    from app.services.job_runner import normalization_log

    normalization_log(job_id, message)


def normalize_product_name(raw: str, job_id: str | None = None, source: str = "") -> str:
    """Нормализует товарное название для сравнения без удаления значимых частей."""
    original = raw or ""
    s = apply_name_patterns(raw)
    s = normalize(s)
    s = re.sub(r"[()\[\]{}]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    if source:
        _log_name_normalization(job_id, f"NORMALIZE {source}: raw={original!r} -> normalized={s!r}")
    return s


def extract_base_name(raw: str) -> str:
    """Совместимость со старым API: возвращает полное унифицированное название."""
    return normalize_product_name(raw)


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


def _transliterate_latin_to_cyr(s: str) -> str:
    # Порядок замен важен: сначала длинные сочетания.
    pairs = [
        ("sch", "щ"),
        ("sh", "ш"),
        ("ch", "ч"),
        ("zh", "ж"),
        ("kh", "х"),
        ("ts", "ц"),
        ("yu", "ю"),
        ("ya", "я"),
        ("yo", "ё"),
        ("ye", "е"),
        ("ei", "ай"),
        ("ey", "ей"),
        ("qu", "кв"),
        ("ph", "ф"),
        ("w", "в"),
        ("x", "кс"),
        ("a", "а"),
        ("b", "б"),
        ("c", "к"),
        ("d", "д"),
        ("e", "е"),
        ("f", "ф"),
        ("g", "г"),
        ("h", "х"),
        ("i", "и"),
        ("j", "й"),
        ("k", "к"),
        ("l", "л"),
        ("m", "м"),
        ("n", "н"),
        ("o", "о"),
        ("p", "п"),
        ("q", "к"),
        ("r", "р"),
        ("s", "с"),
        ("t", "т"),
        ("u", "у"),
        ("v", "в"),
        ("y", "й"),
        ("z", "з"),
    ]
    out = s
    for frm, to in pairs:
        out = out.replace(frm, to)
    return out


def _latin_pronounce_normalize(s: str) -> str:
    out = s
    out = re.sub(r"\bqu", "kv", out)
    out = out.replace("ph", "f")
    out = out.replace("w", "v")
    out = out.replace("x", "ks")
    out = re.sub(r"ei", "ay", out)
    out = re.sub(r"y", "i", out)
    out = re.sub(r"\s+", " ", out).strip()
    return out


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

    expected_cmp = expected
    actual_cmp = actual
    best_score = int(round(fuzz.token_set_ratio(expected_cmp, actual_cmp)))

    def maybe_update_best(lhs: str, rhs: str) -> None:
        nonlocal best_score, expected_cmp, actual_cmp
        if not lhs or not rhs:
            return
        candidate = int(round(fuzz.token_set_ratio(lhs, rhs)))
        if candidate > best_score:
            best_score = candidate
            expected_cmp = lhs
            actual_cmp = rhs

    if mixed_alphabet:
        # 1) Базовая текущая стратегия: перевод обеих строк в латиницу.
        maybe_update_best(_transliterate_cyr_to_latin(expected), _transliterate_cyr_to_latin(actual))
        # 2) Альтернативная стратегия: перевод обеих строк в кириллицу.
        maybe_update_best(_transliterate_latin_to_cyr(expected), _transliterate_latin_to_cyr(actual))
        # 3) Фонетическая нормализация латиницы для сложных кейсов (Queisser vs Квайссер).
        maybe_update_best(
            _latin_pronounce_normalize(_transliterate_cyr_to_latin(expected)),
            _latin_pronounce_normalize(_transliterate_cyr_to_latin(actual)),
        )

    score = best_score
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


def name_match_details(
    xls_name: str,
    site_title: str,
    min_token_set: int = 70,
    min_partial: int = 70,
    job_id: str | None = None,
) -> dict:
    """
    Возвращает детальный результат сравнения названий.
    """
    a = normalize_product_name(xls_name, job_id=job_id, source="xls_name")
    b = normalize_product_name(site_title, job_id=job_id, source="site_title")

    if not a or not b:
        return {
            "matched": False,
            "score": 0,
            "token_set_score": 0,
            "partial_score": 0,
            "reason": "empty_name",
            "query_normalized": a,
            "site_normalized": b,
        }

    lindinet_xls = extract_lindinet_variant(xls_name)
    lindinet_site = extract_lindinet_variant(site_title)
    if lindinet_xls is not None or lindinet_site is not None:
        matched = lindinet_xls is not None and lindinet_xls == lindinet_site
        return {
            "matched": matched,
            "score": 100 if matched else 0,
            "token_set_score": 100 if matched else 0,
            "partial_score": 100 if matched else 0,
            "reason": "lindinet_variant_match" if matched else "lindinet_variant_mismatch",
            "query_normalized": a,
            "site_normalized": b,
        }

    a_tokens = set(a.split())
    b_tokens = set(b.split())

    a_mod = modifiers(a_tokens)
    b_mod = modifiers(b_tokens)
    if b_mod and not b_mod.issubset(a_mod):
        token_set_score = int(round(fuzz.token_set_ratio(a, b)))
        partial_score = int(round(fuzz.partial_ratio(a, b)))
        return {
            "matched": False,
            "score": max(token_set_score, partial_score),
            "token_set_score": token_set_score,
            "partial_score": partial_score,
            "reason": "modifier_mismatch",
            "query_normalized": a,
            "site_normalized": b,
        }

    token_set_score = int(round(fuzz.token_set_ratio(a, b)))
    partial_score = int(round(fuzz.partial_ratio(a, b)))
    matched = token_set_score >= min_token_set or partial_score >= min_partial
    _log_name_normalization(
            job_id,
            "MATCH "
            f"xls_raw={xls_name!r} | site_raw={site_title!r} | "
            f"xls_normalized={a!r} | site_normalized={b!r} | "
            f"token_set={token_set_score} | partial={partial_score} | matched={matched}",
        )
    return {
        "matched": matched,
        "score": max(token_set_score, partial_score),
        "token_set_score": token_set_score,
        "partial_score": partial_score,
        "reason": "ok" if matched else "below_threshold",
        "query_normalized": a,
        "site_normalized": b,
    }


def is_name_match(xls_name: str, site_title: str,
                  min_token_set: int = 70,
                  min_partial: int = 70,
                  job_id: str | None = None) -> bool:
    """
    Нестрогое сравнение RapidFuzz, но без склейки разных препаратов:
    - используем token_set_ratio + partial_ratio
    - блокируем совпадения, если на сайте есть модификатор (микро/плюс/форте...), а в запросе его нет
    """
    details = name_match_details(
        xls_name,
        site_title,
        min_token_set=min_token_set,
        min_partial=min_partial,
        job_id=job_id,
    )
    return details["matched"]

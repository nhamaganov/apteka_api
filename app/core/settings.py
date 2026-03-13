import os

def get_int(name: str, default: int) -> int:
    """Возвращает целочисленное значение переменной окружения или default."""
    try:
        return int((os.environ.get(name, "") or "").strip() or default)
    
    except Exception: 
        return default
    

def get_float(name: str, default: float) -> float:
    """Возвращает число с плавающей точкой из переменной окружения или default."""
    try:
        return float(os.environ.get(name, "").strip() or default) 
    except Exception:
        return default
    

PARSE_TIMEOUT = get_int("PARSE_TIMEOUT", 10)
PARSE_MAX_RETRIES = get_int("PARSE_MAX_RETRIES", 10)
PARSE_PAUSE = get_float("PARSE_PAUSE", 3)

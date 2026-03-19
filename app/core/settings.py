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


def get_str(name: str, default: str = "") -> str:
    """Возвращает строковое значение переменной окружения или default."""
    return (os.environ.get(name, default) or default).strip()


PHARMECONOM_TOKEN = "50q6kIj!i9Ch^$P2cokgP1#egG1DaS5tUrc8sIrsq7MvS3$zkH7rBwBwvmuF*pUi"
PHARMECONOM_COOKIE = "COOKIE=__ddg10_=1773885566; __ddg1_=8uyO0z9ndkkUfbPLzwhl; __ddg8_=0Indtn4VggHH9Jl5; __ddg9_=91.185.32.42; PHPSESSID=282fgJsFUl3rVE70MEeMIqBsxdS03jDH"
PHARMECONOM_TIMEOUT = get_float("PHARMECONOM_TIMEOUT", 20.0)

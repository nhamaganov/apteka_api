import os

def get_int(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, "".strip() or default))
    
    except Exception: 
        return default
    

def get_float(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, "").strip() or default) 
    except Exception:
        return default
    

PARSE_TIMEOUT = get_int("PARSE_TIMEOUT", 10)
PARSE_MAX_RETRIES = get_int("PARSE_MAX_RETRIES", 7)
PARSE_PAUSE = get_float("PARSE_PAUSE", 3)
PARSE_VARIANT_SETTLE_DELAY = get_float("PARSE_VARIANT_SETTLE_DELAY", 4.0)

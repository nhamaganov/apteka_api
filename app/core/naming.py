from pathlib import Path
import re

def make_display_name(filename: str) -> str:
    """Возвращает очищенное отображаемое имя на основе имени файла."""
    base = Path(filename).name  # Извлекает имя файлов без директорий
    stem = Path(base).stem  # Убирает распишения .pdf .txt и тд.
    stem = re.sub(r"\s+", " ", stem).strip()  # Заменяет все пробелы на одиночные, убирает пробелы по краям
    return stem or base

"""
datatypes.py
Определения типов данных для многотипового сканера памяти.

Главная идея: пользователь вводит одно число (например 100), а сканер
одновременно ищет его как int8/16/32/64, uint*, float32/64 — в обоих
порядках байт (little-endian и big-endian). Это решает главную боль
Cheat Engine, где要先 выбрать тип данных, иначе "по умолчанию ничего не находит".
"""

import struct
from dataclasses import dataclass


@dataclass(frozen=True)
class DataType:
    name: str          # человекочитаемое имя, напр. "int32"
    fmt: str           # struct-формат с endian, напр. "<i"
    size: int          # размер в байтах
    is_float: bool     # True для float32/float64 (нужна толерантность при сравнении)

    def pack(self, value) -> bytes | None:
        """Упаковать значение в байты. None, если значение не влезает в тип."""
        try:
            return struct.pack(self.fmt, value)
        except (struct.error, OverflowError):
            return None

    def unpack(self, raw: bytes):
        """Распаковать байты в значение. None при ошибке длины."""
        if len(raw) != self.size:
            return None
        try:
            return struct.unpack(self.fmt, raw)[0]
        except struct.error:
            return None


# Полный набор типов. Для каждого целого — обе endian-варианта (LE и BE),
# потому что в редких играх/движках значения хранятся big-endian.
# signed/unsigned с одинаковым положительным значением дают одинаковые байты,
# но оба включены, чтобы декодирование в UI было корректным для диапазона.
TYPES: list[DataType] = [
    DataType("int8",       "<b", 1, False),
    DataType("uint8",      "<B", 1, False),
    DataType("int16",      "<h", 2, False),
    DataType("int16_be",   ">h", 2, False),
    DataType("uint16",     "<H", 2, False),
    DataType("uint16_be",  ">H", 2, False),
    DataType("int32",      "<i", 4, False),
    DataType("int32_be",   ">i", 4, False),
    DataType("uint32",     "<I", 4, False),
    DataType("uint32_be",  ">I", 4, False),
    DataType("int64",      "<q", 8, False),
    DataType("int64_be",   ">q", 8, False),
    DataType("uint64",     "<Q", 8, False),
    DataType("uint64_be",  ">Q", 8, False),
    DataType("float32",    "<f", 4, True),
    DataType("float32_be", ">f", 4, True),
    DataType("float64",    "<d", 8, True),
    DataType("float64_be", ">d", 8, True),
]

# Быстрый lookup по имени.
BY_NAME: dict[str, DataType] = {t.name: t for t in TYPES}

# Имена типов для UI по умолчанию (все включены).
DEFAULT_TYPE_NAMES: list[str] = [t.name for t in TYPES]

# Типы, которые разумно использовать для авто-поиска ресурсов (самые частые
# в реальных играх). Берём выровненные 4/8-байтные интерпретации.
AUTO_DETECT_TYPES: list[DataType] = [
    BY_NAME["int32"],
    BY_NAME["uint32"],
    BY_NAME["float32"],
    BY_NAME["int64"],
    BY_NAME["float64"],
]


def find_all(haystack: bytes, needle: bytes):
    """
    Генератор всех смещений needle в haystack.
    Использует bytes.find в цикле — быстрее регулярных выражений и
    byte-by-byte на CPython.
    """
    if not needle:
        return
    start = 0
    nlen = len(needle)
    while True:
        idx = haystack.find(needle, start)
        if idx == -1:
            return
        yield idx
        start = idx + 1  # +1, а не +nlen: ловим перекрытия (напр. AAAA в AAAAAA)


def values_equal(a, b, dtype: DataType, tolerance: float) -> bool:
    """Сравнение значений с учётом толерантности для float."""
    if dtype.is_float:
        if a is None or b is None:
            return False
        if tolerance > 0:
            return abs(a - b) <= tolerance
        # Без явной толерантности — точное совпадение бит (NaN-безопасно через unpack).
        return struct.pack(dtype.fmt, a) == struct.pack(dtype.fmt, b) \
            if _finite(a) and _finite(b) else (a == b)
    return a == b


def _finite(x) -> bool:
    try:
        import math
        return math.isfinite(x)
    except (TypeError, ValueError):
        return False

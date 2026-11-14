"""
scanner.py
Мульти-тип сканер памяти — сердце программы.

Главная фишка (то, чего нет в базовом Cheat Engine "из коробки"):
пользователь вводит ОДНО число, а first_scan() одновременно ищет его как
int8/16/32/64, uint*, float32/64 — в little- и big-endian. Совпадения
приходят со всеми типами сразу, поэтому "по умолчанию ничего не находит"
больше не случается из-за неправильно угаданного типа.

next_scan() фильтрует уже найденные адреса по новому значению или по
характеру изменения (точное / изменилось / не изменилось / выросло / упало /
+дельта / -дельта), перечитывая память только в найденных точках.
"""

from __future__ import annotations
import time
import logging
from dataclasses import dataclass, field
from typing import Callable

from datatypes import TYPES, BY_NAME, DataType, find_all, values_equal
from process import Region

_log = logging.getLogger("gamecheat")

# Режимы next_scan. "scan_value" — требуется новое значение.
MODE_EXACT = "exact"                # равно значению
MODE_INCREASED = "increased"        # стало больше
MODE_DECREASED = "decreased"        # стало меньше
MODE_CHANGED = "changed"            # изменилось (любое)
MODE_UNCHANGED = "unchanged"        # не изменилось
MODE_INCREASED_BY = "increased_by"  # выросло ровно на delta
MODE_DECREASED_BY = "decreased_by"  # упало ровно на delta

MODES_NEED_VALUE = {MODE_EXACT, MODE_INCREASED_BY, MODE_DECREASED_BY}

# Читать регионы кусками не более 16 МБ, чтобы не плодить огромные buffers.
CHUNK = 16 * 1024 * 1024


@dataclass
class Match:
    address: int
    type_name: str
    value: float | int   # последнее известное значение (для отображения/сравнения)

    def __lt__(self, other):
        return (self.address, self.type_name) < (other.address, other.type_name)


@dataclass
class ScanProgress:
    regions_done: int = 0
    regions_total: int = 0
    bytes_done: int = 0
    bytes_total: int = 0
    matches: int = 0
    elapsed: float = 0.0


class Scanner:
    """Мульти-тип сканер по одному процессу."""

    def __init__(self, process, enabled_type_names: list[str] | None = None):
        self.proc = process
        names = enabled_type_names or [t.name for t in TYPES]
        # Сохраняем только валидные имена типов, в порядке TYPES.
        valid = {t.name for t in TYPES}
        self.enabled = [BY_NAME[n] for n in names if n in valid]
        if not self.enabled:
            self.enabled = list(TYPES)
        self.matches: list[Match] = []
        self._has_scan = False

    # ------------------------------------------------------------------
    # Утилиты
    # ------------------------------------------------------------------

    def _collect_regions(self) -> list[Region]:
        return [r for r in self.proc.iter_regions(data_only=True) if r.is_data]

    def _patterns_for_value(self, value) -> list[tuple[DataType, bytes]]:
        """Для значения вернуть [(dtype, bytes), ...] по всем включённым типам,
        где значение влезает в тип. Дубликаты байтов (напр. int32 LE == uint32 LE
        для положительных) оставляем — тип нужен для корректной интерпретации."""
        out = []
        for dt in self.enabled:
            raw = dt.pack(value)
            if raw is not None:
                out.append((dt, raw))
        return out

    # ------------------------------------------------------------------
    # Первый скан
    # ------------------------------------------------------------------

    def first_scan(self, value, progress_cb: Callable[[ScanProgress], None] | None = None,
                   float_tol: float = 0.0) -> int:
        """
        Найти value во всех читаемых data-регионах по всем включённым типам.

        Для float-типов с float_tol>0: ищем не точное совпадение битов, а
        ближайшее значение в пределах tol. Простейшая реализация — перебор
        int-представлений вокруг; для первого скана обычно хватает точного
        поиска, толерантность важнее на next_scan. Здесь float_tol используется
        только чтобы пропустить float-типы при tol==0? Нет — float всегда
        ищется точно по битам; tol применяется в next_scan.

        Возвращает количество найденных совпадений.
        """
        self.matches.clear()
        self._has_scan = True
        t0 = time.time()
        regions = self._collect_regions()
        total_bytes = sum(min(r.size, 1 << 30) for r in regions)  # ограничим прогресс
        prog = ScanProgress(regions_total=len(regions), bytes_total=total_bytes)
        patterns = self._patterns_for_value(value)
        _log.info("first_scan: значение=%r, включённых типов=%d, паттернов=%d (%s), регионов=%d, байт=%.1f МБ",
                  value, len(self.enabled), len(patterns),
                  ", ".join(dt.name for dt, _ in patterns), len(regions),
                  total_bytes / (1024 * 1024))
        if not patterns:
            if progress_cb:
                prog.elapsed = time.time() - t0
                progress_cb(prog)
            return 0

        for r in regions:
            region_base = r.base
            rsize = r.size
            off = 0
            while off < rsize:
                sz = min(CHUNK, rsize - off)
                data = self.proc.read(region_base + off, sz)
                if data:
                    for dt, raw in patterns:
                        plen = len(raw)
                        if plen > len(data):
                            continue
                        for idx in find_all(data, raw):
                            addr = region_base + off + idx
                            self.matches.append(Match(addr, dt.name, value))
                off += sz
                prog.bytes_done += sz
            prog.regions_done += 1
            prog.matches = len(self.matches)
            prog.elapsed = time.time() - t0
            if progress_cb:
                progress_cb(prog)
        prog.matches = len(self.matches)
        prog.elapsed = time.time() - t0
        if progress_cb:
            progress_cb(prog)
        _log.info("first_scan: ИТОГО совпадений=%d (%.2f с). Примеры: %s",
                  len(self.matches), prog.elapsed,
                  [(hex(m.address), m.type_name) for m in self.matches[:5]])
        return len(self.matches)

    # ------------------------------------------------------------------
    # Следующий скан (фильтрация)
    # ------------------------------------------------------------------

    def next_scan(self, mode: str, value=None, delta=None,
                  float_tol: float = 0.0,
                  progress_cb: Callable[[ScanProgress], None] | None = None) -> int:
        """
        Отфильтровать текущие совпадения по новому состоянию памяти.

        mode: один из MODE_*.
        value: новое значение (для MODE_EXACT).
        delta: величина изменения (для MODE_INCREASED_BY / DECREASED_BY).
        float_tol: допуска для float-сравнения (для MODE_EXACT).

        Возвращает новое число совпадений.
        """
        if not self._has_scan:
            raise RuntimeError("Сначала выполните первый скан.")
        t0 = time.time()
        _log.info("next_scan: режим=%s, значение=%r, delta=%r, tol=%s, входных совпадений=%d",
                  mode, value, delta, float_tol, len(self.matches))
        prog = ScanProgress(regions_total=1, bytes_total=len(self.matches))
        kept: list[Match] = []
        read_none = 0          # адресов, которые не удалось перечитать
        dropped_val = 0        # адресов, прочитанных, но не подошедших по условию
        dropped_samples: list = []   # несколько примеров отброшенных (для диагностики)
        for i, m in enumerate(self.matches):
            dt = BY_NAME[m.type_name]
            raw = self.proc.read(m.address, dt.size)
            cur = dt.unpack(raw) if raw else None
            keep = False
            if cur is None:
                # Память стала нечитаемой/освобождена — отбрасываем.
                keep = False
                read_none += 1
            elif mode == MODE_EXACT:
                keep = values_equal(cur, value, dt, float_tol)
            elif mode == MODE_CHANGED:
                keep = not values_equal(cur, m.value, dt, float_tol)
            elif mode == MODE_UNCHANGED:
                keep = values_equal(cur, m.value, dt, float_tol)
            elif mode == MODE_INCREASED:
                keep = _safe_gt(cur, m.value)
            elif mode == MODE_DECREASED:
                keep = _safe_lt(cur, m.value)
            elif mode == MODE_INCREASED_BY:
                keep = _safe_eq_delta(cur, m.value, delta, sign=+1, tol=float_tol)
            elif mode == MODE_DECREASED_BY:
                keep = _safe_eq_delta(cur, m.value, delta, sign=-1, tol=float_tol)
            else:
                raise ValueError(f"Неизвестный режим скана: {mode}")
            if keep:
                kept.append(Match(m.address, m.type_name, cur))
            elif cur is not None:
                dropped_val += 1
                if len(dropped_samples) < 5:
                    dropped_samples.append((hex(m.address), m.type_name,
                                            "было", m.value, "стало", cur))
            if progress_cb and (i % 2000 == 0):
                prog.regions_done = 0
                prog.bytes_done = i
                prog.matches = len(kept)
                prog.elapsed = time.time() - t0
                progress_cb(prog)
        self.matches = kept
        prog.matches = len(self.matches)
        prog.bytes_done = len(self.matches)
        prog.elapsed = time.time() - t0
        if progress_cb:
            progress_cb(prog)
        _log.info("next_scan: ИТОГО оставлено=%d из %d. Не перечитано(read=None)=%d, "
                  "отброшено по условию=%d. Примеры отброшенных: %s",
                  len(self.matches), len(self.matches) + read_none + dropped_val,
                  read_none, dropped_val, dropped_samples)
        return len(self.matches)

    # ------------------------------------------------------------------
    # Запись значения в адрес (для "заморозки" и редактирования)
    # ------------------------------------------------------------------

    def write_value(self, address: int, type_name: str, value) -> bool:
        dt = BY_NAME.get(type_name)
        if dt is None:
            return False
        raw = dt.pack(value)
        if raw is None:
            return False
        return self.proc.write(address, raw)

    def read_value(self, address: int, type_name: str):
        dt = BY_NAME.get(type_name)
        if dt is None:
            return None
        raw = self.proc.read(address, dt.size)
        if not raw:
            return None
        return dt.unpack(raw)

    def clear(self):
        self.matches.clear()
        self._has_scan = False

    @property
    def count(self) -> int:
        return len(self.matches)


def _safe_gt(a, b) -> bool:
    try:
        return a > b
    except TypeError:
        return False


def _safe_lt(a, b) -> bool:
    try:
        return a < b
    except TypeError:
        return False


def _safe_eq_delta(cur, old, delta, sign: int, tol: float) -> bool:
    """cur == old + sign*delta (с толерантностью для float)."""
    if cur is None or old is None or delta is None:
        return False
    target = old + sign * delta
    try:
        return abs(cur - target) <= max(tol, 1e-9 * max(abs(target), 1))
    except TypeError:
        return False

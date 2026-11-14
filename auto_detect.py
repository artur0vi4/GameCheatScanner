"""
auto_detect.py
Автоматическое обнаружение "стандартных ресурсов" в игре (здоровье, патроны,
золото, мана, уровень, опыт, выносливость) — та самая фишка, которой
просил пользователь: "программа сама находила стандартные ресурсы".

Подход — гибрид сигнатур + diff-у снимков памяти:

1. capture_baseline() — снимок всех data-регионов (приватная RW память,
   без исполняемого кода). Хранятся сырые байты на регион.

2. Пользователь совершает действие в игре и сообщает инструменту, что
   произошло: "получил урон" (health ↓), "выстрелил" (ammo ↓), "получил
   золото" (gold ↑), и т.п. Можно указать примерную величину изменения.

3. apply_action() делает новый снимок и для каждого 4/8-байтного слота
   сравнивает old vs new. Кандидаты — адреса, где значение изменилось в
   нужном направлении, на правдоподобную величину, и лежит в правдоподобном
   диапазоне для данного ресурса. Сравнение векторизовано через numpy —
   весь кучный регион диффится за доли секунды.

4. Каждое последующее действие сужает список кандидатов (фильтруются уже
   найденные адреса). После 2-3 шагов остаются единицы.

5. classify() оценивает каждого кандидата по набору сигнатур: диапазон
   значения, предпочтительный тип, диапазон изменения, соседний паттерн
   (напр. max_health часто лежит по смещению +4 от текущего health).
   Каждому присваивается наиболее вероятная метка ресурса и confidence.

Так пользователь находит ресурсы БЕЗ знания точного значения — только по
характеру изменений, как ArtMoney "unknown initial value" + "decreased",
но сразу с автоматической классификацией, что это скорее всего health.
"""

from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Callable

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:  # pragma: no cover
    _HAS_NUMPY = False

from process import Region


# ---------------------------------------------------------------------------
# Сигнатуры ресурсов
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class ResourceSignature:
    name: str
    label: str                       # человекочитаемое имя
    value_range: tuple[int, int]     # правдоподобный диапазон абсолютного значения
    delta_range: tuple[int, int]     # правдоподобная величина изменения за одно действие
    preferred_types: tuple[str, ...] # типы, в которых обычно хранится
    neighbor_offset: int = 0         # смещение "парного" значения (max), 0 = нет
    neighbor_relation: str = "ge"    # как сосед относится к текущему (ge/le/eq)


SIGNATURES: dict[str, ResourceSignature] = {
    "health": ResourceSignature(
        "health", "Здоровье", (1, 9999), (1, 500),
        ("int32", "float32", "uint32"),
        neighbor_offset=4, neighbor_relation="ge"),
    "mana": ResourceSignature(
        "mana", "Мана / энергия", (0, 9999), (1, 200),
        ("int32", "float32", "uint32"),
        neighbor_offset=4, neighbor_relation="ge"),
    "stamina": ResourceSignature(
        "stamina", "Выносливость", (0, 1000), (1, 100),
        ("int32", "float32", "uint32")),
    "ammo": ResourceSignature(
        "ammo", "Патроны", (0, 9999), (1, 200),
        ("int32", "uint32"),
        neighbor_offset=4, neighbor_relation="ge"),  # max_ammo рядом
    "gold": ResourceSignature(
        "gold", "Золото / деньги", (0, 2_000_000_000), (1, 10_000_000),
        ("int32", "uint32", "int64", "uint64")),
    "level": ResourceSignature(
        "level", "Уровень", (1, 1000), (1, 1),
        ("int32", "uint32")),
    "xp": ResourceSignature(
        "xp", "Опыт (XP)", (0, 2_000_000_000), (1, 1_000_000),
        ("int32", "uint32", "int64", "uint64")),
}

# Действия пользователя: (kind, direction, default_delta_hint).
# direction: "decreased" / "increased" / "changed".
ACTIONS = {
    "took_damage":    ("health",  "decreased", "health упало (получен урон)"),
    "healed":         ("health",  "increased", "health выросло (лечение)"),
    "fired":          ("ammo",    "decreased", "ammo упало (выстрел)"),
    "reloaded":       ("ammo",    "increased", "ammo выросло (перезарядка)"),
    "spent_gold":     ("gold",    "decreased", "золото упало (покупка)"),
    "earned_gold":    ("gold",    "increased", "золото выросло (доход)"),
    "spent_mana":     ("mana",    "decreased", "мана упала (заклинание)"),
    "regen_mana":     ("mana",    "increased", "мана выросла (реген)"),
    "spent_stamina":  ("stamina", "decreased", "выносливость упала"),
    "regen_stamina":  ("stamina", "increased", "выносливость восстановилась"),
    "gained_xp":      ("xp",      "increased", "опыт вырос"),
    "leveled_up":     ("level",   "increased", "уровень вырос"),
    "custom_inc":     (None,      "increased", "произвольное значение выросло"),
    "custom_dec":     (None,      "decreased", "произвольное значение упало"),
    "custom_chg":     (None,      "changed",   "произвольное значение изменилось"),
    "custom_unchanged": (None,    "unchanged", "значение НЕ изменилось (отсев тикающего шума)"),
}


# ---------------------------------------------------------------------------
# Кандидат
# ---------------------------------------------------------------------------

@dataclass
class Candidate:
    address: int
    type_name: str
    baseline: float | int      # значение на baseline
    current: float | int       # последнее значение
    delta: float               # величина изменения (положительная = в сторону действия)
    best_label: str = "?"      # наиболее вероятный ресурс
    confidence: int = 0        # 0..100
    scores: dict = field(default_factory=dict)  # label -> score


@dataclass
class AutoProgress:
    step: str = ""
    regions_done: int = 0
    regions_total: int = 0
    candidates: int = 0
    elapsed: float = 0.0


# ---------------------------------------------------------------------------
# Детектор
# ---------------------------------------------------------------------------

class AutoDetector:
    def __init__(self, process):
        self.proc = process
        self._baseline: dict[int, bytes] = {}     # base -> raw bytes
        self._regions: list[Region] = []
        self.candidates: list[Candidate] = []
        self._has_baseline = False
        self._action_count = 0
        self._last_kind: str | None = None

    # ------------------------------------------------------------------
    # Baseline
    # ------------------------------------------------------------------

    def capture_baseline(self, progress_cb: Callable[[AutoProgress], None] | None = None):
        """Снимок всех data-регионов. Дублирует первый шаг ArtMoney
        'unknown initial value', но только по data-памяти (без кода)."""
        self._baseline.clear()
        self._regions = [r for r in self.proc.iter_regions(data_only=True) if r.is_data]
        self.candidates.clear()
        self._has_baseline = True
        self._action_count = 0
        prog = AutoProgress(step="baseline", regions_total=len(self._regions))
        t0 = time.time()
        for i, r in enumerate(self._regions):
            # Читаем регион целиком (если очень большой — кусками по 16 МБ).
            data = bytearray()
            off = 0
            while off < r.size:
                sz = min(16 * 1024 * 1024, r.size - off)
                data += self.proc.read(r.base + off, sz)
                off += sz
            self._baseline[r.base] = bytes(data)
            prog.regions_done = i + 1
            prog.elapsed = time.time() - t0
            if progress_cb:
                progress_cb(prog)
        if progress_cb:
            progress_cb(prog)

    @property
    def has_baseline(self) -> bool:
        return self._has_baseline

    @property
    def baseline_bytes(self) -> int:
        return sum(len(b) for b in self._baseline.values())

    # ------------------------------------------------------------------
    # Применить действие (дифф / фильтр)
    # ------------------------------------------------------------------

    def apply_action(self, action_id: str, magnitude: float | None = None,
                     progress_cb: Callable[[AutoProgress], None] | None = None):
        """
        action_id — ключ из ACTIONS (напр. 'took_damage').
        magnitude — примерная величина изменения (необязательно).

        Первый вызов после baseline — полный дифф по всей памяти.
        Последующие — фильтр уже найденных кандидатов.
        """
        if action_id not in ACTIONS:
            raise ValueError(f"Неизвестное действие: {action_id}")
        kind, direction, desc = ACTIONS[action_id]
        t0 = time.time()
        prog = AutoProgress(step=desc, regions_total=len(self._baseline))
        if not self._has_baseline:
            raise RuntimeError("Сначала сделайте baseline-снимок.")

        if not self.candidates:
            # Полный дифф от baseline.
            new_cands: list[Candidate] = []
            for i, (base, old) in enumerate(self._baseline.items()):
                new = self._read_region(base, len(old))
                region_cands = self._diff_region(base, old, new, kind, direction, magnitude)
                new_cands.extend(region_cands)
                prog.regions_done = i + 1
                prog.candidates = len(new_cands)
                prog.elapsed = time.time() - t0
                if progress_cb:
                    progress_cb(prog)
            self.candidates = new_cands
        else:
            # Фильтр существующих кандидатов: перечитываем и проверяем направление.
            kept: list[Candidate] = []
            for c in self.candidates:
                cur = self._read_value(c.address, c.type_name)
                if cur is None:
                    continue
                if self._matches_direction(c.current, cur, direction, kind, magnitude):
                    delta = self._signed_delta(c.current, cur, direction)
                    c.baseline = c.current  # сдвигаем окно
                    c.current = cur
                    c.delta = delta
                    kept.append(c)
            self.candidates = kept
            prog.regions_done = len(self._baseline)
            prog.candidates = len(self.candidates)

        self._action_count += 1
        self._last_kind = kind
        self.classify(kind=kind)
        prog.candidates = len(self.candidates)
        prog.elapsed = time.time() - t0
        if progress_cb:
            progress_cb(prog)

    # ------------------------------------------------------------------
    # Внутренние: чтение и дифф
    # ------------------------------------------------------------------

    def _read_region(self, base: int, size: int) -> bytes:
        if not _HAS_NUMPY:
            # pure-python fallback — просто читаем целиком.
            off = 0
            out = bytearray()
            while off < size:
                sz = min(16 * 1024 * 1024, size - off)
                out += self.proc.read(base + off, sz)
                off += sz
            return bytes(out)
        off = 0
        out = bytearray()
        while off < size:
            sz = min(16 * 1024 * 1024, size - off)
            out += self.proc.read(base + off, sz)
            off += sz
        return bytes(out)

    def _diff_region(self, base: int, old: bytes, new: bytes,
                     kind: str | None, direction: str,
                     magnitude: float | None) -> list[Candidate]:
        """Векторизованный дифф одного региона. Возвращает кандидатов.

        Подход Cheat Engine:
        • один адрес = один тип. Сначала int32; float32 берём только для слотов,
          где int32 неправдоподобен, но float «чистый» (не денормаль, разумная
          величина). Так не плодятся мусорные float-интерпретации тех же байт
          (те самые «плавающие цифры без запятой»).
        • float-фильтр: |v| в [1e-4, 1e10] и не NaN/inf — убивает 1.4e-34, 6e23 и т.п.
        • для произвольного (custom) поиска сканируем только 4-байтные типы —
          этого хватает для ~99% игровых статов и сильно меньше шума/работы.
          8-байтные (int64/float64) — только для ресурсов, где они типичны.
        • «unchanged» на первом диффе бессмысленно (почти вся память) — пропускаем.
        """
        if not _HAS_NUMPY:
            return self._diff_region_pure(base, old, new, kind, direction, magnitude)
        if direction == "unchanged":
            return []

        sig = SIGNATURES.get(kind) if kind else None
        vrange = sig.value_range if sig else (0, 1_000_000_000)
        drange = sig.delta_range if sig else (1, 1_000_000_000)
        n = min(len(old), len(new))
        out: list[Candidate] = []

        # --- 4-байтные: int32, затем float32 (без дублей с int) ---
        n4 = (n // 4) * 4
        if n4 >= 4:
            oi = np.frombuffer(old, dtype="<i4", count=n4 // 4)
            ni = np.frombuffer(new, dtype="<i4", count=n4 // 4)
            int_mask = self._direction_mask(oi, ni, vrange, drange, direction, magnitude, is_float=False)
            out += self._candidates_from_mask(base, oi, ni, "int32", int_mask)
            of = np.frombuffer(old, dtype="<f4", count=n4 // 4)
            nf = np.frombuffer(new, dtype="<f4", count=n4 // 4)
            flt_mask = self._direction_mask(of, nf, vrange, drange, direction, magnitude, is_float=True)
            flt_mask &= ~int_mask  # не дублируем слоты, уже отданные как int32
            out += self._candidates_from_mask(base, of, nf, "float32", flt_mask)

        # --- 8-байтные: только для ресурсов с типичными int64/float64 (золото/опыт) ---
        n8 = (n // 8) * 8
        if n8 >= 8 and sig is not None and any(t in ("int64", "uint64", "float64") for t in sig.preferred_types):
            oi64 = np.frombuffer(old, dtype="<i8", count=n8 // 8)
            ni64 = np.frombuffer(new, dtype="<i8", count=n8 // 8)
            i64_mask = self._direction_mask(oi64, ni64, vrange, drange, direction, magnitude, is_float=False)
            out += self._candidates_from_mask(base, oi64, ni64, "int64", i64_mask)
            of64 = np.frombuffer(old, dtype="<f8", count=n8 // 8)
            nf64 = np.frombuffer(new, dtype="<f8", count=n8 // 8)
            f64_mask = self._direction_mask(of64, nf64, vrange, drange, direction, magnitude, is_float=True)
            f64_mask &= ~i64_mask
            out += self._candidates_from_mask(base, of64, nf64, "float64", f64_mask)
        return out

    def _direction_mask(self, old, new, vrange, drange, direction, magnitude, is_float):
        """Булева маска слотов, подошедших под направление + фильтры величины."""
        itemsize = old.dtype.itemsize
        if is_float:
            finite = np.isfinite(old) & np.isfinite(new)
            # «Чистый» float: не денормаль и разумная величина (1e-4 .. 1e10).
            flo = 1.175e-38 if itemsize == 4 else 2.225e-308   # min normal
            fhi = 1e10
            ao = np.abs(old); an = np.abs(new)
            clean = finite & (ao >= flo) & (ao <= fhi) & (an >= flo) & (an <= fhi)
        else:
            clean = np.ones(old.shape, dtype=bool)
        if direction == "decreased":
            dir_mask = (new < old) & clean
            d = (old - new).astype(np.float64)
        elif direction == "increased":
            dir_mask = (new > old) & clean
            d = (new - old).astype(np.float64)
        elif direction == "changed":
            dir_mask = (new != old) & clean
            d = np.abs(new.astype(np.float64) - old.astype(np.float64))
        else:  # unchanged — на первом диффе не используется (см. _diff_region)
            dir_mask = np.zeros(old.shape, dtype=bool)
            d = np.zeros(old.shape, dtype=np.float64)
        in_range = (
            (old.real >= vrange[0]) & (old.real <= vrange[1]) &
            (new.real >= vrange[0]) & (new.real <= vrange[1])
        )
        if magnitude is not None and magnitude > 0:
            lo = max(1, magnitude * 0.5)
            hi = magnitude * 2.0
            mag_ok = (d >= lo) & (d <= hi)
        else:
            mag_ok = (d >= drange[0]) & (d <= drange[1])
        return dir_mask & in_range & mag_ok

    def _candidates_from_mask(self, base, old, new, type_name, mask, cap=10000):
        item = old.dtype.itemsize
        is_float = "float" in type_name
        idxs = np.nonzero(mask)[0]
        if len(idxs) > cap:
            idxs = idxs[:cap]
        out: list[Candidate] = []
        for i in idxs:
            ov = float(old[i]); nv = float(new[i])
            if not is_float:
                ov = int(ov); nv = int(nv); dv = int(abs(ov - nv))
            else:
                dv = float(abs(ov - nv))
            out.append(Candidate(base + int(i) * item, type_name, ov, nv, dv))
        return out

    def _diff_region_pure(self, base, old, new, kind, direction, magnitude):
        """Медленный запасной путь без numpy (на случай её отсутствия)."""
        import struct
        if direction == "unchanged":
            return []
        sig = SIGNATURES.get(kind) if kind else None
        vrange = sig.value_range if sig else (0, 2_000_000_000)
        drange = sig.delta_range if sig else (1, 2_000_000_000)
        n = min(len(old), len(new))
        out = []
        for off in range(0, n - 3, 4):
            ov = struct.unpack_from("<i", old, off)[0]
            nv = struct.unpack_from("<i", new, off)[0]
            if ov == nv:
                continue
            if not (vrange[0] <= ov <= vrange[1] and vrange[0] <= nv <= vrange[1]):
                continue
            if direction == "decreased" and nv >= ov:
                continue
            if direction == "increased" and nv <= ov:
                continue
            d = abs(nv - ov)
            if magnitude and magnitude > 0:
                if not (magnitude * 0.5 <= d <= magnitude * 2):
                    continue
            elif not (drange[0] <= d <= drange[1]):
                continue
            out.append(Candidate(base + off, "int32", ov, nv, d))
            if len(out) > 20000:
                break
        return out

    # ------------------------------------------------------------------
    # Чтение одиночного значения (для фильтра кандидатов)
    # ------------------------------------------------------------------

    def _read_value(self, address: int, type_name: str):
        import struct
        fmts = {"int8": "<b", "uint8": "<B", "int16": "<h", "uint16": "<H",
                "int32": "<i", "uint32": "<I", "int64": "<q", "uint64": "<Q",
                "float32": "<f", "float64": "<d",
                "int16_be": ">h", "uint16_be": ">H", "int32_be": ">i",
                "uint32_be": ">I", "int64_be": ">q", "uint64_be": ">Q",
                "float32_be": ">f", "float64_be": ">d"}
        fmt = fmts.get(type_name)
        if fmt is None:
            return None
        sz = struct.calcsize(fmt)
        raw = self.proc.read(address, sz)
        if len(raw) != sz:
            return None
        try:
            return struct.unpack(fmt, raw)[0]
        except struct.error:
            return None

    def _matches_direction(self, old, cur, direction, kind, magnitude) -> bool:
        if old is None or cur is None:
            return False
        sig = SIGNATURES.get(kind) if kind else None
        vrange = sig.value_range if sig else (0, 2_000_000_000)
        if not (vrange[0] <= old <= vrange[1] and vrange[0] <= cur <= vrange[1]):
            return False
        if direction == "decreased":
            if cur >= old:
                return False
            d = old - cur
        elif direction == "increased":
            if cur <= old:
                return False
            d = cur - old
        elif direction == "unchanged":
            # Не изменилось с прошлого раза — узкий отсев тикающего шума
            # (таймеры/счётчики/RNG продолжают меняться и отсеиваются).
            return cur == old
        else:
            if cur == old:
                return False
            d = abs(cur - old)
        if magnitude and magnitude > 0:
            return magnitude * 0.5 <= d <= magnitude * 2
        drange = sig.delta_range if sig else (1, 2_000_000_000)
        return drange[0] <= d <= drange[1]

    def _signed_delta(self, old, cur, direction) -> float:
        if old is None or cur is None:
            return 0.0
        if direction == "decreased":
            return float(old - cur)
        if direction == "increased":
            return float(cur - old)
        return float(abs(cur - old))

    # ------------------------------------------------------------------
    # Классификация: проставить метку ресурса и confidence
    # ------------------------------------------------------------------

    def classify(self, kind: str | None = None):
        """Проставить каждому кандидату метку ресурса и confidence.
        kind — ресурс заявленного действия (если известен): даёт бонус +15
        совпадающей сигнатуре — пользователь сообщил намерение, это решающий
        сигнал среди структурно равных кандидатов (health/mana/ammo)."""
        use_kind = kind if kind is not None else self._last_kind
        for c in self.candidates:
            scores: dict[str, int] = {}
            for key, sig in SIGNATURES.items():
                scores[key] = self._score(c, sig, use_kind)
            # Лучший — максимальный score.
            best_key = max(scores, key=scores.get)
            best_score = scores[best_key]
            c.scores = scores
            # confidence = доля от теоретического максимума (~110, с kind-бонусом).
            c.best_label = SIGNATURES[best_key].label if best_score > 0 else "?"
            c.confidence = min(100, int(best_score * 100 / 110))
        # Сортируем: выше confidence — первыми.
        self.candidates.sort(key=lambda c: (-c.confidence, c.address))

    def _score(self, c: Candidate, sig: ResourceSignature, kind: str | None = None) -> int:
        s = 0
        # Диапазон значения (30 баллов).
        if sig.value_range[0] <= c.current <= sig.value_range[1]:
            s += 30
        # Предпочтительный тип (20).
        if c.type_name in sig.preferred_types:
            s += 20
        # Величина изменения в диапазоне (15).
        if sig.delta_range[0] <= c.delta <= sig.delta_range[1]:
            s += 15
        # Соседний паттерн: по смещению neighbor_offset лежит max-значение,
        # относящееся к текущему как ge (>=). Если сигнатура ожидает соседа,
        # а его нет — штраф -10: отличает gold/xp/level (без соседа) от
        # health/mana/ammo (с max-парой).
        if sig.neighbor_offset:
            neighbor = self._read_value(c.address + sig.neighbor_offset, "int32")
            if neighbor is not None and _relation_ok(neighbor, c.current, sig.neighbor_relation):
                s += 25
            else:
                # Попробуем как float32 (mana/health могут быть float).
                neighbor_f = self._read_value(c.address + sig.neighbor_offset, "float32")
                if neighbor_f is not None and _relation_ok(neighbor_f, c.current, sig.neighbor_relation):
                    s += 15
                else:
                    s -= 10  # ожидался max-сосед, но не подтверждён
        # Бонус за совпадение с заявленным действием (15).
        if kind is not None and kind == sig.name:
            s += 15
        # Бонус за "красивое" целое значение, не равное 0 (5).
        if isinstance(c.current, int) and c.current != 0:
            s += 5
        return s

    # ------------------------------------------------------------------
    # Публичные утилиты
    # ------------------------------------------------------------------

    def write_value(self, address: int, type_name: str, value) -> bool:
        import struct
        fmts = {"int8": "<b", "uint8": "<B", "int16": "<h", "uint16": "<H",
                "int32": "<i", "uint32": "<I", "int64": "<q", "uint64": "<Q",
                "float32": "<f", "float64": "<d"}
        fmt = fmts.get(type_name)
        if fmt is None:
            return False
        try:
            raw = struct.pack(fmt, value)
        except (struct.error, OverflowError):
            return False
        return self.proc.write(address, raw)

    def clear(self):
        self._baseline.clear()
        self.candidates.clear()
        self._has_baseline = False
        self._action_count = 0


def _relation_ok(neighbor, current, relation: str) -> bool:
    try:
        if relation == "ge":
            return neighbor >= current
        if relation == "le":
            return neighbor <= current
        if relation == "eq":
            return neighbor == current
    except TypeError:
        return False
    return False

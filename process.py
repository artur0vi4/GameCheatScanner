"""
process.py
Бэкенд доступа к памяти процесса.

На Windows: настоящие ctypes-обёртки над kernel32 (OpenProcess,
ReadProcessMemory, WriteProcessMemory, VirtualQueryEx) и ToolHelp32
для перечисления процессов.

На любой ОС (для демо/теста/UI-предпросмотра): MockProcess —
фейковый "игровой процесс" с health/ammo/gold/mana/level в памяти,
имитирующий живую игру (можно "получить урон", "выстрелить", "купить").

Оба бэкенда реализуют один и тот же интерфейс ProcessBackend, поэтому
сканер и авто-поиск работают одинаково в обоих режимах.
"""

from __future__ import annotations
import sys
import ctypes
import logging
from ctypes import wintypes
from dataclasses import dataclass
from typing import Iterator

_log = logging.getLogger("gamecheat")

IS_WINDOWS = sys.platform == "win32"


def is_admin() -> bool:
    """На Windows: запущен ли процесс с повышенными правами администратора.
    На не-Windows всегда False (реальный бэкенд там всё равно недоступен)."""
    if not IS_WINDOWS:
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


# ---------------------------------------------------------------------------
# Регион памяти (общий для всех бэкендов)
# ---------------------------------------------------------------------------

# Флаги защиты страниц (Windows-константы, но используются как нейтральные
# признаки "читаемо/перезаписываемо/исполняемо" и в mock-бэкенде тоже).
PAGE_NOACCESS = 0x01
PAGE_READONLY = 0x02
PAGE_READWRITE = 0x04
PAGE_WRITECOPY = 0x08
PAGE_EXECUTE = 0x10
PAGE_EXECUTE_READ = 0x20
PAGE_EXECUTE_READWRITE = 0x40
PAGE_EXECUTE_WRITECOPY = 0x80
PAGE_GUARD = 0x100

MEM_COMMIT = 0x1000
MEM_FREE = 0x10000
MEM_RESERVE = 0x2000
MEM_IMAGE = 0x1000000      # образ загруженного PE-модуля (код)
MEM_MAPPED = 0x40000       # файл, спроецированный в память
MEM_PRIVATE = 0x20000      # приватная память (куча, стек) — здесь живут данные игры


@dataclass
class Region:
    base: int          # начальный адрес
    size: int          # размер в байтах
    protect: int       # текущая защита (PAGE_*)
    state: int         # MEM_COMMIT / MEM_FREE / MEM_RESERVE
    mtype: int         # MEM_IMAGE / MEM_MAPPED / MEM_PRIVATE

    @property
    def readable(self) -> bool:
        """Можно ли читать. Игнорируем GUARD-страницы (читать нельзя)."""
        if self.state != MEM_COMMIT:
            return False
        if self.protect & PAGE_GUARD:
            return False
        return self.protect in (
            PAGE_READONLY, PAGE_READWRITE, PAGE_WRITECOPY,
            PAGE_EXECUTE_READ, PAGE_EXECUTE_READWRITE, PAGE_EXECUTE_WRITECOPY,
        )

    @property
    def writable(self) -> bool:
        if self.state != MEM_COMMIT:
            return False
        return self.protect in (PAGE_READWRITE, PAGE_WRITECOPY,
                                PAGE_EXECUTE_READWRITE, PAGE_EXECUTE_WRITECOPY)

    @property
    def is_data(self) -> bool:
        """
        Пригодно для поиска игровых значений: приватная (куча) или
        отображённая RW память, но НЕ исполняемый код (MEM_IMAGE с EXECUTE).
        Код сканировать бессмысленно — там инструкции, не данные; это
        ускоряет скан в десятки раз и убирает шум.
        """
        if not self.readable:
            return False
        if self.protect & PAGE_GUARD:
            return False
        # Исполняемые регионы пропускаем.
        if self.protect in (PAGE_EXECUTE, PAGE_EXECUTE_READ,
                            PAGE_EXECUTE_READWRITE, PAGE_EXECUTE_WRITECOPY):
            return False
        # MEM_IMAGE = загруженная DLL/exe (код + .rdata); данные игры
        # почти всегда в MEM_PRIVATE (куча) или MEM_MAPPED (файлы сохранений).
        return self.mtype in (MEM_PRIVATE, MEM_MAPPED, 0)


# ---------------------------------------------------------------------------
# Windows-бэкенд
# ---------------------------------------------------------------------------

# Права доступа к процессу: чтение + запись + запрос информации + операция
# (нужна для VirtualProtectEx при записи в read-only регионы).
PROCESS_ACCESS = (0x0400   # PROCESS_QUERY_INFORMATION
                  | 0x1000  # PROCESS_QUERY_LIMITED_INFORMATION
                  | 0x0010  # PROCESS_VM_READ
                  | 0x0020  # PROCESS_VM_WRITE
                  | 0x0008)  # PROCESS_VM_OPERATION


if IS_WINDOWS:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    # MEMORY_BASIC_INFORMATION имеет разный размер на x86/x64; на x64
    # добавлено поле PartitionId. Делаем архитектурно-зависимое определение.
    if ctypes.sizeof(ctypes.c_void_p) == 8:
        class MEMORY_BASIC_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BaseAddress", ctypes.c_void_p),
                ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wintypes.DWORD),
                ("PartitionId", wintypes.WORD),
                ("RegionSize", ctypes.c_size_t),
                ("State", wintypes.DWORD),
                ("Protect", wintypes.DWORD),
                ("Type", wintypes.DWORD),
            ]
    else:
        class MEMORY_BASIC_INFORMATION(ctypes.Structure):
            _fields_ = [
                ("BaseAddress", ctypes.c_void_p),
                ("AllocationBase", ctypes.c_void_p),
                ("AllocationProtect", wintypes.DWORD),
                ("RegionSize", ctypes.c_size_t),
                ("State", wintypes.DWORD),
                ("Protect", wintypes.DWORD),
                ("Type", wintypes.DWORD),
            ]

    TH32CS_SNAPPROCESS = 0x00000002

    class PROCESSENTRY32W(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.c_void_p),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_wchar * 260),
        ]

    def _list_processes_toolhelp() -> list[tuple[int, str]]:
        """Перечисление процессов через ToolHelp32 (CreateToolhelp32Snapshot)."""
        k32.CreateToolhelp32Snapshot.restype = wintypes.HANDLE
        k32.CreateToolhelp32Snapshot.argtypes = [wintypes.DWORD, wintypes.DWORD]
        k32.Process32FirstW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        k32.Process32FirstW.restype = wintypes.BOOL
        k32.Process32NextW.argtypes = [wintypes.HANDLE, ctypes.POINTER(PROCESSENTRY32W)]
        k32.Process32NextW.restype = wintypes.BOOL

        snap = k32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
        # CreateToolhelp32Snapshot при ошибке возвращает INVALID_HANDLE_VALUE
        # (-1), а не NULL. c_void_p (HANDLE) отдаёт беззнаковое значение,
        # поэтому сравниваем с 2^(битwidth)-1, а не только с 0/None.
        INVALID_HANDLE = (1 << (8 * ctypes.sizeof(ctypes.c_void_p))) - 1
        if not snap or int(snap) == INVALID_HANDLE:
            err = ctypes.get_last_error()
            _log.warning("Toolhelp: CreateToolhelp32Snapshot не удался (err=%s)", err)
            return []
        out: list[tuple[int, str]] = []
        pe = PROCESSENTRY32W()
        pe.dwSize = ctypes.sizeof(PROCESSENTRY32W)
        try:
            if k32.Process32FirstW(snap, ctypes.byref(pe)):
                while True:
                    out.append((int(pe.th32ProcessID), pe.szExeFile))
                    if not k32.Process32NextW(snap, ctypes.byref(pe)):
                        break
        finally:
            k32.CloseHandle(snap)
        out.sort(key=lambda x: x[1].lower())
        _log.info("Toolhelp: найдено процессов: %d", len(out))
        return out

    def _list_processes_psapi() -> list[tuple[int, str]]:
        """Запасной метод: EnumProcesses (Psapi) + QueryFullProcessImageNameW.
        Работает, если ToolHelp32 по какой-то причине вернул пусто. Имена
        получаем через QueryFullProcessImageNameW с правами
        PROCESS_QUERY_LIMITED_INFORMATION (доступно без админа для большинства
        процессов)."""
        try:
            psapi = ctypes.WinDLL("psapi.dll", use_last_error=True)
        except OSError as e:
            _log.warning("Psapi: не удалось загрузить psapi.dll: %s", e)
            return []
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]

        psapi.EnumProcesses.restype = wintypes.BOOL
        psapi.EnumProcesses.argtypes = [ctypes.POINTER(wintypes.DWORD),
                                        wintypes.DWORD,
                                        ctypes.POINTER(wintypes.DWORD)]
        arr = (wintypes.DWORD * 2048)()
        needed = wintypes.DWORD(0)
        if not psapi.EnumProcesses(arr, ctypes.sizeof(arr), ctypes.byref(needed)):
            _log.warning("Psapi: EnumProcesses не удался (err=%s)", ctypes.get_last_error())
            return []
        count = needed.value // ctypes.sizeof(wintypes.DWORD)
        _log.info("Psapi: EnumProcesses вернул %d pid", count)

        # QueryFullProcessImageNameW(handle, flags=0, buf, &size)
        psapi.QueryFullProcessImageNameW.restype = wintypes.BOOL
        psapi.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD,
                                                     ctypes.c_wchar_p,
                                                     ctypes.POINTER(wintypes.DWORD)]
        PROCESS_QUERY_LIMITED = 0x1000
        out: list[tuple[int, str]] = []
        buf = ctypes.create_unicode_buffer(260)
        for i in range(count):
            pid = int(arr[i])
            if pid == 0:
                continue
            h = k32.OpenProcess(PROCESS_QUERY_LIMITED, False, pid)
            if not h:
                # Не удалось открыть — покажем хотя бы pid, чтобы пользователь
                # мог опознать игру по номеру в диспетчере задач.
                out.append((pid, f"<pid {pid}>"))
                continue
            try:
                size = wintypes.DWORD(260)
                if psapi.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
                    name = buf.value.rsplit("\\", 1)[-1]
                    out.append((pid, name))
                else:
                    out.append((pid, f"<pid {pid}>"))
            finally:
                k32.CloseHandle(h)
        out.sort(key=lambda x: x[1].lower())
        _log.info("Psapi: собрано процессов с именами: %d", len(out))
        return out

    def list_processes() -> list[tuple[int, str]]:
        """Вернуть [(pid, имя_exe), ...], отсортировано по имени.
        Сначала ToolHelp32, при пустом результате — запасной Psapi."""
        out = _list_processes_toolhelp()
        if out:
            return out
        _log.warning("Toolhelp дал пусто — пробуем запасной метод Psapi")
        out = _list_processes_psapi()
        if out:
            return out
        _log.error("Оба метода перечисления процессов вернули пустой список. "
                   "Возможно, программа запущена без прав администратора в "
                   "ограниченной среде.")
        return []

    def list_processes_detailed() -> list[tuple[int, str, str]]:
        """[(pid, имя_exe, полный_путь)] — для классификации игр по пути.
        Перечисляет pid через list_processes(), путь берёт через
        QueryFullProcessImageNameW. Эта функция на Vista+ экспортируется
        kernel32.dll (не psapi!); на старых сборках — K32QueryFullProcessImageNameW
        в psapi. Если путь получить не удалось — пустая строка (классификация
        тогда по имени). Один сбой пути на pid НЕ валит весь список."""
        base = list_processes()
        # QueryFullProcessImageNameW живёт в kernel32 на современных Windows.
        try:
            kdll = ctypes.WinDLL("kernel32", use_last_error=True)
        except OSError:
            return [(pid, name, "") for pid, name in base]
        qfn = getattr(kdll, "QueryFullProcessImageNameW", None)
        if qfn is None:
            # Запасной вариант: K32-префикс в psapi (старые SDK).
            try:
                p2 = ctypes.WinDLL("psapi.dll", use_last_error=True)
                qfn = getattr(p2, "K32QueryFullProcessImageNameW", None)
            except OSError:
                qfn = None
        if qfn is None:
            # Пути недоступны — вернём список без путей (фильтр игр по имени).
            return [(pid, name, "") for pid, name in base]
        qfn.restype = wintypes.BOOL
        qfn.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_wchar_p,
                        ctypes.POINTER(wintypes.DWORD)]
        kdll.OpenProcess.restype = wintypes.HANDLE
        kdll.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        PROCESS_QUERY_LIMITED = 0x1000
        buf = ctypes.create_unicode_buffer(1024)
        out: list[tuple[int, str, str]] = []
        for pid, name in base:
            path = ""
            if pid > 0:
                try:
                    h = kdll.OpenProcess(PROCESS_QUERY_LIMITED, False, pid)
                except OSError:
                    h = 0
                if h:
                    try:
                        size = wintypes.DWORD(1024)
                        if qfn(h, 0, buf, ctypes.byref(size)):
                            path = buf.value
                    finally:
                        kdll.CloseHandle(h)
            out.append((pid, name, path))
        return out

else:
    def list_processes() -> list[tuple[int, str]]:
        """На не-Windows возвращаем только demo-процесс."""
        return [(-1, "DemoGame.exe (учебный режим)")]

    def list_processes_detailed() -> list[tuple[int, str, str]]:
        """На не-Windows возвращаем только demo-процесс."""
        return [(-1, "DemoGame.exe (учебный режим)", "")]


# ---------------------------------------------------------------------------
# Windows Process
# ---------------------------------------------------------------------------

class WindowsProcess:
    """Реальный доступ к памяти процесса через WinAPI."""

    def __init__(self, pid: int):
        if not IS_WINDOWS:
            raise RuntimeError("WindowsProcess можно использовать только на Windows.")
        k32.OpenProcess.restype = wintypes.HANDLE
        k32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        self.handle = k32.OpenProcess(PROCESS_ACCESS, False, pid)
        if not self.handle:
            err = ctypes.get_last_error()
            raise OSError(f"OpenProcess failed (pid={pid}). Код ошибки Win32: {err}. "
                          f"Запустите программу от имени администратора.")
        self.pid = pid

    def close(self):
        if getattr(self, "handle", None):
            k32.CloseHandle(self.handle)
            self.handle = None

    def __del__(self):
        try:
            self.close()
        except Exception:
            pass

    def iter_regions(self, data_only: bool = True) -> Iterator[Region]:
        """Перебор регионов виртуальной памяти. data_only=True — только данные."""
        k32.VirtualQueryEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                       ctypes.POINTER(MEMORY_BASIC_INFORMATION), ctypes.c_size_t]
        k32.VirtualQueryEx.restype = ctypes.c_size_t
        mbi = MEMORY_BASIC_INFORMATION()
        addr = 0
        max_addr = 0x7FFFFFFFFFFF if ctypes.sizeof(ctypes.c_void_p) == 8 else 0xFFFFFFFF
        while addr < max_addr:
            ret = k32.VirtualQueryEx(self.handle, ctypes.c_void_p(addr),
                                     ctypes.byref(mbi), ctypes.sizeof(mbi))
            if ret == 0:
                break
            region = Region(int(mbi.BaseAddress or 0), int(mbi.RegionSize),
                            int(mbi.Protect), int(mbi.State), int(mbi.Type))
            if (not data_only) or region.is_data:
                yield region
            # Следующий регион сразу за текущим.
            next_addr = int(mbi.BaseAddress or 0) + int(mbi.RegionSize)
            if next_addr <= addr:
                break  # защита от зацикливания
            addr = next_addr

    def read(self, address: int, size: int) -> bytes:
        """Прочитать size байт по адресу. Возвращает bytes (пусто при ошибке)."""
        k32.ReadProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                          ctypes.c_void_p, ctypes.c_size_t,
                                          ctypes.POINTER(ctypes.c_size_t)]
        k32.ReadProcessMemory.restype = wintypes.BOOL
        buf = (ctypes.c_char * size)()
        read = ctypes.c_size_t(0)
        ok = k32.ReadProcessMemory(self.handle, ctypes.c_void_p(address),
                                   buf, size, ctypes.byref(read))
        if not ok:
            return b""
        return bytes(buf[:read.value])

    def write(self, address: int, data: bytes) -> bool:
        """Записать data по адресу. При необходимости снимает защиту через
        VirtualProtectEx и возвращает её обратно."""
        k32.WriteProcessMemory.argtypes = [wintypes.HANDLE, ctypes.c_void_p,
                                           ctypes.c_void_p, ctypes.c_size_t,
                                           ctypes.POINTER(ctypes.c_size_t)]
        k32.WriteProcessMemory.restype = wintypes.BOOL
        k32.VirtualProtectEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.c_size_t,
                                         wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
        k32.VirtualProtectEx.restype = wintypes.BOOL
        size = len(data)
        if size == 0:
            return True
        buf = (ctypes.c_char * size).from_buffer_copy(data)
        old = wintypes.DWORD(0)
        # Пытаемся сделать страницу RW на время записи.
        protected = k32.VirtualProtectEx(self.handle, ctypes.c_void_p(address),
                                         size, PAGE_READWRITE, ctypes.byref(old))
        written = ctypes.c_size_t(0)
        ok = k32.WriteProcessMemory(self.handle, ctypes.c_void_p(address),
                                    buf, size, ctypes.byref(written))
        if protected:
            # Возвращаем исходную защиту.
            tmp = wintypes.DWORD(0)
            k32.VirtualProtectEx(self.handle, ctypes.c_void_p(address),
                                 size, old.value, ctypes.byref(tmp))
        return bool(ok and written.value == size)


# ---------------------------------------------------------------------------
# Mock Process (demo/тест/UI-предпросмотр) — работает на любой ОС
# ---------------------------------------------------------------------------

import struct
import random


class MockProcess:
    """
    Фейковый процесс с предсказуемой игровой памятью. Нужен, чтобы:
      1. Тестировать сканер и авто-поиск без реальной игры (здесь, на Linux).
      2. Дать пользователю prewiew UI до запуска программы в бою.
      3. Служить учебным материалом.

    Карта памяти (все RW, MEM_PRIVATE, выровнено):
      0x00100000: player struct
        +0x00  health   int32   = 100
        +0x04  max_hp   int32   = 100
        +0x08  mana     float32 = 50.0
        +0x0C  level    int32   = 1
      0x00101000: inventory
        +0x00  gold     int32   = 5000
        +0x04  ammo     int32   = 30
        +0x08  max_ammo int32   = 30
      0x00200000: "куча шума" — массив случайных меняющихся значений,
                   чтобы авто-поиск имел реалистичный фон для фильтрации.
    """

    PLAYER_BASE = 0x00100000
    PLAYER_SIZE = 0x1000
    INV_BASE = 0x00101000
    INV_SIZE = 0x1000
    NOISE_BASE = 0x00200000
    NOISE_SIZE = 0x10000  # 64 КБ шума

    def __init__(self):
        self.pid = -1
        self._mem: dict[int, bytearray] = {}
        self._regions: list[Region] = []
        self._noise_rng = random.Random(12345)
        self._reset()

    def _reset(self):
        # Три региона: игрок, инвентарь, шум.
        self._mem = {
            self.PLAYER_BASE: bytearray(self.PLAYER_SIZE),
            self.INV_BASE: bytearray(self.INV_SIZE),
            self.NOISE_BASE: bytearray(self.NOISE_SIZE),
        }
        self._regions = [
            Region(self.PLAYER_BASE, self.PLAYER_SIZE, PAGE_READWRITE, MEM_COMMIT, MEM_PRIVATE),
            Region(self.INV_BASE, self.INV_SIZE, PAGE_READWRITE, MEM_COMMIT, MEM_PRIVATE),
            Region(self.NOISE_BASE, self.NOISE_SIZE, PAGE_READWRITE, MEM_COMMIT, MEM_PRIVATE),
        ]
        p = self._mem[self.PLAYER_BASE]
        struct.pack_into("<i", p, 0x00, 100)     # health
        struct.pack_into("<i", p, 0x04, 100)     # max_hp
        struct.pack_into("<f", p, 0x08, 50.0)    # mana
        struct.pack_into("<i", p, 0x0C, 1)       # level
        iv = self._mem[self.INV_BASE]
        struct.pack_into("<i", iv, 0x00, 5000)   # gold
        struct.pack_into("<i", iv, 0x04, 30)     # ammo
        struct.pack_into("<i", iv, 0x08, 30)     # max_ammo
        self._refresh_noise()

    def _refresh_noise(self):
        """Заполнить шумовый регион случайными int32 (некоторые совпадут
        с искомыми значениями — реалистичный фон для сканера)."""
        n = self._mem[self.NOISE_BASE]
        for off in range(0, self.NOISE_SIZE - 4, 4):
            # Подкидываем значения, близкие к игровым, чтобы создать ложные
            # кандидаты — так авто-поиск имеет смысл фильтровать.
            pick = self._noise_rng.choice([
                self._noise_rng.randint(0, 10000),
                self._noise_rng.randint(0, 100),
                self._noise_rng.randint(0, 100000),
                int(self._noise_rng.uniform(0, 100)),  # иногда как float-биты
            ])
            struct.pack_into("<i", n, off, pick)

    # --- Симуляция игровых действий (для demo кнопок в UI) ---

    def simulate_damage(self, amount: int = 10):
        """Игрок получил урон: health -= amount."""
        p = self._mem[self.PLAYER_BASE]
        hp = struct.unpack_from("<i", p, 0x00)[0]
        hp = max(0, hp - amount)
        struct.pack_into("<i", p, 0x00, hp)

    def simulate_heal(self, amount: int = 10):
        p = self._mem[self.PLAYER_BASE]
        hp = struct.unpack_from("<i", p, 0x00)[0]
        max_hp = struct.unpack_from("<i", p, 0x04)[0]
        hp = min(max_hp, hp + amount)
        struct.pack_into("<i", p, 0x00, hp)

    def simulate_shoot(self, shots: int = 1):
        p = self._mem[self.INV_BASE]
        ammo = struct.unpack_from("<i", p, 0x04)[0]
        ammo = max(0, ammo - shots)
        struct.pack_into("<i", p, 0x04, ammo)

    def simulate_reload(self):
        p = self._mem[self.INV_BASE]
        max_a = struct.unpack_from("<i", p, 0x08)[0]
        struct.pack_into("<i", p, 0x04, max_a)

    def simulate_spend_gold(self, amount: int = 250):
        p = self._mem[self.INV_BASE]
        g = struct.unpack_from("<i", p, 0x00)[0]
        g = max(0, g - amount)
        struct.pack_into("<i", p, 0x00, g)

    def simulate_earn_gold(self, amount: int = 150):
        p = self._mem[self.INV_BASE]
        g = struct.unpack_from("<i", p, 0x00)[0]
        g += amount
        struct.pack_into("<i", p, 0x00, g)

    def simulate_tick(self):
        """Лёгкое дрожание шума — имитирует живой процесс (другие счётчики
        меняются, пока игрок стоит). Реальные игровые значения не трогаем."""
        n = self._mem[self.NOISE_BASE]
        # Меняем ~2% позиций шума.
        count = self.NOISE_SIZE // 4 // 50
        for _ in range(count):
            off = self._noise_rng.randrange(0, self.NOISE_SIZE - 4) & ~3
            val = self._noise_rng.randint(0, 10000)
            struct.pack_into("<i", n, off, val)

    # --- Интерфейс, совместимый с WindowsProcess ---

    def close(self):
        pass

    def iter_regions(self, data_only: bool = True) -> Iterator[Region]:
        for r in self._regions:
            if (not data_only) or r.is_data:
                yield r

    def read(self, address: int, size: int) -> bytes:
        for base, mem in self._mem.items():
            if base <= address < base + len(mem):
                off = address - base
                end = min(off + size, len(mem))
                return bytes(mem[off:end])
        return b""

    def write(self, address: int, data: bytes) -> bool:
        for base, mem in self._mem.items():
            if base <= address < base + len(mem):
                off = address - base
                end = min(off + len(data), len(mem))
                mem[off:end] = data[:end - off]
                return True
        return False


# ---------------------------------------------------------------------------
# Фабрика процесса
# ---------------------------------------------------------------------------

def open_process(pid: int):
    """
    Открыть процесс по pid. На Windows — WindowsProcess.
    pid == -1 (или не-Windows) — учебный MockProcess.
    """
    if pid == -1 or not IS_WINDOWS:
        return MockProcess()
    return WindowsProcess(pid)

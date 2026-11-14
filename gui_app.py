"""
gui_app.py
Tkinter-интерфейс программы — ОДИН экран без вкладок.

Поток (всё автоматизировано):
  1. Программа сама находит игры в списке процессов и подключается к первой.
  2. Введите значение из игры → «Поиск» (все типы автоматически + снимок памяти).
  3. Измените значение в игре → введите НОВОЕ → «Отсев».
     • Если точные совпадения есть — остаются они.
     • Если точных нет (значение хранится не как целое — float с дробью,
       масштаб и т.п.) — программа АВТОМАТИЧЕСКИ показывает адреса,
       изменившиеся при смене значения (режим «unknown + changed»),
       с автоматической классификацией (здоровье/маны/золото/…).
  4. Повторяйте «Отсев» — список сужается. Выберите адрес → «Записать»/«Заморозить».

Длинные операции — в фоновом потоке; прогресс/результат через очередь.
Значения в таблице обновляются вживую. Заморозка — отдельный поток-писатель.
"""

from __future__ import annotations
import math
import queue
import threading
import logging
import traceback
import tkinter as tk
from tkinter import ttk, messagebox

from datatypes import BY_NAME, DEFAULT_TYPE_NAMES
from scanner import Scanner, MODE_EXACT, ScanProgress
from auto_detect import AutoDetector
from process import (open_process, list_processes, list_processes_detailed,
                     MockProcess, IS_WINDOWS, is_admin)
from i18n import tr, LANGS, LANG_CODES, current_lang, set_lang
import icons

_log = logging.getLogger("gamecheat")

MAX_DISPLAY_ROWS = 5000

VERSION = "1.1.2"
GITHUB_URL = "https://github.com/artur0vi4/GameCheatScanner"

# ===========================================================================
# Палитра и тема
# ===========================================================================

C_BG        = "#16162a"
C_BG_PANEL  = "#1e1e36"
C_BG_ENTRY  = "#262645"
C_BG_ROW2   = "#20203a"
C_BORDER    = "#33335a"
C_FG        = "#e8e8f5"
C_FG_DIM    = "#9a9ac0"
C_FG_MUTED  = "#6c6c92"
C_ACCENT    = "#7c5cff"
C_ACCENT_HV = "#9373ff"
C_GREEN     = "#22d3a6"
C_AMBER     = "#f5b042"
C_RED       = "#ef5b6b"
C_BLUE      = "#4aa3ff"

F_TITLE   = ("Segoe UI", 16, "bold")
F_H       = ("Segoe UI", 11, "bold")
F_BODY    = ("Segoe UI", 10)
F_BODY_B  = ("Segoe UI", 10, "bold")
F_SMALL   = ("Segoe UI", 9)


def apply_theme(root: tk.Tk):
    s = ttk.Style()
    try:
        s.theme_use("clam")
    except tk.TclError:
        pass
    root.configure(bg=C_BG)
    s.configure("TFrame", background=C_BG)
    s.configure("TLabel", background=C_BG, foreground=C_FG, font=F_BODY)
    s.configure("Dim.TLabel", background=C_BG, foreground=C_FG_DIM, font=F_SMALL)
    s.configure("DimP.TLabel", background=C_BG_PANEL, foreground=C_FG_DIM, font=F_SMALL)
    s.configure("H.TLabel", background=C_BG, foreground=C_FG, font=F_H)
    s.configure("TLabelframe", background=C_BG_PANEL, bordercolor=C_BORDER, relief="solid", borderwidth=1)
    s.configure("TLabelframe.Label", background=C_BG_PANEL, foreground=C_ACCENT, font=F_H)
    s.configure("TButton", background=C_BG_ENTRY, foreground=C_FG, bordercolor=C_BORDER, font=F_BODY, padding=(10, 6))
    s.map("TButton", background=[("active", C_BORDER), ("disabled", C_BG_PANEL)], foreground=[("disabled", C_FG_MUTED)])
    s.configure("Accent.TButton", background=C_ACCENT, foreground="#ffffff", bordercolor=C_ACCENT, font=F_BODY_B, padding=(12, 7))
    s.map("Accent.TButton", background=[("active", C_ACCENT_HV), ("disabled", C_BG_PANEL)], foreground=[("disabled", C_FG_MUTED)])
    s.configure("Green.TButton", background=C_GREEN, foreground="#06281f", bordercolor=C_GREEN, font=F_BODY_B, padding=(10, 6))
    s.map("Green.TButton", background=[("active", "#3be0b6"), ("disabled", C_BG_PANEL)])
    s.configure("Danger.TButton", background=C_RED, foreground="#2a0a10", font=F_BODY_B, padding=(10, 6))
    s.map("Danger.TButton", background=[("active", "#f47687")])
    # Компактные иконки-кнопки в шапке (обновить список, о программе) —
    # в едином стиле с остальными элементами, а не «голые» квадраты.
    s.configure("Icon.TButton", background=C_BG_ENTRY, foreground=C_FG_DIM, bordercolor=C_BORDER, font=F_BODY, padding=(8, 5), width=3)
    s.map("Icon.TButton", background=[("active", C_BORDER)], foreground=[("active", C_FG)], bordercolor=[("active", C_ACCENT)])
    s.configure("TEntry", fieldbackground=C_BG_ENTRY, foreground=C_FG, bordercolor=C_BORDER, insertcolor=C_FG, padding=5)
    s.map("TEntry", bordercolor=[("focus", C_ACCENT)])
    s.configure("TCombobox", fieldbackground=C_BG_ENTRY, foreground=C_FG, background=C_BG_ENTRY, bordercolor=C_BORDER, arrowcolor=C_FG, padding=5)
    s.map("TCombobox", fieldbackground=[("readonly", C_BG_ENTRY)], background=[("active", C_BORDER)])
    root.option_add("*TCombobox*Listbox.background", C_BG_ENTRY)
    root.option_add("*TCombobox*Listbox.foreground", C_FG)
    root.option_add("*TCombobox*Listbox.selectBackground", C_ACCENT)
    root.option_add("*TCombobox*Listbox.selectForeground", "#ffffff")
    s.configure("TCheckbutton", background=C_BG_PANEL, foreground=C_FG_DIM, font=F_SMALL)
    s.map("TCheckbutton", background=[("active", C_BG_PANEL)])
    s.configure("Treeview", background=C_BG_PANEL, fieldbackground=C_BG_PANEL, foreground=C_FG, bordercolor=C_BORDER, rowheight=24)
    s.configure("Treeview.Heading", background=C_BG_ENTRY, foreground=C_FG, font=F_BODY_B, relief="flat", padding=(6, 6))
    s.map("Treeview", background=[("selected", C_ACCENT)], foreground=[("selected", "#ffffff")])
    s.map("Treeview.Heading", background=[("active", C_BORDER)])
    s.configure("TProgressbar", background=C_ACCENT, troughcolor=C_BG_ENTRY, bordercolor=C_BORDER, thickness=10)
    s.configure("TScrollbar", background=C_BG_ENTRY, troughcolor=C_BG_PANEL, bordercolor=C_BORDER, arrowcolor=C_FG)
    s.map("TScrollbar", background=[("active", C_BORDER)])
    s.configure("TSeparator", background=C_BORDER)


# ===========================================================================
# Классификация процессов: система / игра / приложение
# ===========================================================================

SYSTEM_NAMES = {
    "svchost.exe", "explorer.exe", "csrss.exe", "wininit.exe", "services.exe",
    "lsass.exe", "smss.exe", "winlogon.exe", "dwm.exe", "fontdrvhost.exe",
    "runtimebroker.exe", "searchhost.exe", "startmenuexperiencehost.exe",
    "texthost.exe", "sihost.exe", "taskhostw.exe", "ctfmon.exe", "conhost.exe",
    "wudfhost.exe", "audiodg.exe", "dllhost.exe", "systemsettings.exe",
    "applicationframehost.exe", "searchprotocolhost.exe", "searchfilterhost.exe",
    "wmiprvse.exe", "spoolsv.exe", "msmpeng.exe", "mpcmdrun.exe",
    "securityhealthservice.exe", "securityhealthsystray.exe",
    "widgetservice.exe", "widgets.exe", "phoneexperiencehost.exe",
    "msedgewebview2.exe", "edgeupdate.exe", "microsoftedgeupdate.exe",
    "gamecheatscanner.exe", "cmd.exe", "powershell.exe", "pwsh.exe",
    "firefox.exe", "chrome.exe", "msedge.exe", "opera.exe", "vivaldi.exe",
    "code.exe", "7zfm.exe", "winrar.exe",
}

GAME_PATH_KEYWORDS = (
    "steam", "steamapps", "\\common\\", "epic", "epicgames", "gog", "galaxy",
    "ubisoft", "uplay", "origin", "\\ea games\\", "battle.net", "battlenet",
    "\\games\\", "\\game\\", "windowsapps", "xbox", "bethesda", "riot",
    "blizzard", "\\my games\\",
)


def _classify_proc(name: str, path: str) -> str:
    n = (name or "").lower()
    p = (path or "").lower()
    if p.startswith("c:\\windows") or n in SYSTEM_NAMES:
        return "system"
    if any(k in p for k in GAME_PATH_KEYWORDS):
        return "game"
    return "app"


# Вспомогательные процессы игровых лаунчеров: оверлеи, анти-чит, крэш-хендлеры.
# Это НЕ сама игра — при авто-подключении их деприоритезируем (но показываем).
HELPER_HINTS = (
    "overlay", "crash", "anticheat", "easyanticheat", "battleye", "redist",
    "setup", "unins", "bootstrap", "helper", "eosoverlay", "service",
    "webhelper", "steamerrorreport", "cef", "browser",
)


def _is_helper(name: str) -> bool:
    n = (name or "").lower()
    return any(h in n for h in HELPER_HINTS)


# ===========================================================================
# Главное приложение
# ===========================================================================

class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title("GameCheat Scanner")
        root.geometry("1120x740")
        root.minsize(920, 620)
        root.configure(bg=C_BG)

        self.proc = None
        self.scanner: Scanner | None = None
        self.detector: AutoDetector | None = None
        self._proc_list: list = []
        self._procs_raw: list = []
        self._show_system = False
        self._job_queue: queue.Queue = queue.Queue()
        self._busy = False
        self._freeze_stop = threading.Event()
        self._freeze_thread: threading.Thread | None = None
        self.frozen: dict[int, dict] = {}
        self._selected_iid: str | None = None
        self._mode = "exact"
        self._first_value = None
        self._last_value = None      # предыдущее введённое значение (для отношения при ранжировании)
        self._marquee = False        # режим «бегущего» индикатора во время отсева

        # Иконки интерфейса (PNG base64, кэш на окно) + иконка окна в заголовке.
        self.icons = icons.load(root)
        root.iconphoto(False, self.icons["logo"])
        self._build_header()
        self._build_main()
        self._build_status_bar()
        if IS_WINDOWS:
            # Боевой режим: сразу ищем игры и авто-подключаемся.
            try:
                self._refresh_processes()
                self._check_admin()
            except Exception as e:
                _log.exception("Сбой при получении списка процессов: %s", e)
                self._set_status(tr("status_no_proc_list"))
        else:
            # На не-Windows чужой памяти нет — демо-режим (для предпросмотра).
            self._attach_demo()

        self.root.after(100, self._poll_queue)
        self.root.after(500, self._refresh_values_loop)

    # ------------------------------------------------------------------
    # Header
    # ------------------------------------------------------------------

    def _build_header(self):
        hdr = tk.Frame(self.root, bg=C_BG_PANEL, height=68)
        hdr.pack(fill=tk.X)
        hdr.pack_propagate(False)

        # Тонкая акцентная линия снизу — чёткая граница шапки от контента.
        tk.Frame(hdr, bg=C_ACCENT, height=2).pack(side=tk.BOTTOM, fill=tk.X)

        # Левая часть: иконка-знак + название + подзаголовок.
        left = tk.Frame(hdr, bg=C_BG_PANEL)
        left.pack(side=tk.LEFT, padx=(14, 8), pady=12)
        tk.Label(left, image=self.icons["logo"], bg=C_BG_PANEL).pack(side=tk.LEFT, padx=(0, 8))
        tbox = tk.Frame(left, bg=C_BG_PANEL)
        tbox.pack(side=tk.LEFT)
        tk.Label(tbox, text="GameCheat Scanner", bg=C_BG_PANEL, fg=C_FG, font=F_TITLE).pack(anchor=tk.W)
        tk.Label(tbox, text=tr("subtitle"),
                 bg=C_BG_PANEL, fg=C_FG_DIM, font=F_SMALL).pack(anchor=tk.W)

        # Правая часть: выбор процесса + сервисные кнопки + пилюля статуса.
        right = tk.Frame(hdr, bg=C_BG_PANEL)
        right.pack(side=tk.RIGHT, padx=(0, 12), pady=12)
        tk.Label(right, text=tr("process_label"), bg=C_BG_PANEL, fg=C_FG_DIM,
                 font=F_SMALL).pack(side=tk.LEFT, padx=(0, 4))
        self.proc_var = tk.StringVar()
        self.proc_combo = ttk.Combobox(right, textvariable=self.proc_var, width=30, state="readonly")
        self.proc_combo.pack(side=tk.LEFT, padx=2)
        # Выбор игры в списке = авто-подключение (кнопка не нужна).
        self.proc_combo.bind("<<ComboboxSelected>>", lambda _e: self._attach_selected())
        ttk.Button(right, image=self.icons["refresh"], style="Icon.TButton",
                   command=self._refresh_processes).pack(side=tk.LEFT, padx=2)
        self.sys_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(right, text=tr("all_processes"), variable=self.sys_var,
                        command=self._repopulate_combo).pack(side=tk.LEFT, padx=(6, 0))
        # Визуальный разделитель между блоком процесса и сервисными кнопками.
        tk.Frame(right, bg=C_BORDER, width=1).pack(side=tk.LEFT, fill=tk.Y, padx=10)
        ttk.Button(right, image=self.icons["info"], style="Icon.TButton",
                   command=self._show_about).pack(side=tk.LEFT, padx=2)
        # Переключатель языка (живая перестройка UI через _rebuild).
        self.lang_var = tk.StringVar()
        self.lang_combo = ttk.Combobox(right, textvariable=self.lang_var, width=9,
                                       values=[n for _, n in LANGS], state="readonly")
        try:
            self.lang_combo.current(LANG_CODES.index(current_lang()))
        except Exception:
            self.lang_combo.current(0)
        self.lang_combo.bind("<<ComboboxSelected>>", lambda _e: self._on_lang_change())
        self.lang_combo.pack(side=tk.LEFT, padx=(6, 0))
        # Статус-пилюля — чистая, в ряду справа (не «плавает» поверх шапки).
        self.status_pill = tk.Label(right, text="● " + tr("pill_demo"),
                                    bg=C_BG_PANEL, fg=C_GREEN, font=F_SMALL)
        self.status_pill.pack(side=tk.LEFT, padx=(10, 0))

    def _set_pill(self, text, color):
        self.status_pill.config(text=f"● {text}", fg=color)

    def _on_lang_change(self):
        idx = self.lang_combo.current()
        if idx < 0:
            return
        code = LANG_CODES[idx]
        if code == current_lang():
            return
        set_lang(code)
        self._rebuild()

    def _rebuild(self):
        """Живая перестройка UI при смене языка. Состояние (процесс,
        снимок, кандидаты, замороженные адреса) сохраняется на self."""
        last_status = self.status_var.get() if hasattr(self, "status_var") else ""
        pill_text = self.status_pill.cget("text") if hasattr(self, "status_pill") else ""
        pill_fg = self.status_pill.cget("fg") if hasattr(self, "status_pill") else C_GREEN
        count = self.scan_count_var.get() if hasattr(self, "scan_count_var") else ""
        for w in list(self.root.winfo_children()):
            w.destroy()
        self._build_header()
        self._build_main()
        self._build_status_bar()
        # Список процессов (без повторного авто-подключения — .current() не
        # генерирует <<ComboboxSelected>>, см. _auto_connect_top_game).
        if getattr(self, "_procs_raw", None):
            self._repopulate_combo()
        # Восстановить состояние поверх.
        if pill_text:
            self.status_pill.config(text=pill_text, fg=pill_fg)
        if last_status:
            self.status_var.set(last_status)
        if count:
            self.scan_count_var.set(count)
        if (self.detector and self.detector.candidates) or (self.scanner and self.scanner.matches):
            self._render_results()
        self._set_edit_enabled(False)

    def _show_about(self):
        win = tk.Toplevel(self.root)
        win.title(tr("about_title"))
        win.configure(bg=C_BG_PANEL)
        win.resizable(False, False)
        win.transient(self.root)
        win.grab_set()

        head = tk.Frame(win, bg=C_BG_PANEL)
        head.pack(fill=tk.X, padx=18, pady=(18, 8))
        tk.Label(head, image=self.icons["logo"], bg=C_BG_PANEL).pack(side=tk.LEFT, padx=(0, 8))
        ht = tk.Frame(head, bg=C_BG_PANEL)
        ht.pack(side=tk.LEFT)
        tk.Label(ht, text=f"GameCheat Scanner  v{VERSION}", bg=C_BG_PANEL, fg=C_FG, font=F_TITLE).pack(anchor=tk.W)
        tk.Label(ht, text=tr("subtitle"),
                 bg=C_BG_PANEL, fg=C_FG_DIM, font=F_SMALL).pack(anchor=tk.W)

        body = tk.Frame(win, bg=C_BG_PANEL)
        body.pack(fill=tk.X, padx=18, pady=(0, 8))
        lines = [
            (tr("about_what"), tr("about_what_body")),
            (tr("about_method"), tr("about_method_body")),
            (tr("about_thanks"), tr("about_thanks_body")),
            (tr("about_license"), tr("about_license_body")),
            (tr("about_source"), GITHUB_URL),
            (tr("about_support"), tr("about_support_body")),
        ]
        for title, text in lines:
            row = tk.Frame(body, bg=C_BG_PANEL)
            row.pack(fill=tk.X, pady=2)
            tk.Label(row, text=title + ":", bg=C_BG_PANEL, fg=C_ACCENT,
                     font=F_BODY_B, width=12, anchor=tk.NW).pack(side=tk.LEFT)
            tk.Label(row, text=text, bg=C_BG_PANEL, fg=C_FG, font=F_BODY,
                     justify=tk.LEFT, wraplength=420).pack(side=tk.LEFT, fill=tk.X)

        ttk.Button(win, text=tr("about_close"), command=win.destroy).pack(pady=(4, 14))
        win.update_idletasks()
        w, h = win.winfo_reqwidth(), win.winfo_reqheight()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        win.geometry(f"+{(sw - w) // 2}+{(sh - h) // 2}")

    # ------------------------------------------------------------------
    # Главный экран
    # ------------------------------------------------------------------

    def _build_main(self):
        strip = tk.Frame(self.root, bg=C_BG_PANEL, height=34)
        strip.pack(fill=tk.X)
        strip.pack_propagate(False)
        steps = [tr("step1"), tr("step2"), tr("step3"), tr("step4"), tr("step5")]
        for i, step in enumerate(steps, 1):
            tk.Label(strip, text=str(i), bg=C_ACCENT, fg="#ffffff", font=F_BODY_B, width=2, padx=4).pack(side=tk.LEFT, padx=(10, 4), pady=6)
            tk.Label(strip, text=step, bg=C_BG_PANEL, fg=C_FG_DIM, font=F_SMALL).pack(side=tk.LEFT, padx=(0, 6), pady=6)
            if i < len(steps):
                tk.Label(strip, text="→", bg=C_BG_PANEL, fg=C_FG_MUTED, font=F_SMALL).pack(side=tk.LEFT, padx=2)

        bar = tk.Frame(self.root, bg=C_BG)
        bar.pack(fill=tk.X, padx=10, pady=(8, 4))
        tk.Label(bar, text=tr("value_label"), bg=C_BG, fg=C_FG, font=F_BODY_B).pack(side=tk.LEFT, padx=(0, 6))
        self.value_var = tk.StringVar()
        self.value_entry = ttk.Entry(bar, textvariable=self.value_var, width=16, font=F_BODY)
        self.value_entry.pack(side=tk.LEFT, padx=(0, 8))
        self.value_entry.bind("<Return>", lambda _e: self._smart_scan())
        self.first_btn = ttk.Button(bar, text=tr("btn_search"), image=self.icons["search"], compound="left", style="Accent.TButton", command=self._do_first_scan)
        self.first_btn.pack(side=tk.LEFT, padx=2)
        self.next_btn = ttk.Button(bar, text=tr("btn_narrow"), image=self.icons["funnel"], compound="left", style="Accent.TButton", command=self._do_next_scan)
        self.next_btn.pack(side=tk.LEFT, padx=2)
        ttk.Button(bar, text=tr("btn_new_search"), image=self.icons["plus"], compound="left", command=self._new_scan).pack(side=tk.LEFT, padx=2)
        self.scan_count_var = tk.StringVar(value=tr("matches_found", n=0))
        tk.Label(bar, textvariable=self.scan_count_var, bg=C_BG, fg=C_GREEN, font=F_BODY_B).pack(side=tk.RIGHT)

        tk.Label(self.root,
                 text=tr("hint_main"),
                 bg=C_BG, fg=C_FG_DIM, font=F_SMALL).pack(anchor=tk.W, padx=12)

        self.progress = ttk.Progressbar(self.root, mode="determinate")
        self.progress.pack(fill=tk.X, padx=10, pady=(4, 4))

        # Нижние панели пакуем ПЕРВЫМИ (side=BOTTOM) — строка состояния и панель
        # редактирования всегда видны, даже когда окно не развёрнуто полностью.
        # Дерево результатов (expand) пакуем последним: оно заполняет середину и
        # первым ужмётся, если вертикального места не хватает.
        status = tk.Frame(self.root, bg=C_BG_PANEL, height=28)
        status.pack(fill=tk.X, side=tk.BOTTOM)
        status.pack_propagate(False)
        self.status_var = tk.StringVar(value=tr("status_demo_ready"))
        tk.Label(status, textvariable=self.status_var, bg=C_BG_PANEL, fg=C_FG_DIM,
                 font=F_SMALL).pack(side=tk.LEFT, padx=10, pady=4)

        edit = tk.Frame(self.root, bg=C_BG_PANEL)
        edit.pack(fill=tk.X, side=tk.BOTTOM, padx=10, pady=(0, 6))
        tk.Label(edit, text=tr("selected_addr"), bg=C_BG_PANEL, fg=C_FG_DIM, font=F_SMALL).pack(side=tk.LEFT, padx=(8, 4))
        self.sel_addr_var = tk.StringVar(value="—")
        tk.Label(edit, textvariable=self.sel_addr_var, bg=C_BG_PANEL, fg=C_FG, font=F_BODY_B).pack(side=tk.LEFT, padx=(0, 10))
        tk.Label(edit, text=tr("new_value"), bg=C_BG_PANEL, fg=C_FG_DIM, font=F_SMALL).pack(side=tk.LEFT, padx=(8, 4))
        self.write_var = tk.StringVar()
        self.write_entry = ttk.Entry(edit, textvariable=self.write_var, width=14, font=F_BODY)
        self.write_entry.pack(side=tk.LEFT, padx=(0, 6))
        self.write_btn = ttk.Button(edit, text=tr("btn_write"), image=self.icons["pen"], compound="left", style="Accent.TButton", command=self._write_selected)
        self.write_btn.pack(side=tk.LEFT, padx=2)
        self.freeze_btn = ttk.Button(edit, text=tr("btn_freeze"), image=self.icons["snowflake"], compound="left", style="Green.TButton", command=self._freeze_toggle_selected)
        self.freeze_btn.pack(side=tk.LEFT, padx=2)
        ttk.Button(edit, text=tr("btn_remove"), image=self.icons["trash"], compound="left", style="Danger.TButton", command=self._remove_selected).pack(side=tk.LEFT, padx=2)
        self._set_edit_enabled(False)

        # Дерево — последним: expand заполняет всё оставшееся пространство.
        tree_frame = tk.Frame(self.root, bg=C_BG)
        tree_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 4))
        cols = ("addr", "type", "value", "state")
        self.tree = ttk.Treeview(tree_frame, columns=cols, show="headings", height=16)
        for c, w, a, t in [("addr", 170, tk.W, tr("col_addr")), ("type", 90, tk.W, tr("col_type")),
                          ("value", 120, tk.E, tr("col_value")), ("state", 170, tk.W, tr("col_state"))]:
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor=a)
        self.tree.tag_configure("row2", background=C_BG_ROW2)
        self.tree.tag_configure("frozen", foreground=C_GREEN)
        vsb = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.tree.yview)
        self.tree.configure(yscrollcommand=vsb.set)
        self.tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        vsb.pack(side=tk.RIGHT, fill=tk.Y)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._on_select())

    def _build_status_bar(self):
        # Устаревший метод: строка состояния теперь строится в _build_main
        # (pack side=BOTTOM до дерева) — оставлен как no-op для совместимости.
        pass

    # ------------------------------------------------------------------
    # Процессы: фильтр игр + авто-подключение
    # ------------------------------------------------------------------

    def _refresh_processes(self):
        try:
            procs = list_processes_detailed()
        except Exception as e:
            _log.exception("list_processes_detailed() ошибся: %s", e)
            self.proc_combo["values"] = []
            self._set_status(tr("status_proc_list_err", e=e))
            return
        self._procs_raw = procs
        self._repopulate_combo()
        real_connected = self.proc is not None and not isinstance(self.proc, MockProcess)
        if not real_connected:
            self._auto_connect_top_game()

    def _repopulate_combo(self):
        procs = self._procs_raw
        classified = [(pid, name, path, _classify_proc(name, path)) for pid, name, path in procs]
        if not self._show_system:
            classified = [p for p in classified if p[3] != "system"]
        order = {"game": 0, "app": 1, "system": 2}
        # Игры идут первыми; среди игр — настоящие игры раньше вспомогательных
        # (оверлеи/анти-чит), потом по имени.
        classified.sort(key=lambda p: (order.get(p[3], 1),
                                       1 if (p[3] == "game" and _is_helper(p[1])) else 0,
                                       p[1].lower()))
        self._proc_list = classified
        items = []
        for pid, name, path, cls in classified:
            if cls == "game":
                mark = "♦ " if _is_helper(name) else "► "
            elif cls == "app":
                mark = "▪ "
            else:
                mark = "· "
            items.append(f"{mark}{name}  (pid {pid})")
        self.proc_combo["values"] = items
        n_games = sum(1 for p in classified if p[3] == "game" and not _is_helper(p[1]))
        n_helpers = sum(1 for p in classified if p[3] == "game" and _is_helper(p[1]))
        n_apps = sum(1 for p in classified if p[3] == "app")
        admin_txt = tr("admin_yes") if is_admin() else tr("admin_no")
        if items:
            self.proc_combo.current(0)
            self._set_status(tr("status_admin_games", admin=admin_txt, games=n_games,
                                helpers=n_helpers, apps=n_apps))
        else:
            self._set_status(tr("status_admin_no_procs", admin=admin_txt))

    def _auto_connect_top_game(self):
        # Сначала пробуем настоящую игру (не оверлей/анти-чит).
        games = [p for p in self._proc_list if p[3] == "game" and not _is_helper(p[1])]
        if not games:
            games = [p for p in self._proc_list if p[3] == "game"]
        if not games:
            return
        pid, name = games[0][0], games[0][1]
        for i, (pid2, name2, _, _) in enumerate(self._proc_list):
            if pid2 == pid and name2 == name:
                self.proc_combo.current(i)
                break
        _log.info("Авто-подключение к игре: pid=%s name=%s", pid, name)
        self._attach_selected()

    def _check_admin(self):
        if is_admin():
            self._set_pill(tr("pill_demo_admin"), C_GREEN)
        else:
            self._set_pill(tr("pill_demo_no_admin"), C_AMBER)

    def _attach_selected(self):
        if not IS_WINDOWS:
            messagebox.showinfo(tr("msg_demo_title"), tr("msg_demo_body"))
            self._attach_demo()
            return
        sel = self.proc_combo.get()
        if not sel:
            self._refresh_processes()
            sel = self.proc_combo.get()
            if not sel:
                return
        try:
            pid = int(sel.rsplit("(pid", 1)[1].strip(" )"))
        except Exception:
            messagebox.showerror(tr("msg_error"), tr("msg_pid_err"))
            return
        if pid <= 0:
            self._attach_demo()
            return
        _log.info("Попытка подключиться к pid=%s", pid)
        try:
            self.proc = open_process(pid)
        except OSError as e:
            _log.warning("OpenProcess не удался для pid=%s: %s", pid, e)
            messagebox.showerror(tr("msg_open_err_title"), tr("msg_open_err_body", e=e))
            return
        except Exception as e:
            _log.exception("Непредвиденная ошибка при открытии pid=%s: %s", pid, e)
            messagebox.showerror(tr("msg_open_err_title"), tr("msg_open_err_log", e=e))
            return
        _log.info("Подключён процесс pid=%s", pid)
        self.scanner = None
        self.detector = None
        self._mode = "exact"
        self._last_value = None
        name = sel.rsplit("(pid", 1)[0].strip().lstrip("►▪·♦ ").strip()
        self._set_pill(tr("pill_connected", name=name), C_BLUE)
        self._set_status(tr("status_connected", pid=pid, name=name))

    def _attach_demo(self):
        self.proc = MockProcess()
        self.scanner = None
        self.detector = None
        self._mode = "exact"
        self._last_value = None
        self._set_pill(tr("pill_demo"), C_GREEN)
        self._set_status(tr("status_demo_intro"))

    # ------------------------------------------------------------------
    # Фоновый исполнитель + опрос очереди
    # ------------------------------------------------------------------

    def _run_bg(self, fn):
        if self._busy:
            messagebox.showinfo(tr("msg_busy_title"), tr("msg_busy_body"))
            return
        self._busy = True
        self._set_busy_ui(True)
        threading.Thread(target=_worker, args=(fn, self._job_queue), daemon=True).start()

    def _poll_queue(self):
        try:
            while True:
                kind, payload = self._job_queue.get_nowait()
                if kind == "progress":
                    self._on_progress(payload)
                elif kind == "done":
                    self._on_done(payload)
                elif kind == "error":
                    self._on_error(payload)
        except queue.Empty:
            pass
        self.root.after(100, self._poll_queue)

    def _on_progress(self, data: dict):
        if "msg" in data:
            self._set_status(data["msg"])
        if "matches" in data:
            cnt = data["matches"]
            if self._mode == "auto":
                self.scan_count_var.set(tr("matches_candidates", n=cnt))
            else:
                self.scan_count_var.set(tr("matches_found", n=cnt))
        # Движение полосы прогресса — только в детерминированном режиме
        # (во время отсева работает «бегущий» индикатор, полосу не трогаем).
        if not self._marquee and "regions_total" in data:
            total = data.get("regions_total", 0) or 1
            self.progress["maximum"] = total
            self.progress["value"] = data.get("regions_done", 0)

    def _marquee_on(self, text: str):
        self._marquee = True
        try:
            self.progress.config(mode="indeterminate")
            self.progress.start(12)
        except tk.TclError:
            pass
        self._set_status(text)

    def _marquee_off(self):
        try:
            self.progress.stop()
            self.progress.config(mode="determinate")
        except tk.TclError:
            pass
        self.progress["value"] = 0
        self._marquee = False

    def _on_done(self, payload):
        self._busy = False
        self._set_busy_ui(False)
        self._marquee_off()
        tag = payload[0] if isinstance(payload, tuple) else None
        if tag == "first_scan":
            self._mode = "exact"
            self._last_value = None
            self.scan_count_var.set(tr("matches_found", n=payload[1]))
            self._render_results()
            extra = tr("extra_baseline") if self.detector and self.detector.has_baseline else ""
            self._set_status(tr("status_first_done", n=payload[1], extra=extra))
        elif tag == "next_scan":
            self._mode = "exact"
            self._last_value = None
            self.scan_count_var.set(tr("matches_found", n=payload[1]))
            self._render_results()
            self._set_status(tr("status_next_done", n=payload[1]))
        elif tag == "auto_fallback":
            self._mode = "auto"
            n = payload[1]
            kind = payload[2] if len(payload) > 2 else "directed"
            self.scan_count_var.set(tr("matches_candidates", n=n))
            self._render_results()
            if n > 0 and kind == "directed":
                self._set_status(tr("status_auto_directed", n=n))
            elif n > 0 and kind == "unchanged":
                self._set_status(tr("status_auto_unchanged", n=n))
            else:
                self._set_status(tr("status_auto_empty"))
        else:
            self._set_status(tr("status_done"))

    def _on_error(self, msg):
        self._busy = False
        self._set_busy_ui(False)
        self._marquee_off()
        messagebox.showerror(tr("msg_op_error_title"), msg)
        self._set_status(tr("msg_error") + ": " + msg[:120])

    def _set_busy_ui(self, busy: bool):
        for btn in (self.first_btn, self.next_btn, self.write_btn, self.freeze_btn):
            try:
                btn.state(["!disabled"] if not busy else ["disabled"])
            except Exception:
                pass

    # ------------------------------------------------------------------
    # Скан
    # ------------------------------------------------------------------

    def _parse_value(self, text):
        text = text.strip()
        try:
            return int(text)
        except ValueError:
            return float(text)

    def _smart_scan(self):
        if self._mode == "auto":
            self._do_next_scan()
        elif self.scanner and self.scanner.matches:
            self._do_next_scan()
        else:
            self._do_first_scan()

    def _ensure_detector(self):
        if self.detector is None:
            self.detector = AutoDetector(self.proc)

    def _do_first_scan(self):
        if not self.proc:
            messagebox.showinfo(tr("msg_no_proc_title"), tr("msg_no_proc_body"))
            return
        try:
            val = self._parse_value(self.value_var.get())
        except ValueError:
            messagebox.showerror(tr("msg_value_title"), tr("msg_value_body"))
            return
        self.scanner = Scanner(self.proc, DEFAULT_TYPE_NAMES)
        self.frozen.clear()
        self._clear_tree(self.tree)
        self.scan_count_var.set(tr("scanning"))

        def job(on_progress):
            def cb(p: ScanProgress):
                on_progress({"regions_total": p.regions_total, "regions_done": p.regions_done,
                             "matches": p.matches,
                             "msg": tr("prog_first", done=p.regions_done, total=p.regions_total, matches=p.matches)})
            n = self.scanner.first_scan(val, progress_cb=cb)
            # Снимок всей памяти для авто-отсева (если точный даст 0).
            try:
                self._ensure_detector()
                self.detector.capture_baseline(
                    progress_cb=lambda p: on_progress({
                        "regions_total": p.regions_total, "regions_done": p.regions_done,
                        "msg": tr("prog_baseline", done=p.regions_done, total=p.regions_total)}))
            except Exception as e:
                _log.warning("baseline не собран (авто-отсев будет недоступен): %s", e)
            self._first_value = val
            return ("first_scan", n)
        self._run_bg(job)

    def _do_next_scan(self):
        if self._mode == "exact":
            if not self.scanner or not self.scanner.matches:
                messagebox.showinfo(tr("msg_no_data_title"), tr("msg_no_data_body"))
                return
            try:
                val = self._parse_value(self.value_var.get())
            except ValueError:
                messagebox.showerror(tr("msg_value_title"), tr("msg_new_value_body"))
                return
        else:  # auto — поле значения задаёт тип отсева:
            #   пусто  → «значение НЕ изменилось» (отсев тикающего шума, как в Cheat Engine)
            #   число  → направленный отсев (упало/выросло к этому значению) + ранжирование
            raw = self.value_var.get().strip()
            if not raw:
                val = None
            else:
                try:
                    val = self._parse_value(raw)
                except ValueError:
                    val = None

        # Чёткая индикация: «бегущий» индикатор + статус.
        if self._mode == "auto":
            if val is None:
                self._marquee_on(tr("prog_narrow_noise"))
            else:
                self._marquee_on(tr("prog_narrow_directed"))
        else:
            self._marquee_on(tr("prog_narrow_exact"))

        def job(on_progress):
            def cb(p):
                # AutoProgress (apply_action) несёт регионы и кандидатов;
                # ScanProgress (next_scan) — регионы и совпадения.
                rt = getattr(p, "regions_total", 0)
                rd = getattr(p, "regions_done", 0)
                cnt = getattr(p, "candidates", None)
                if cnt is None:
                    cnt = getattr(p, "matches", 0)
                if rt:
                    msg = tr("prog_narrow_cmp", done=rd, total=rt, cnt=cnt)
                else:
                    msg = tr("prog_narrow_short", cnt=cnt)
                on_progress({"matches": cnt, "msg": msg})
            if self._mode == "auto":
                if val is None:
                    # Узкий отсев: оставить только НЕ изменившиеся с прошлого раза.
                    self.detector.apply_action("custom_unchanged", progress_cb=cb)
                    return ("auto_fallback", len(self.detector.candidates), "unchanged")
                # Направленный отсев к введённому значению (в ~2× избирательнее «changed»).
                rank_old = self._last_value if self._last_value is not None else self._first_value
                rank_new = val
                direction = ("custom_dec" if (rank_old is not None and val < rank_old) else
                             "custom_inc" if (rank_old is not None and val > rank_old) else "custom_chg")
                _log.info("Отсев(auto): направление=%s (new=%r old=%r)", direction, val, rank_old)
                self.detector.apply_action(direction, progress_cb=cb)
                self._last_value = val
                self._rank_candidates(rank_old, rank_new)
                return ("auto_fallback", len(self.detector.candidates), "directed")
            n = self.scanner.next_scan(MODE_EXACT, value=val, float_tol=0.0, progress_cb=cb)
            if n > 0:
                return ("next_scan", n)
            # FALLBACK: точных нет → ищем изменившиеся адреса.
            if self.detector and self.detector.has_baseline:
                fv = self._first_value
                direction = "custom_dec" if (fv is not None and val < fv) else (
                    "custom_inc" if (fv is not None and val > fv) else "custom_chg")
                _log.info("Отсев: точных 0 → авто-fallback направление=%s (new=%r old=%r)", direction, val, fv)
                on_progress({"msg": tr("prog_narrow_fallback")})
                self.detector.apply_action(direction, progress_cb=cb)
                self._last_value = val
                self._rank_candidates(fv, val)
                return ("auto_fallback", len(self.detector.candidates), "directed")
            return ("next_scan", 0)
        self._run_bg(job)

    def _rank_candidates(self, old_target, new_target):
        """Отсортировать авто-кандидатов по похожести на изменение значения пользователя.

        У настоящего ресурса old→new повторяет введённое (770→387). Отношение
        old/new масштабно-инвариантно: работает и для int, и для float с дробью,
        и для масштабированного хранения (×k). Шум такого отношения почти не имеет.
        Наверх таблицы всплывают самые вероятные адреса."""
        cs = self.detector.candidates if self.detector else []
        if not cs or old_target is None or new_target is None:
            return
        try:
            nt = float(new_target)
            ot = float(old_target)
            if nt <= 0 or ot <= 0:
                return
            log_tr = math.log(ot / nt)
        except (TypeError, ValueError, ZeroDivisionError):
            return
        def score(c):
            o, n = c.baseline, c.current
            try:
                of, nf = float(o), float(n)
            except (TypeError, ValueError):
                return (3, 9e9)
            # Правдоподобие величины: положительные, не указатели/не гигантские.
            plausible = (0 < of < 1e8 and 0 < nf < 1e8)
            if not plausible or nf <= 0 or of <= 0:
                return (2, 9e9)
            # Расстояние по логарифму отношения (масштабно-инвариантно).
            try:
                dr = abs(math.log(of / nf) - log_tr)
            except (ValueError, ZeroDivisionError):
                dr = 9e9
            return (0, dr)
        try:
            cs.sort(key=score)
        except Exception:
            _log.exception("Ранжирование кандидатов не удалось.")

    def _new_scan(self):
        if self.scanner:
            self.scanner.clear()
        if self.detector:
            self.detector.clear()
        self.frozen.clear()
        self._mode = "exact"
        self._last_value = None
        self._clear_tree(self.tree)
        self.scan_count_var.set(tr("matches_found", n=0))
        self.sel_addr_var.set("—")
        self._set_edit_enabled(False)
        self._set_status(tr("status_new_search"))

    def _render_results(self):
        self._clear_tree(self.tree)
        if self._mode == "auto" and self.detector:
            cs = self.detector.candidates
            # Кандидаты уже отсортированы по похожести (ранжирование) —
            # показываем топ, чтобы настоящий адрес был виден сразу.
            for i, c in enumerate(cs[:2000]):
                tags = []
                if c.address in self.frozen:
                    tags.append("frozen")
                if i % 2 == 1:
                    tags.append("row2")
                state = ("■ " if c.address in self.frozen else "") + tr(c.best_label or "res_unknown")
                if c.confidence:
                    state += f" {c.confidence}%"
                self.tree.insert("", tk.END, iid=str(i), tags=tuple(tags),
                                 values=(hex(c.address), c.type_name, _fmt(c.current), state))
            return
        ms = self.scanner.matches if self.scanner else []
        for i, m in enumerate(ms[:MAX_DISPLAY_ROWS]):
            tags = []
            if m.address in self.frozen:
                tags.append("frozen")
            if i % 2 == 1:
                tags.append("row2")
            state = tr("frozen_state") if m.address in self.frozen else ""
            self.tree.insert("", tk.END, iid=str(i), tags=tuple(tags),
                             values=(hex(m.address), m.type_name, _fmt(m.value), state))

    # ------------------------------------------------------------------
    # Выбор / запись / заморозка
    # ------------------------------------------------------------------

    def _on_select(self):
        sel = self.tree.selection()
        if not sel:
            self._selected_iid = None
            self.sel_addr_var.set("—")
            self._set_edit_enabled(False)
            return
        iid = sel[0]
        self._selected_iid = iid
        info = self._selected_addr_info()
        if info:
            self.sel_addr_var.set(f"{info[0]}  ({info[1]})")
            self._set_edit_enabled(True)

    def _selected_addr_info(self):
        if self._selected_iid is None:
            return None
        try:
            idx = int(self._selected_iid)
        except ValueError:
            return None
        if self._mode == "auto" and self.detector:
            cs = self.detector.candidates
            if 0 <= idx < len(cs):
                c = cs[idx]
                return (hex(c.address), c.type_name, c.current)
            return None
        if self.scanner:
            ms = self.scanner.matches
            if 0 <= idx < len(ms):
                m = ms[idx]
                return (hex(m.address), m.type_name, m.value)
        return None

    def _set_edit_enabled(self, enabled: bool):
        state = "!disabled" if enabled else "disabled"
        for w in (self.write_entry, self.write_btn, self.freeze_btn):
            try:
                w.state([state])
            except Exception:
                pass

    def _write_selected(self):
        info = self._selected_addr_info()
        if info is None:
            messagebox.showinfo(tr("msg_no_sel_title"), tr("msg_no_sel_body"))
            return
        addr_s, typ, _cur = info
        try:
            val = self._parse_value(self.write_var.get())
        except ValueError:
            messagebox.showerror(tr("msg_value_title"), tr("msg_write_val_body"))
            return
        dt = BY_NAME.get(typ)
        if not dt:
            return
        addr = int(addr_s, 16)
        raw = dt.pack(val)
        ok = bool(raw and self.proc and self.proc.write(addr, raw))
        if ok:
            try:
                self._update_model_value(int(self._selected_iid), val)
            except Exception:
                pass
            self.tree.set(self._selected_iid, "value", _fmt(val))
            _log.info("Записано %r по адресу %s (%s)", val, addr_s, typ)
            self._set_status(tr("status_written", val=val, addr=addr_s, type=typ))
        else:
            messagebox.showerror(tr("msg_write_err_title"), tr("msg_write_err_body"))

    def _update_model_value(self, idx: int, value):
        if self._mode == "auto" and self.detector:
            cs = self.detector.candidates
            if 0 <= idx < len(cs):
                cs[idx].current = value
        elif self.scanner:
            ms = self.scanner.matches
            if 0 <= idx < len(ms):
                ms[idx].value = value

    def _freeze_toggle_selected(self):
        info = self._selected_addr_info()
        if info is None:
            messagebox.showinfo(tr("msg_no_sel_title"), tr("msg_no_sel_body"))
            return
        addr_s, typ, cur = info
        addr = int(addr_s, 16)
        iid = self._selected_iid
        if addr in self.frozen:
            del self.frozen[addr]
            self._refresh_row_state(iid, addr)
            self.freeze_btn.config(text=tr("btn_freeze"))
            self._set_status(tr("status_unfrozen", addr=addr_s))
        else:
            try:
                fv = self._parse_value(self.write_var.get()) if self.write_var.get().strip() else cur
            except ValueError:
                fv = cur
            self.frozen[addr] = {"type_name": typ, "value": fv}
            self._refresh_row_state(iid, addr)
            self.freeze_btn.config(text=tr("btn_unfreeze"))
            self._ensure_freeze_thread()
            _log.info("Заморожено %s (%s) = %r", addr_s, typ, fv)
            self._set_status(tr("status_frozen", addr=addr_s, val=fv))

    def _refresh_row_state(self, iid: str, addr: int):
        if iid is None or not self.tree.exists(iid):
            return
        if self._mode == "auto" and self.detector:
            try:
                idx = int(iid)
                c = self.detector.candidates[idx]
                state = ("■ " if addr in self.frozen else "") + tr(c.best_label or "res_unknown")
                if c.confidence:
                    state += f" {c.confidence}%"
            except Exception:
                state = ""
        else:
            state = tr("frozen_state") if (addr in self.frozen) else ""
        self.tree.set(iid, "state", state)
        tags = list(self.tree.item(iid, "tags"))
        if addr in self.frozen:
            if "frozen" not in tags:
                tags.append("frozen")
        else:
            tags = [t for t in tags if t != "frozen"]
        self.tree.item(iid, tags=tuple(tags))

    def _remove_selected(self):
        if self._selected_iid is None:
            return
        try:
            idx = int(self._selected_iid)
        except ValueError:
            return
        if self._mode == "auto" and self.detector:
            cs = self.detector.candidates
            if 0 <= idx < len(cs):
                if cs[idx].address in self.frozen:
                    del self.frozen[cs[idx].address]
                del cs[idx]
            self._render_results()
            self.scan_count_var.set(tr("matches_candidates", n=len(self.detector.candidates)))
        elif self.scanner:
            ms = self.scanner.matches
            if 0 <= idx < len(ms):
                if ms[idx].address in self.frozen:
                    del self.frozen[ms[idx].address]
                del ms[idx]
            self._render_results()
            self.scan_count_var.set(tr("matches_found", n=len(self.scanner.matches)))
        self.sel_addr_var.set("—")
        self._set_edit_enabled(False)

    # ------------------------------------------------------------------
    # Живое обновление значений + заморозка
    # ------------------------------------------------------------------

    def _refresh_values_loop(self):
        try:
            if self.proc:
                if self._mode == "auto" and self.detector:
                    cs = self.detector.candidates
                    for i in range(min(len(cs), MAX_DISPLAY_ROWS)):
                        iid = str(i)
                        try:
                            if not self.tree.exists(iid):
                                continue
                        except Exception:
                            continue
                        c = cs[i]
                        if c.address in self.frozen:
                            cur = self.frozen[c.address]["value"]
                        else:
                            dt = BY_NAME.get(c.type_name)
                            cur = c.current
                            if dt:
                                raw = self.proc.read(c.address, dt.size)
                                if raw:
                                    v = dt.unpack(raw)
                                    if v is not None:
                                        cur = v
                                        c.current = v
                        try:
                            self.tree.set(iid, "value", _fmt(cur))
                        except Exception:
                            pass
                elif self.scanner and self.scanner.matches:
                    ms = self.scanner.matches
                    for i in range(min(len(ms), MAX_DISPLAY_ROWS)):
                        iid = str(i)
                        try:
                            if not self.tree.exists(iid):
                                continue
                        except Exception:
                            continue
                        m = ms[i]
                        if m.address in self.frozen:
                            cur = self.frozen[m.address]["value"]
                        else:
                            dt = BY_NAME.get(m.type_name)
                            cur = m.value
                            if dt:
                                raw = self.proc.read(m.address, dt.size)
                                if raw:
                                    v = dt.unpack(raw)
                                    if v is not None:
                                        cur = v
                                        m.value = v
                        try:
                            self.tree.set(iid, "value", _fmt(cur))
                        except Exception:
                            pass
        except Exception:
            pass
        self.root.after(500, self._refresh_values_loop)

    def _ensure_freeze_thread(self):
        if self._freeze_thread and self._freeze_thread.is_alive():
            return
        self._freeze_stop.clear()
        self._freeze_thread = threading.Thread(target=self._freeze_loop, daemon=True)
        self._freeze_thread.start()

    def _freeze_loop(self):
        while not self._freeze_stop.is_set():
            if self.proc:
                for addr, info in list(self.frozen.items()):
                    dt = BY_NAME.get(info["type_name"])
                    if dt:
                        raw = dt.pack(info["value"])
                        if raw:
                            self.proc.write(addr, raw)
            self._freeze_stop.wait(0.05)

    # ------------------------------------------------------------------
    # Утилиты
    # ------------------------------------------------------------------

    def _clear_tree(self, tree: ttk.Treeview):
        for iid in tree.get_children():
            tree.delete(iid)

    def _set_status(self, msg):
        self.status_var.set(msg)


def _worker(fn, q):
    try:
        result = fn(on_progress=lambda d: q.put(("progress", d)))
        q.put(("done", result))
    except Exception as e:
        q.put(("error", repr(e)))


def _fmt(v) -> str:
    if v is None:
        return "—"
    if isinstance(v, float):
        if v == int(v) and abs(v) < 1e15:
            return f"{int(v)}"
        return f"{v:.4g}"
    return str(v)


def launch():
    root = tk.Tk()
    try:
        apply_theme(root)
        App(root)
        root.mainloop()
    except Exception:
        tb = traceback.format_exc()
        _log.exception("Критическая ошибка GUI:\n%s", tb)
        try:
            from crash_handler import show_crash_window
            show_crash_window(tb)
        except Exception:
            raise

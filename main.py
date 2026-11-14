"""
main.py
Точка входа программы GameCheat Scanner.

Запуск (из исходников, нужен Python 3.10+):
    python main.py

Сборка в .exe на Windows:
    build.bat   или   python build.py
(см. README.md)

При любом падении полный traceback пишется в gamecheat.log рядом с
программой и показывается в окне «Программа завершилась с ошибкой».
"""

import sys
import logging
from i18n import tr


def main():
    # Сначала настраиваем лог и перехват ошибок — чтобы любой сбой ниже
    # попал в gamecheat.log, а не «просто закрыл окно».
    from crash_handler import setup_logging, install_excepthooks
    log = setup_logging()
    install_excepthooks()

    try:
        from gui_app import launch
    except Exception as e:
        log.error("Не удалось импортировать gui_app:\n%s", traceback_str(e))
        print(tr("main_load_err"), e, file=sys.stderr)
        print(tr("main_pip_hint"), file=sys.stderr)
        print(tr("main_pip_cmd"), file=sys.stderr)
        print(tr("main_log_hint"), file=sys.stderr)
        sys.exit(1)

    launch()


def traceback_str(e) -> str:
    import traceback
    return "".join(traceback.format_exception(type(e), e, e.__traceback__))


if __name__ == "__main__":
    main()

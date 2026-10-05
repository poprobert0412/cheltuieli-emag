"""Configurează jurnalul (log) al unei sesiuni de rulare.

Primește: folderul `logs/`. Dă înapoi: calea fișierului de jurnal creat.
Scrie tot ce loghează aplicația de la INFO în sus, în `logs/<data>_<ora>.log`
și pe ecran. Nu are alt rol.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

LOG_FORMAT = "%(asctime)s [%(name)s] %(levelname)s: %(message)s"


def setup_logging(logs_dir: Path) -> Path:
    """Creează fișierul de jurnal al sesiunii și atașează handler-ele.

    Întoarce calea fișierului. Apelat o singură dată pe sesiune; handler-ele
    vechi sunt scoase ca să nu se dubleze mesajele la apeluri repetate (teste).
    """
    logs_dir.mkdir(parents=True, exist_ok=True)
    log_path = logs_dir / f"{datetime.now():%Y-%m-%d_%H-%M-%S}.log"

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    for handler in list(root.handlers):
        root.removeHandler(handler)

    formatter = logging.Formatter(LOG_FORMAT)
    file_handler = logging.FileHandler(log_path, encoding="utf-8")
    file_handler.setFormatter(formatter)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    root.addHandler(file_handler)
    root.addHandler(console_handler)
    return log_path

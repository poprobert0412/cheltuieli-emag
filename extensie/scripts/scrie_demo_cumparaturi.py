"""Exportă comenzile demonstrative pentru funcțiile extensiei care filtrează perioade.

Primește generatorul existent, fără date de cont, și o cale opțională de ieșire.
Scrie JSON determinist cu comenzi și retururi inventate; build-ul Node îl împachetează.
Nu recalculează raportul și nu modifică datele demonstrative comune.
"""

import json
from dataclasses import asdict
from pathlib import Path

from emag_spend import settings
from emag_spend.demo_data import demo_orders_and_returns

DEMO_SOURCE_FILE = settings.PROJECT_ROOT / "extensie" / "demo" / "shopping_source.json"


def expected_demo_source() -> str:
    """Întoarce JSON-ul comenzilor inventate din același generator ca demo-data.js."""
    orders, returns = demo_orders_and_returns()
    data = {"orders": [asdict(order) for order in orders], "returns": [asdict(ret) for ret in returns]}
    return json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n"


def write_demo_source(target: Path = DEMO_SOURCE_FILE) -> Path:
    """Scrie UTF-8 cu LF și întoarce calea; nu citește sau exportă datele utilizatorului."""
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(expected_demo_source().encode("utf-8"))
    return target


if __name__ == "__main__":
    print(write_demo_source())

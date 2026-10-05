"""Deschide raportul HTML în browserul implicit, pe orice sistem de operare.

Primește: calea unui fișier (de obicei raport.html). Dă înapoi: True dacă s-a cerut deschiderea,
False dacă fișierul lipsește sau sistemul nu are browser (apelantul spune atunci calea utilizatorului).
Folosește webbrowser cu o adresă file:// (merge pe Windows, macOS și Linux), nu os.startfile (doar Windows).
Nu generează raportul și nu pornește niciun server.
"""

import webbrowser
from pathlib import Path


def open_report(report_path: Path) -> bool:
    """Deschide `report_path` în browserul implicit; False dacă fișierul nu există sau nu se poate deschide.

    Adresa se construiește cu as_uri(), care codifică spațiile și diacriticele din cale.
    """
    path = Path(report_path).resolve()
    if not path.is_file():
        return False
    return webbrowser.open(path.as_uri())

"""Testele picate, ca adnotări GitHub: se văd pe pagina rulării și fără cont (jurnalele complete cer autentificare).

Primește: calea raportului JUnit scris de pytest (--junitxml). Dă: pe stdout, câte o comandă `::error title=…::…` pentru
fiecare test picat sau cu eroare (cel mult MAX_ANNOTATIONS), cu primele rânduri ale mesajului. Fără raport: o singură adnotare
care spune că pytest nu a ajuns să scrie raportul. Ce NU face: nu decide dacă jobul pică (o face pasul pytest).
"""

import sys
import xml.etree.ElementTree as ET
from pathlib import Path

MAX_ANNOTATIONS = 10  # GitHub arată cel mult 10 adnotări de eroare pe pas; restul ar fi aruncate oricum
MESSAGE_LINES = 8  # destule cât să se vadă aserțiunea și valorile ei, fără tot traceback-ul
MESSAGE_MAX_CHARS = 1500


def escape_data(text: str) -> str:
    """Textul unei comenzi de workflow (după „::”): %, CR și LF codate, cum cere GitHub."""
    return text.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def escape_property(text: str) -> str:
    """Valoarea unei proprietăți (title=…): în plus față de text, „:” și „,” codate."""
    return escape_data(text).replace(":", "%3A").replace(",", "%2C")


def annotations(report: Path) -> list[str]:
    """Comenzile `::error` pentru testele picate din raportul JUnit (cel mult MAX_ANNOTATIONS)."""
    if not report.is_file():
        return [f"::error::{escape_data(f'pytest nu a scris raportul {report.name}: s-a oprit înainte să ruleze testele')}"]
    found = []
    for case in ET.parse(report).getroot().iter("testcase"):
        problem = case.find("failure")
        if problem is None:
            problem = case.find("error")
        if problem is None:
            continue
        name = f"{case.get('classname', '')}::{case.get('name', '')}"
        detail = (problem.text or problem.get("message") or "").strip().splitlines()
        message = "\n".join([problem.get("message", "").strip(), *detail[-MESSAGE_LINES:]]).strip()[:MESSAGE_MAX_CHARS]
        found.append(f"::error title={escape_property(name)}::{escape_data(message or 'fără mesaj')}")
    return found[:MAX_ANNOTATIONS]


if __name__ == "__main__":
    for line in annotations(Path(sys.argv[1])):
        print(line)

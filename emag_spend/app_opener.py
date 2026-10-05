"""Deschide pagina aplicației locale în browserul implicit (și numai pe ea).

Primește: adresa paginii aplicației, cu tokenul în fragment (app_security.build_app_url). Dă înapoi: OpenResult(opened, reason);
`reason` spune în română de ce n-a mers (ca ruleaza.py să afișeze adresa și motivul). Refuză orice adresă care nu e exact
pagina aplicației pe bucla locală (http, 127.0.0.1, port, /aplicatie.html): un modul care deschide adrese oarecare ar fi o
ieșire spre internet. Raportul local îl deschide report_opener.py; aici nu se deschide niciun fișier.
Ce NU face: nu pornește serverul și nu scrie tokenul nicăieri (nici în jurnal).
"""

import webbrowser
from dataclasses import dataclass
from urllib.parse import urlsplit

from emag_spend import app_security


@dataclass(frozen=True)
class OpenResult:
    """Rezultatul încercării de a deschide browserul: reușit, sau motivul eșecului (în română)."""

    opened: bool
    reason: str = ""


def is_app_page_url(url: str) -> bool:
    """True doar pentru pagina aplicației pe bucla locală: http, gazda 127.0.0.1, port numeric, calea /aplicatie.html, fără parametri."""
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return (parts.scheme == app_security.HTTP_SCHEME and parts.hostname == app_security.PAGE_HOST and port is not None
            and parts.path == app_security.APP_PAGE_PATH and not parts.query and not parts.username and not parts.password)


def open_app_page(url: str) -> OpenResult:
    """Deschide `url` în browserul implicit dacă e pagina aplicației; altfel sau dacă sistemul nu poate, întoarce motivul."""
    if not is_app_page_url(url):
        return OpenResult(False, "adresa nu e pagina aplicației locale, așa că nu o deschid")
    try:
        opened = webbrowser.open(url)
    except webbrowser.Error as error:
        return OpenResult(False, f"browserul implicit nu a putut fi pornit ({error})")
    if not opened:
        return OpenResult(False, "sistemul nu are un browser implicit configurat")
    return OpenResult(True)

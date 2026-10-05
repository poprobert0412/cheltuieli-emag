"""Fișierele statice ale aplicației locale: lista albă din interfata/, construită o singură dată la pornire.

Primește: folderul interfata/. Dă înapoi (prin `StaticFiles.read`): conținutul și tipul unui fișier din lista albă, sau None.
Lista albă = aplicatie.html și DOAR fișierele pe care ea le cere (script, stil, imagine), citite din HTML-ul ei; dacă pagina încă nu
există, tiparele de rezervă (assets/app*.js|css, dashboard.*, site.css). Intră doar fișiere obișnuite (nu legături sau joncțiuni) care, după
`resolve`, sunt în interfata/. Cheile sunt adrese exacte (`/assets/app.js`): nicio cale nu se construiește din ce trimite browserul, deci `..`,
`%2e%2e`, `\\`, `//`, nume 8.3, `::$DATA` și majusculele nu ajung la disc; fără foldere listate, fără demo-data.js decât dacă pagina îl cere.
Ce NU face: nu servește API-ul și nu scrie nimic."""

import os
import posixpath
import stat
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import urlsplit

from emag_spend import app_security

APP_PAGE_NAME = app_security.APP_PAGE_PATH.lstrip("/")
# Tipul de conținut după extensie: html, css, js (cerute de pagină) și imagini mici (pictogramă). Orice altă extensie nu se servește.
CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".ico": "image/x-icon",
    ".webp": "image/webp",
}
# Tiparele de rezervă, relative la interfata/, folosite doar cât aplicatie.html nu există: ce are nevoie aplicația
# (scripturile și stilurile ei, componenta de raport și stilul comun), nimic din site-ul explicativ.
FALLBACK_PATTERNS = ("assets/app*.js", "assets/app*.css", "assets/dashboard.*", "assets/site.css")
# Un fișier static mai mare decât atât nu e o pagină scrisă de om (cele reale au zeci de KB); 8 MiB oprește umflarea memoriei.
MAX_STATIC_BYTES = 8 * 1024 * 1024
# Etichetele și atributele din care pagina cere alte fișiere.
_REFERENCE_ATTRIBUTES = {"script": "src", "link": "href", "img": "src"}


@dataclass(frozen=True)
class StaticFile:
    """Un fișier din lista albă: calea lui reală (rezolvată) și tipul de conținut."""

    path: Path
    content_type: str


def _is_link_like(path: Path) -> bool:
    """True pentru legături simbolice și joncțiuni Windows (orice reparse point); nu ridică excepții."""
    try:
        info = os.lstat(path)
    except OSError:
        return False
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT)


class _ReferenceCollector(HTMLParser):
    """Strânge adresele cerute de o pagină HTML prin <script src>, <link href> și <img src>."""

    def __init__(self):
        """Pornește cu lista goală de referințe."""
        super().__init__(convert_charrefs=True)
        self.references: list[str] = []

    def handle_starttag(self, tag, attrs):
        """Reține atributul-țintă al etichetei, dacă are valoare."""
        wanted = _REFERENCE_ATTRIBUTES.get(tag.lower())
        for name, value in attrs:
            if wanted and name.lower() == wanted and value:
                self.references.append(value)

    handle_startendtag = handle_starttag


def _local_reference_to_url_path(reference: str) -> str | None:
    """Adresa `/cale/fisier.ext` pentru o referință locală din pagină; None pentru adrese externe, cu `..` sau cu caractere neobișnuite.

    Referințele către altă gazdă (https://..., //...), data: și cele cu % sau \\ nu intră în lista albă: ar însemna alt fișier decât cel scris.
    """
    text = reference.strip().split("#", 1)[0].split("?", 1)[0]
    parts = urlsplit(text)
    if not text or parts.scheme or parts.netloc or "%" in text or "\\" in text:
        return None
    normalized = posixpath.normpath("/" + text.lstrip("/"))
    if not app_security.is_plain_request_path(normalized) or normalized == "/":
        return None
    return normalized


def _admit(interface_root: Path, url_path: str) -> StaticFile | None:
    """Intrarea din lista albă pentru `url_path`, dacă fișierul există, e obișnuit (nu legătură), e în interfata/ și are o extensie servită."""
    content_type = CONTENT_TYPES.get(posixpath.splitext(url_path)[1])
    candidate = interface_root / url_path.lstrip("/")
    if content_type is None or _is_link_like(candidate):
        return None
    try:
        info = os.lstat(candidate)
        resolved = candidate.resolve(strict=True)
    except (OSError, RuntimeError):
        return None
    if not stat.S_ISREG(info.st_mode) or interface_root not in resolved.parents:
        return None
    return StaticFile(resolved, content_type)


def build_whitelist(interface_dir: Path) -> dict[str, StaticFile]:
    """Lista albă `{adresă: StaticFile}` pentru folderul interfata/ (vezi antetul modulului pentru reguli)."""
    try:
        root = Path(interface_dir).resolve()
    except (OSError, RuntimeError):
        return {}
    page = _admit(root, "/" + APP_PAGE_NAME)
    urls: list[str] = []
    if page is not None:
        collector = _ReferenceCollector()
        try:
            collector.feed(page.path.read_text(encoding="utf-8"))
            collector.close()
        except (OSError, UnicodeDecodeError):
            return {}
        urls = [url for url in (_local_reference_to_url_path(ref) for ref in collector.references) if url]
    else:
        for pattern in FALLBACK_PATTERNS:
            urls.extend("/" + found.relative_to(root).as_posix() for found in sorted(root.glob(pattern)))
    whitelist: dict[str, StaticFile] = {}
    for url in ["/" + APP_PAGE_NAME, *urls]:
        entry = _admit(root, url)
        if entry is not None:
            whitelist[url] = entry
    return whitelist


class StaticFiles:
    """Lista albă a fișierelor statice, construită la creare; `read` e tot ce are nevoie serverul."""

    def __init__(self, interface_dir: Path):
        """Construiește lista albă din `interface_dir` (o singură dată: o modificare ulterioară cere repornirea aplicației)."""
        self._files = build_whitelist(interface_dir)

    @property
    def urls(self) -> frozenset[str]:
        """Adresele servite (pentru teste și jurnal)."""
        return frozenset(self._files)

    def read(self, url_path: str) -> tuple[bytes, str] | None:
        """(conținut, tip) pentru adresa EXACTĂ din lista albă, sau None (necunoscută, schimbată în legătură între timp, prea mare)."""
        entry = self._files.get(url_path)
        if entry is None or _is_link_like(entry.path):
            return None
        try:
            with open(entry.path, "rb") as handle:
                data = handle.read(MAX_STATIC_BYTES + 1)
        except OSError:
            return None
        if len(data) > MAX_STATIC_BYTES:
            return None
        return data, entry.content_type

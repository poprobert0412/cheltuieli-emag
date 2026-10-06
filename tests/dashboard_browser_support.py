"""Ajutoare pentru testele care deschid componenta dashboard într-un browser real.

Primește: dicționare de date și calea unui folder temporar. Dă înapoi: o pagină
„harness” (HTML minim care încarcă dashboard.css și dashboard.js din proiect prin
file://), un browser Playwright (Edge sau Chrome instalat) și o sondă care adună
erorile din consolă și cererile de rețea.
Mai dă și datele demonstrative reale ale site-ului (`assets/demo-data.js`), citite din fișier, ca testele noilor funcții
(linkuri, avertismente pe grupe, prețuri) să verifice și datele generate de program, nu doar fixturile inventate.
Ce NU face: nu conține teste. Dacă niciun browser nu pornește, testele se sar
(pytest.skip), ca suita să rămână verde pe orice PC.
"""

import json
from dataclasses import dataclass, field
from pathlib import Path

from emag_spend import settings

LOCAL_SCHEMES = ("file:", "data:", "blob:", "about:")
DEMO_DATA_PREFIX = "window.EMAG_DEMO_DATA = "
BROWSER_CHANNELS = tuple(c for c in (settings.BROWSER_CHANNEL, "msedge", "chrome") if c)  # gol = automat: Edge, apoi Chrome


@dataclass
class Probe:
    """Ce a văzut pagina: erori de consolă, excepții necaptate și cereri care ies din fișierele locale."""

    console_errors: list = field(default_factory=list)
    page_errors: list = field(default_factory=list)
    external_requests: list = field(default_factory=list)

    def problems(self) -> dict:
        """Tot ce ar trebui să fie gol pentru ca pagina să fie curată."""
        return {"console": self.console_errors, "pageerror": self.page_errors, "network": self.external_requests}


def read_demo_file_data() -> dict | None:
    """Conținutul lui `interfata/assets/demo-data.js` ca dicționar, sau None dacă fișierul lipsește (testul se sare atunci)."""
    demo_file = settings.PROJECT_ROOT / "interfata" / "assets" / "demo-data.js"
    if not demo_file.is_file():
        return None
    text = demo_file.read_text(encoding="utf-8")
    assert text.startswith(DEMO_DATA_PREFIX), "demo-data.js nu începe cu window.EMAG_DEMO_DATA = "
    return json.loads(text[len(DEMO_DATA_PREFIX):text.rstrip().rindex(";")])  # json.loads înțelege și „<\/”


def launch_browser(playwright):
    """Pornește primul browser instalat din BROWSER_CHANNELS; ridică RuntimeError dacă niciunul nu pornește."""
    errors = []
    for channel in dict.fromkeys(BROWSER_CHANNELS):
        try:
            return playwright.chromium.launch(channel=channel)
        except Exception as exc:  # Playwright ridică Error generic dacă browserul lipsește
            errors.append(f"{channel}: {str(exc).splitlines()[0]}")
    raise RuntimeError("niciun browser nu a pornit (" + "; ".join(errors) + ")")


def attach_probe(page) -> Probe:
    """Atașează ascultători care completează o `Probe` cât timp pagina trăiește."""
    probe = Probe()
    page.on("console", lambda msg: probe.console_errors.append(msg.text) if msg.type in ("error", "warning") else None)
    page.on("pageerror", lambda exc: probe.page_errors.append(str(exc)))
    page.on("request", lambda req: probe.external_requests.append(req.url) if not req.url.startswith(LOCAL_SCHEMES) else None)
    return probe


def embed_json(data) -> str:
    """JSON sigur de pus într-un <script>: toate „<” devin \\u003c."""
    return json.dumps(data, ensure_ascii=False).replace("<", "\\u003c")


def write_harness(folder: Path, datasets: dict, roots: tuple[str, ...] = ("a", "b"), html_attrs: str = "", wrapper_style: str = "") -> Path:
    """Scrie harness.html în `folder`; datele sunt în `window.DATA[<nume>]`, rădăcinile sunt <div id="a"> etc.

    Datele trec prin JSON.parse, ca în aplicație: un literal de obiect ar transforma cheia „__proto__”
    în prototip, în timp ce JSON.parse o face proprietate proprie (cazul real al unui fișier încărcat).

    Încarcă designul direct din interfata/assets/ (aceleași fișiere ca raportul și site-ul).
    `html_attrs` se pune pe <html> (ex. 'data-theme="dark"'); `wrapper_style` pe un <div> în jurul rădăcinilor.
    """
    css = settings.DASHBOARD_CSS_FILE.as_uri()
    js = settings.DASHBOARD_JS_FILE.as_uri()
    divs = "".join(f'<div id="{name}"></div>' for name in roots)
    page = (
        f'<!doctype html><html lang="ro" {html_attrs}><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1">'
        f'<link rel="stylesheet" href="{css}"><script src="{js}"></script></head>'
        f'<body style="margin:0"><div id="wrapper" style="{wrapper_style}">{divs}</div>'
        f"<script>window.DATA = JSON.parse({embed_json(json.dumps(datasets, ensure_ascii=False))});</script></body></html>"
    )
    path = folder / "harness.html"
    path.write_text(page, encoding="utf-8")
    return path

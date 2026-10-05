"""Generează raportul HTML dintr-un șablon-schelet, designul și datele analizei.

Primește: calea fișierului de ieșire, șablonul HTML, dicționarul `summary` și,
opțional, fișierele de design (CSS și JS al componentei din `interfata/assets/`).
Dă înapoi: nimic (scrie fișierul). Raportul e UN SINGUR fișier HTML autonom:
designul și datele sunt lipite inline, graficele se desenează în browser, fără
internet. Designul însuși stă în `interfata/assets/dashboard.{css,js}` (aceeași
sursă ca site-ul), nu aici și nu în șablon.
Ce NU face: nu validează `summary` (o face componenta din browser) și nu
modifică nimic din șablon în afară de cele trei locuri marcate.
"""

import json
from pathlib import Path

from emag_spend import settings

_CSS_PLACEHOLDER = "/*__DASHBOARD_CSS__*/"
_JS_PLACEHOLDER = "/*__DASHBOARD_JS__*/"
_DATA_PLACEHOLDER = "/*__DATE_ANALIZA__*/null"

# Secvențe care, într-un <script> sau <style> inline, ar putea închide sau
# deruta parserul HTML. Nu le rescriem în tăcere: designul nostru nu le are,
# iar dacă apar, cineva trebuie să afle (un test verifică și el).
_FORBIDDEN_IN_INLINE_JS = ("</script", "<!--")
_FORBIDDEN_IN_INLINE_CSS = ("</style", "<!--")


def _fill(template: str, placeholder: str, value: str, template_path: Path) -> str:
    """Înlocuiește `placeholder` (care trebuie să apară exact o dată) cu `value`."""
    found = template.count(placeholder)
    if found != 1:
        raise ValueError(
            f"șablonul {template_path} trebuie să conțină {placeholder} exact o dată (am găsit {found})"
        )
    return template.replace(placeholder, value)


def _read_inline_asset(path: Path, forbidden: tuple[str, ...], kind: str) -> str:
    """Citește un fișier de design și refuză conținutul care ar rupe tag-ul inline."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ValueError(f"fișierul de design {kind} lipsește: {path}") from None
    lowered = text.lower()
    for marker in forbidden:
        if marker in lowered:
            raise ValueError(f"{path} conține „{marker}” și nu poate fi lipit inline în raport")
    return text


def write_report(
    output_path: Path,
    template_path: Path,
    summary: dict,
    css_path: Path | None = None,
    js_path: Path | None = None,
) -> None:
    """Scrie raportul autonom; ridică ValueError dacă șablonul sau fișierele de design nu se potrivesc.

    `css_path` / `js_path` sunt implicit `settings.DASHBOARD_CSS_FILE` / `DASHBOARD_JS_FILE`,
    citite la fiecare apel (un test le poate schimba). Fișierul se scrie cu sfârșit de rând `\\n`.
    """
    template = Path(template_path).read_text(encoding="utf-8")
    css = _read_inline_asset(css_path or settings.DASHBOARD_CSS_FILE, _FORBIDDEN_IN_INLINE_CSS, "CSS")
    js = _read_inline_asset(js_path or settings.DASHBOARD_JS_FILE, _FORBIDDEN_IN_INLINE_JS, "JS")
    # Toate "<" din date devin < (escape valid în JSON): un nume de produs nu
    # poate închide <script> ("</script>") și nici deschide "<!--<script>", care
    # ar face parserul să ignore </script>-ul real. json.loads dă înapoi textul original.
    data = json.dumps(summary, ensure_ascii=False).replace("<", "\\u003c")
    # Datele se pun ULTIMELE: un placeholder scris într-un nume de produs nu mai are ce înlocui.
    html = _fill(template, _CSS_PLACEHOLDER, css, template_path)
    html = _fill(html, _JS_PLACEHOLDER, js, template_path)
    html = _fill(html, _DATA_PLACEHOLDER, data, template_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(html.encode("utf-8"))

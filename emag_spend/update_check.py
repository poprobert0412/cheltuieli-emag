"""Verifică dacă pe GitHub e publicată o versiune nouă a programului (decis 5 oct. 2026, D2, D4, D6, D20).

Primește: funcția care citește JSON (implicit update_http.get_json; testele dau una falsă) și, opțional, `enabled`
(None = se citește EMAG_UPDATE_CHECK prin settings.update_check_enabled()).
Dă înapoi: UpdateCheck — starea ("dezactivat" | "eroare" | "la-zi" | "noua"), versiunile, „Ce e nou” (text simplu),
pagina lansării și, doar pentru o versiune nouă, activele de descărcat (ReleaseAssets), cu nume și adrese validate strict.
Nu ridică niciodată excepții. Ce NU face: nu descarcă (update_download.py) și nu instalează nimic (update_apply.py).
"""

import logging
import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime

from emag_spend import settings, update_http
from emag_spend.update_errors import UpdateError
from emag_spend.version import VERSION, is_newer, parse_version

logger = logging.getLogger(__name__)

# Adresele, ca șabloane completate cu settings.UPDATE_REPOSITORY (un fork își schimbă depozitul doar acolo).
LATEST_RELEASE_API_URL = "https://api.github.com/repos/{repository}/releases/latest"
RELEASE_PAGE_PREFIX = "https://github.com/{repository}/releases/"
RELEASES_PAGE_URL = "https://github.com/{repository}/releases/latest"
ASSET_URL_PREFIX = "https://github.com/{repository}/releases/download/{tag}/"
# Numele activelor, exact cum le face .github/workflows/lansare.yml.
ZIP_NAME_TEMPLATE = "cheltuieli-emag-{tag}.zip"
SUMS_NAME = "SHA256SUMS.txt"
TAG_PREFIX = "v"
# Primul caracter de după TAG_PREFIX: doar o cifră ASCII (set de caractere, ca „” să nu fie găsit ca subșir gol).
_ASCII_DIGITS = frozenset("0123456789")
# Răspunsul API pentru o lansare are câțiva KB (lista activelor și notele); 1 MB e o marjă mare care oprește totuși un răspuns absurd.
MAX_RELEASE_JSON_BYTES = 1_000_000
# Verificarea rulează în fundal la pornirea aplicației: 15 s ajung pentru o cerere mică și nu țin un fir agățat la nesfârșit.
CHECK_TIMEOUT_SECONDS = 15.0
# „Ce e nou” (D20): secțiunea de sub primul titlu „## Ce e nou”, până la următorul „## ”; fără titlu, primele rânduri.
NOTES_HEADING = "## ce e nou"  # comparat fără litere mari/mici
NEXT_SECTION_PREFIX = "## "
NOTES_FALLBACK_LINES = 20
# O bandă în aplicație, nu un document: 4000 de caractere încap într-o pagină de note și opresc un corp uriaș.
MAX_NOTES_CHARS = 4000
NOTES_CUT_MARK = "…"
# Activul e gata de descărcat doar în starea „uploaded” (în „open” încă se încarcă).
UPLOADED_STATE = "uploaded"
# Data publicării: un șir ISO scurt; ce nu se parsează (sau e absurd de lung) se ignoră, nu e o eroare.
MAX_DATE_CHARS = 40

STATUS_DISABLED = "dezactivat"
STATUS_ERROR = "eroare"
STATUS_UP_TO_DATE = "la-zi"
STATUS_NEW = "noua"

MESSAGE_DISABLED = "Verificarea automată a versiunii noi e oprită (EMAG_UPDATE_CHECK=0)."
MESSAGE_NEW = "Versiune nouă: {latest} (ai {current})."
MESSAGE_UP_TO_DATE = "Ai ultima versiune ({current})."
MESSAGE_AHEAD = "Ai o versiune mai nouă ({current}) decât ultima lansare publicată ({latest})."
MESSAGE_BAD_REPOSITORY = "Depozitul actualizărilor din settings.py nu e de forma proprietar/nume; verificarea s-a oprit."
MESSAGE_BAD_RELEASE = "Lansarea de pe GitHub are date neașteptate ({detail}); din siguranță, nu o folosesc."
MESSAGE_UNEXPECTED = "Verificarea versiunii noi a eșuat neașteptat; detaliile sunt în jurnal."

# Proprietar GitHub (litere, cifre, cratimă) și numele depozitului (litere, cifre, punct, cratimă, linie jos), fără „.” sau „..”.
_REPOSITORY = re.compile(r"[A-Za-z0-9][A-Za-z0-9-]{0,38}/(?!\.{1,2}\Z)[A-Za-z0-9._-]{1,100}")
_DIGEST = re.compile(r"sha256:([0-9a-fA-F]{64})")
# Caractere care nu au ce căuta în textul notelor: cele de control (categoria Unicode „Cc”, în afară de rând nou și TAB) și
# marcajele de direcție (bidi), enumerate unul câte unul: fără intervale de coduri într-o expresie regulată (CodeQL #7).
_KEPT_CONTROL_CHARACTERS = frozenset("\n\t")
_BIDI_MARKS = frozenset("\u061c\u200e\u200f\u202a\u202b\u202c\u202d\u202e\u2066\u2067\u2068\u2069")


def _without_hidden_characters(text: str) -> str:
    """Textul fără caractere de control (în afară de rând nou și TAB) și fără marcaje de direcție (bidi)."""
    return "".join(char for char in text
                   if char in _KEPT_CONTROL_CHARACTERS or (unicodedata.category(char) != "Cc" and char not in _BIDI_MARKS))


@dataclass(frozen=True)
class ReleaseAssets:
    """Activele unei lansări noi, validate: eticheta, versiunea, arhiva (nume, adresă, mărime, digest opțional) și SHA256SUMS.txt."""

    tag: str
    version: str
    zip_name: str
    zip_url: str
    zip_size: int
    zip_digest: str | None  # „sha256:<64 hex, litere mici>” dacă API-ul l-a dat, altfel None
    sums_url: str


@dataclass(frozen=True)
class UpdateCheck:
    """Rezultatul verificării, gata de arătat: starea, versiunile, notele, pagina lansării, activele (doar la „noua”) și o frază."""

    status: str  # "dezactivat" | "eroare" | "la-zi" | "noua"
    current: str
    latest: str | None
    notes: str  # „Ce e nou”, text simplu
    published: str | None  # data ISO din API
    page_url: str | None  # doar https://github.com/{repo}/releases/...
    release: ReleaseAssets | None
    message: str  # o frază pentru utilizator


def release_notes(body: object) -> str:
    """„Ce e nou” din corpul lansării (D20), ca text simplu curățat de caractere ascunse și tăiat la MAX_NOTES_CHARS; "" dacă nu e text."""
    if not isinstance(body, str):
        return ""
    lines = _without_hidden_characters(body.replace("\r\n", "\n").replace("\r", "\n")).split("\n")
    start = next((index for index, line in enumerate(lines) if line.strip().casefold().startswith(NOTES_HEADING)), None)
    if start is None:
        selected = lines[:NOTES_FALLBACK_LINES]
    else:
        selected = []
        for line in lines[start + 1:]:
            if line.lstrip().startswith(NEXT_SECTION_PREFIX):
                break
            selected.append(line)
    notes = "\n".join(selected).strip()
    if len(notes) > MAX_NOTES_CHARS:
        notes = notes[:MAX_NOTES_CHARS - len(NOTES_CUT_MARK)].rstrip() + NOTES_CUT_MARK
    return notes


def _bad(detail: str) -> UpdateError:
    """UpdateError pentru o lansare cu date neașteptate; `detail` spune, în română, ce anume."""
    return UpdateError(MESSAGE_BAD_RELEASE.format(detail=detail))


def _has_prefix(url: str, prefix: str) -> bool:
    """True dacă `url` începe cu `prefix`, fără să conteze literele mari/mici (GitHub nu le deosebește în proprietar și depozit)."""
    return url[:len(prefix)].casefold() == prefix.casefold()


def _published(value: object) -> str | None:
    """Data publicării, dacă e un șir ISO valid și scurt; altfel None (nu e motiv de eroare)."""
    if not isinstance(value, str) or len(value) > MAX_DATE_CHARS:
        return None
    try:
        datetime.fromisoformat(value)
    except ValueError:
        return None
    return value


def _page_url(data: dict, repository: str) -> str:
    """html_url al lansării, doar dacă e https://github.com/{repo}/releases/...; altfel UpdateError."""
    url = data.get("html_url")
    prefix = RELEASE_PAGE_PREFIX.format(repository=repository)
    if not (isinstance(url, str) and update_http.is_allowed_url(url) and _has_prefix(url, prefix) and len(url) > len(prefix)):
        raise _bad("pagina lansării nu e în depozitul programului")
    return url


def is_release_tag(tag: object) -> bool:
    """True doar pentru eticheta exactă „v” + X.Y.Z (D1; decis 6 oct. 2026, N10): un singur „v” mic, urmat direct de o cifră ASCII.

    Capcana: parse_version acceptă și un „v” în față, deci „începe cu v și restul se parsează” ar lua „vv1.2.3” drept „v1.2.3”.
    """
    if not isinstance(tag, str) or not tag.startswith(TAG_PREFIX):
        return False
    bare = tag[len(TAG_PREFIX):]
    return bare[:1] in _ASCII_DIGITS and parse_version(bare) is not None


def _tag(data: dict) -> str:
    """Eticheta lansării, exact „vX.Y.Z” (is_release_tag); altfel UpdateError."""
    tag = data.get("tag_name")
    if not is_release_tag(tag):
        raise _bad("eticheta nu e de forma vX.Y.Z")
    return tag


def _single_asset(assets: list, name: str, repository: str, tag: str) -> dict:
    """Activul cu numele EXACT `name` (unul singur), cu adresa EXACT .../releases/download/{tag}/{name} și încărcat complet."""
    matches = [asset for asset in assets if isinstance(asset, dict) and asset.get("name") == name]
    if len(matches) != 1:
        raise _bad(f"lansarea trebuie să aibă exact un fișier {name}, are {len(matches)}")
    asset = matches[0]
    url = asset.get("browser_download_url")
    prefix = ASSET_URL_PREFIX.format(repository=repository, tag=tag)
    if not (isinstance(url, str) and update_http.is_allowed_url(url) and _has_prefix(url, prefix) and url[len(prefix):] == name):
        raise _bad(f"adresa lui {name} nu e din lansarea {tag} a depozitului programului")
    if "state" in asset and asset["state"] != UPLOADED_STATE:
        raise _bad(f"{name} încă se încarcă pe GitHub")
    size = asset.get("size")
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise _bad(f"mărimea lui {name} lipsește sau e greșită")
    return asset


def _digest(asset: dict) -> str | None:
    """Digest-ul arhivei din API normalizat la „sha256:<hex mic>”; None dacă lipsește; UpdateError dacă are altă formă."""
    value = asset.get("digest")
    if value is None:
        return None
    match = _DIGEST.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        raise _bad("amprenta (digest) arhivei nu e de forma sha256:<64 de cifre hexazecimale>")
    return "sha256:" + match.group(1).lower()


def release_assets(data: dict, repository: str, tag: str) -> ReleaseAssets:
    """Activele validate ale lansării `tag` (arhiva cheltuieli-emag-{tag}.zip și SHA256SUMS.txt); ridică UpdateError."""
    assets = data.get("assets")
    if not isinstance(assets, list):
        raise _bad("lista fișierelor lansării lipsește")
    zip_name = ZIP_NAME_TEMPLATE.format(tag=tag)
    archive = _single_asset(assets, zip_name, repository, tag)
    sums = _single_asset(assets, SUMS_NAME, repository, tag)
    return ReleaseAssets(tag=tag, version=tag[len(TAG_PREFIX):], zip_name=zip_name, zip_url=archive["browser_download_url"],
                         zip_size=archive["size"], zip_digest=_digest(archive), sums_url=sums["browser_download_url"])


def _failure(message: str, repository: str | None) -> UpdateCheck:
    """UpdateCheck „eroare” cu mesajul dat și, dacă depozitul e valid, linkul spre pagina lansărilor (verificare manuală)."""
    page = RELEASES_PAGE_URL.format(repository=repository) if repository else None
    return UpdateCheck(STATUS_ERROR, VERSION, None, "", None, page, None, message)


def _from_release(data: object, repository: str) -> UpdateCheck:
    """Rezultatul pentru JSON-ul unei lansări: „la-zi” sau „noua” (cu active validate); ridică UpdateError la date neașteptate."""
    if not isinstance(data, dict):
        raise _bad("răspunsul nu descrie o lansare")
    if data.get("draft") is True or data.get("prerelease") is True:
        raise _bad("lansarea e marcată ca ciornă sau de test")
    tag = _tag(data)
    page = _page_url(data, repository)
    latest = tag[len(TAG_PREFIX):]
    notes, published = release_notes(data.get("body")), _published(data.get("published_at"))
    if not is_newer(latest, VERSION):
        message = MESSAGE_AHEAD if is_newer(VERSION, latest) else MESSAGE_UP_TO_DATE
        return UpdateCheck(STATUS_UP_TO_DATE, VERSION, latest, notes, published, page, None, message.format(current=VERSION, latest=latest))
    assets = release_assets(data, repository, tag)
    return UpdateCheck(STATUS_NEW, VERSION, latest, notes, published, page, assets, MESSAGE_NEW.format(latest=latest, current=VERSION))


def _check(get_json, enabled: bool | None) -> UpdateCheck:
    """Corpul verificării; erorile așteptate (rețea, date) devin „eroare”, cele neașteptate le prinde check_for_update."""
    if enabled is None:
        enabled = settings.update_check_enabled()
    repository = settings.UPDATE_REPOSITORY
    valid_repository = isinstance(repository, str) and _REPOSITORY.fullmatch(repository) is not None
    if not enabled:
        page = RELEASES_PAGE_URL.format(repository=repository) if valid_repository else None
        return UpdateCheck(STATUS_DISABLED, VERSION, None, "", None, page, None, MESSAGE_DISABLED)
    if not valid_repository:
        return _failure(MESSAGE_BAD_REPOSITORY, None)
    try:
        data = get_json(LATEST_RELEASE_API_URL.format(repository=repository), max_bytes=MAX_RELEASE_JSON_BYTES, timeout=CHECK_TIMEOUT_SECONDS)
        return _from_release(data, repository)
    except UpdateError as error:
        return _failure(str(error), repository)


def check_for_update(*, get_json=update_http.get_json, enabled: bool | None = None) -> UpdateCheck:
    """Verifică ultima lansare publicată și întoarce UpdateCheck; nu ridică niciodată (o eroare neașteptată devine „eroare”, cu jurnal)."""
    try:
        result = _check(get_json, enabled)
    except Exception:  # plasă de siguranță: verificarea rulează în fundal și nu are voie să oprească aplicația
        logger.exception("Verificarea versiunii noi a eșuat neașteptat")
        result = _failure(MESSAGE_UNEXPECTED, None)
    logger.info("Verificarea versiunii noi: %s (curentă %s, ultima %s)", result.status, result.current, result.latest or "necunoscută")
    return result

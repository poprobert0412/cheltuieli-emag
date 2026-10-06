"""Descarcă și verifică arhiva unei versiuni noi (decis 5 oct. 2026, D6).

Primește: activele validate ale lansării (ReleaseAssets, din update_check.py), folderul descărcării și, pentru teste, funcția
de descărcare (implicit update_http.download_to). Dă înapoi: calea arhivei verificate.
Verifică: mărimea anunțată de API (cel mult MAX_ZIP_BYTES) == octeții primiți; SHA-256 al arhivei == cel din SHA256SUMS.txt
al aceleiași lansări (parsat strict) și == digest-ul din API, dacă există. Arhiva greșită se șterge; SHA256SUMS.txt nu rămâne.
Folderul descărcării (decis 6 oct. 2026, N9, P7, P8): `download_folder(settings.UPDATE_DOWNLOAD_DIR)` refuză un .actualizare sau un
descarcari care e legătură, șterge descărcările lăsate de un proces omorât (mai vechi de update_recovery.STALE_DOWNLOAD_SECONDS), dă
fiecărei descărcări un subfolder nou și unic și îl șterge la final, oricum s-ar fi terminat (aplicația și `ruleaza.py --actualizeaza`
nu-și ating arhivele). Ce NU face: nu deschide arhiva și nu verifică VERSION din ea (update_apply.py).
"""

import hashlib
import hmac
import logging
import os
import re
import tempfile
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from emag_spend import update_http, update_recovery
from emag_spend.update_check import SUMS_NAME, TAG_PREFIX, ZIP_NAME_TEMPLATE, ReleaseAssets, is_release_tag
from emag_spend.update_errors import UpdateError
from emag_spend.update_recovery import DOWNLOAD_FOLDER_PREFIX, MESSAGE_LINKED_WORK_DIR, is_link

logger = logging.getLogger(__name__)

# Arhiva programului (cod, interfață, documentație) are câțiva MB; 100 MB e o marjă imensă care oprește totuși o arhivă absurdă.
MAX_ZIP_BYTES = 100 * 1024 * 1024
# SHA256SUMS.txt are un rând (~100 de octeți); 64 KiB acoperă orice listă rezonabilă de amprente.
MAX_SUMS_BYTES = 64 * 1024
# Cât se așteaptă conectarea sau următorul bloc de date (nu tot transferul): 60 s trec peste o rețea lentă, nu peste una căzută.
DOWNLOAD_TIMEOUT_SECONDS = 60.0
# Citirea arhivei pentru amprentă, pe bucăți de 1 MiB: memorie mică, viteză bună.
HASH_CHUNK_BYTES = 1024 * 1024
STAGE_DOWNLOAD = "descarc"
STAGE_VERIFY = "verific"
DIGEST_PREFIX = "sha256:"
# DOWNLOAD_FOLDER_PREFIX (începutul numelui subfolderului unei descărcări) vine din update_recovery.py: curățenia de acolo îl folosește.

# Un rând din SHA256SUMS.txt, cum îl scrie `sha256sum`: 64 de cifre hex, apoi două spații (text) sau spațiu și „*” (binar),
# apoi numele fișierului, fără spații, separatori de cale sau caractere de control.
_SUMS_LINE = re.compile(r"([0-9a-fA-F]{64})(?:  | \*)([^\x00-\x20\x7f/\\]+)")
_NORMALIZED_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")

MESSAGE_BAD_RELEASE = "Datele versiunii noi sunt incomplete sau greșite ({detail}); nu descarc nimic."
MESSAGE_TOO_BIG = f"Arhiva versiunii noi e mai mare decât limita de {MAX_ZIP_BYTES} octeți; din siguranță, nu o descarc."
MESSAGE_WORK_DIR = "Nu pot crea folderul de lucru al actualizării ({detail})."
MESSAGE_BAD_SUMS = "Fișierul cu amprente (SHA256SUMS.txt) al lansării e greșit ({detail}); din siguranță, nu continui."
MESSAGE_SIZE_MISMATCH = "Arhiva descărcată are {received} octeți, dar GitHub anunța {expected}; am șters-o."
MESSAGE_WRONG_HASH = "Amprenta arhivei descărcate nu se potrivește cu SHA256SUMS.txt al lansării; am șters-o, nimic nu s-a instalat."
MESSAGE_WRONG_DIGEST = "Amprenta arhivei descărcate nu se potrivește cu cea anunțată de GitHub; am șters-o, nimic nu s-a instalat."
MESSAGE_READ_FAILED = "Nu pot citi arhiva descărcată ({detail})."


def _validate(release: ReleaseAssets) -> None:
    """Verifică din nou, înainte de orice cerere, ce vine din update_check: etichetă, nume, mărime, digest și adrese."""
    if not isinstance(release, ReleaseAssets):
        raise UpdateError(MESSAGE_BAD_RELEASE.format(detail="lipsesc activele lansării"))
    tag = release.tag
    if not (is_release_tag(tag) and release.version == tag[len(TAG_PREFIX):]):  # exact „v” + X.Y.Z (N10), nu „vv1.2.3”
        raise UpdateError(MESSAGE_BAD_RELEASE.format(detail="eticheta nu e de forma vX.Y.Z"))
    if release.zip_name != ZIP_NAME_TEMPLATE.format(tag=tag):  # numele devine cale pe disc: doar cel așteptat, fără „/” sau „..”
        raise UpdateError(MESSAGE_BAD_RELEASE.format(detail="numele arhivei"))
    size = release.zip_size
    if not isinstance(size, int) or isinstance(size, bool) or size <= 0:
        raise UpdateError(MESSAGE_BAD_RELEASE.format(detail="mărimea arhivei"))
    if size > MAX_ZIP_BYTES:
        raise UpdateError(MESSAGE_TOO_BIG)
    if release.zip_digest is not None and not (isinstance(release.zip_digest, str) and _NORMALIZED_DIGEST.fullmatch(release.zip_digest)):
        raise UpdateError(MESSAGE_BAD_RELEASE.format(detail="amprenta anunțată de GitHub"))
    if not (update_http.is_allowed_url(release.zip_url) and update_http.is_allowed_url(release.sums_url)):
        raise UpdateError(MESSAGE_BAD_RELEASE.format(detail="adresele de descărcare"))


def expected_sha256(sums_text: str, file_name: str) -> str:
    """Amprenta (hex, litere mici) a lui `file_name` din textul unui SHA256SUMS.txt, parsat strict; ridică UpdateError.

    Orice rând negol care nu are forma `sha256sum` face tot fișierul invalid; numele trebuie să apară exact o dată.
    """
    found = []
    for line in sums_text.split("\n"):
        line = line.removesuffix("\r")
        if not line:
            continue
        match = _SUMS_LINE.fullmatch(line)
        if match is None:
            raise UpdateError(MESSAGE_BAD_SUMS.format(detail="un rând nu are forma «amprentă  nume»"))
        if match.group(2) == file_name:
            found.append(match.group(1).lower())
    if len(found) != 1:
        raise UpdateError(MESSAGE_BAD_SUMS.format(detail=f"arhiva {file_name} apare de {len(found)} ori, nu o dată"))
    return found[0]


def _read_sums(path: Path, file_name: str) -> str:
    """Citește SHA256SUMS.txt descărcat (UTF-8 strict) și întoarce amprenta arhivei; ridică UpdateError."""
    try:
        text = path.read_bytes().decode("utf-8")
    except (OSError, UnicodeDecodeError) as error:
        raise UpdateError(MESSAGE_BAD_SUMS.format(detail="nu se poate citi ca text")) from error
    return expected_sha256(text, file_name)


def sha256_of(path: Path) -> str:
    """SHA-256 (hex, litere mici) al fișierului, citit pe bucăți; ridică UpdateError dacă nu se poate citi."""
    digest = hashlib.sha256()
    try:
        with open(path, "rb") as handle:
            while chunk := handle.read(HASH_CHUNK_BYTES):
                digest.update(chunk)
    except OSError as error:
        raise UpdateError(MESSAGE_READ_FAILED.format(detail=error.strerror or type(error).__name__)) from error
    return digest.hexdigest()


def _remove_quietly(path: Path) -> None:
    """Șterge `path` dacă există; o eroare la ștergere nu ascunde eroarea care a dus aici."""
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass


def _refuse_linked_folders(base: Path) -> None:
    """UpdateError dacă folderul de lucru (.actualizare, părintele lui `base`) sau `base` (descarcari) e o legătură spre alt loc (P8):
    arhiva s-ar scrie, iar curățenia ar șterge, în afara programului. Se verifică înaintea oricărei creări și a oricărei cereri."""
    for path in (base.parent, base):
        if is_link(path):
            raise UpdateError(MESSAGE_LINKED_WORK_DIR.format(path=path.relative_to(base.parent.parent).as_posix()))


def _new_download_folder(base: Path) -> Path:
    """Creează `base` (dacă lipsește) și în el un subfolder nou, unic (tempfile.mkdtemp(dir=base)); ridică UpdateError."""
    try:
        base.mkdir(parents=True, exist_ok=True)
        return Path(tempfile.mkdtemp(prefix=DOWNLOAD_FOLDER_PREFIX, dir=base))
    except OSError as error:
        raise UpdateError(MESSAGE_WORK_DIR.format(detail=error.strerror or type(error).__name__)) from error


def _remove_download_folder(folder: Path, base: Path) -> None:
    """Șterge fișierele din `folder`, apoi `folder` și, dacă a rămas gol și nu e legătură, `base`. Nu ridică niciodată.

    Șterge doar fișiere obișnuite aflate direct în `folder` (download_release nu scrie altceva): nu coboară în foldere și nu urmează
    legături. Ce nu se poate șterge rămâne, cu un avertisment în jurnal; `base` rămâne și cât altă descărcare îl folosește.
    """
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                if entry.is_file(follow_symlinks=False):
                    os.unlink(entry.path)
                else:
                    logger.warning("actualizare: în folderul descărcării %s e ceva neașteptat, lăsat neatins: %s", folder.name, entry.name)
        os.rmdir(folder)
    except OSError as error:
        # Doar numele și motivul: calea întreagă ar pune în jurnal și numele contului de Windows.
        logger.warning("actualizare: folderul descărcării %s nu s-a putut șterge (%s)", folder.name, error.strerror or type(error).__name__)
        return
    if is_link(base):
        return
    try:
        os.rmdir(base)
    except OSError:
        pass  # nu e gol: altă descărcare (altă fereastră a aplicației) lucrează încă în el


@contextmanager
def download_folder(base: Path) -> Iterator[Path]:
    """Subfolderul nou și unic al unei descărcări, în `base` (settings.UPDATE_DOWNLOAD_DIR), șters la ieșire oricum s-ar fi terminat.

    Înainte: refuză un `base` sau un părinte al lui (.actualizare) care e legătură (P8) și șterge descărcările lăsate de un proces omorât,
    neatinse de o oră (update_recovery.remove_stale_downloads, P7; una vie, din altă fereastră, rămâne). Arhiva întoarsă de
    download_release(…, folder) rămâne pe disc cât ține blocul `with` (deci și cât rulează apply_update). Ridică UpdateError la o
    legătură sau dacă folderul nu se poate crea; ștergerea de la final nu ridică (vezi _remove_download_folder).
    """
    base = Path(base)
    _refuse_linked_folders(base)
    update_recovery.remove_stale_downloads(base)
    folder = _new_download_folder(base)
    try:
        yield folder
    finally:
        _remove_download_folder(folder, base)


def download_release(release: ReleaseAssets, work_dir: Path, *, download_to=update_http.download_to,
                     progress: Callable[[str], None] | None = None) -> Path:
    """Descarcă arhiva și SHA256SUMS.txt în `work_dir`, verifică mărimea și amprentele și întoarce calea arhivei verificate.

    `progress("descarc")` înainte de descărcare, `progress("verific")` înainte de amprentă. Ridică UpdateError; la orice
    eroare (și la întrerupere) arhiva se șterge. SHA256SUMS.txt se șterge mereu după citire.
    """
    _validate(release)
    work_dir = Path(work_dir)
    try:
        work_dir.mkdir(parents=True, exist_ok=True)
    except OSError as error:
        raise UpdateError(MESSAGE_WORK_DIR.format(detail=error.strerror or type(error).__name__)) from error
    zip_path, sums_path = work_dir / release.zip_name, work_dir / SUMS_NAME
    try:
        if progress is not None:
            progress(STAGE_DOWNLOAD)
        download_to(release.sums_url, sums_path, max_bytes=MAX_SUMS_BYTES, timeout=DOWNLOAD_TIMEOUT_SECONDS)
        expected = _read_sums(sums_path, release.zip_name)
        received = download_to(release.zip_url, zip_path, max_bytes=release.zip_size, timeout=DOWNLOAD_TIMEOUT_SECONDS)
        if received != release.zip_size:
            raise UpdateError(MESSAGE_SIZE_MISMATCH.format(received=received, expected=release.zip_size))
        if progress is not None:
            progress(STAGE_VERIFY)
        actual = sha256_of(zip_path)
        if not hmac.compare_digest(actual, expected):
            raise UpdateError(MESSAGE_WRONG_HASH)
        if release.zip_digest is not None and not hmac.compare_digest(DIGEST_PREFIX + actual, release.zip_digest):
            raise UpdateError(MESSAGE_WRONG_DIGEST)
    except BaseException:
        _remove_quietly(zip_path)
        raise
    finally:
        _remove_quietly(sums_path)
    return zip_path

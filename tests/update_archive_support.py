"""Arhive de lansare, foldere de program și un GitHub fals, toate INVENTATE, pentru testele actualizării.

Ce face: construiește cu zipfile o arhivă cu forma celei din lansare.yml (prefix cheltuieli-emag-vX.Y.Z/, .bat cu CRLF, lansatoarele
Unix cu modul 0o100755, manifestul instalare/fisiere.txt), instalează în tmp un program „vechi” cu manifestul lui și calculează
amprenta unui arbore (octet cu octet), ca testele să compare înainte/după; face și desface legături de folder (joncțiuni pe
Windows), „îmbătrânește” un folder (data modificării dată înapoi, ca o descărcare lăsată de un proces omorât de mult) și spune ce a
rămas în .actualizare în afară de lacăt. FakeGitHub înlocuiește deschizătorul din update_http: răspunde la API, la active (cu o
redirecționare, ca GitHub) și notează cererile. Ce NU face: nu iese pe internet, nu scrie în proiect.
"""

import email.message
import hashlib
import io
import json
import os
import time
import zipfile
from pathlib import Path

from emag_spend import settings, update_http
from emag_spend.version import VERSION, parse_version

MANIFEST = "instalare/fisiere.txt"
VERSION_FILE = "emag_spend/version.py"
LOCK_FILE = ".actualizare/lacat"  # singurul fișier care rămâne în .actualizare după o actualizare (gol, permanent; N5, N9)
EXECUTABLE_FILES = ("porneste.sh", "porneste.command", "instalare/pregatire.sh")
REGULAR_FILE_MODE = 0o100644
EXECUTABLE_FILE_MODE = 0o100755
DIRECTORY_MODE = 0o40755
UNIX_CREATE_SYSTEM = 3  # ca git archive: biții Unix stau în external_attr >> 16
MSDOS_DIRECTORY_FLAG = 0x10
ARCHIVE_DATE = (2026, 10, 5, 12, 0, 0)
DIRECTORY_MARK = "<folder>"
LINK_MARK = "<legătură>"


def newer_than(version: str = VERSION) -> str:
    """O versiune inventată, cu un pas mai nouă decât `version` (1.0.0 → 1.0.1)."""
    major, minor, patch = parse_version(version)
    return f"{major}.{minor}.{patch + 1}"


def program_files(version: str, *, extra: dict[str, bytes] | None = None, without: tuple[str, ...] = ()) -> dict[str, bytes]:
    """Fișierele unui program inventat la versiunea dată (fără manifest): cod, lansatoare (.bat cu CRLF), config, documentație.

    Conține toate fișierele obligatorii din update_archive.REQUIRED_FILES (altfel orice arhivă ar fi refuzată), cu conținut inventat.
    """
    files = {
        "emag_spend/__init__.py": b"",
        VERSION_FILE: f'"""Versiune inventată pentru teste."""\n\nVERSION = "{version}"\n'.encode("utf-8"),
        "emag_spend/modul.py": f"# modul inventat, versiunea {version}\n".encode("utf-8"),
        "emag_spend/update_lock.py": f"# lacăt inventat, versiunea {version}\n".encode("utf-8"),
        "emag_spend/update_recovery.py": f"# recuperare inventată, versiunea {version}\n".encode("utf-8"),
        "ruleaza.py": f"print('program inventat {version}')\n".encode("utf-8"),
        "porneste.bat": f"@echo off\r\nrem lansator inventat {version}\r\n".encode("utf-8"),
        "porneste.sh": f"#!/bin/sh\necho lansator inventat {version}\n".encode("utf-8"),
        "porneste.command": f"#!/bin/sh\necho lansator inventat {version}\n".encode("utf-8"),
        "instaleaza.bat": f"@echo off\r\nrem instalator inventat {version}\r\n".encode("utf-8"),
        "instalare/dupa_rulare.bat": f"@echo off\r\nrem după rulare, inventat {version}\r\n".encode("utf-8"),
        "instalare/mediu.bat": f"@echo off\r\nrem mediu inventat {version}\r\n".encode("utf-8"),
        "instalare/mediu.sh": f"# mediu inventat {version}\n".encode("utf-8"),
        "instalare/pregatire.sh": f"#!/bin/sh\necho pregătire inventată {version}\n".encode("utf-8"),
        "config/categorii.json": f'{{"versiune": "{version}"}}\n'.encode("utf-8"),
        "docs/ghid.md": f"Ghid inventat {version}\n".encode("utf-8"),
    }
    files.update(extra or {})
    for name in without:
        files.pop(name, None)
    return files


def manifest_bytes(paths) -> bytes:
    """Conținutul lui instalare/fisiere.txt: căile date plus manifestul însuși, sortate, câte una pe rând, LF."""
    return ("\n".join(sorted({*paths, MANIFEST})) + "\n").encode("utf-8")


def _entry(name: str, mode: int, *, directory: bool = False) -> zipfile.ZipInfo:
    """O intrare de arhivă cu modul Unix dat, ca la git archive."""
    info = zipfile.ZipInfo(name, date_time=ARCHIVE_DATE)
    info.create_system = UNIX_CREATE_SYSTEM
    info.external_attr = (mode << 16) | (MSDOS_DIRECTORY_FLAG if directory else 0)
    info.compress_type = zipfile.ZIP_STORED if directory else zipfile.ZIP_DEFLATED
    return info


def archive_bytes(version: str, files: dict[str, bytes], *, manifest: bytes | None = None, prefix: str | None = None,
                  extra_entries: tuple[tuple[zipfile.ZipInfo | str, bytes], ...] = (), directories: bool = True) -> bytes:
    """Arhiva unei lansări inventate: `files` + manifestul (implicit exact lista lor) sub cheltuieli-emag-v{version}/.

    `extra_entries` se adaugă la final ca atare (intrări capcană); `directories` pune și intrările de folder, ca git archive.
    """
    prefix = f"cheltuieli-emag-v{version}/" if prefix is None else prefix
    content = dict(files)
    content[MANIFEST] = manifest_bytes(files) if manifest is None else manifest
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        if directories:
            folders = sorted({str(Path(name).parent.as_posix()) for name in content} - {"."})
            archive.writestr(_entry(prefix, DIRECTORY_MODE, directory=True), b"")
            for folder in folders:
                archive.writestr(_entry(f"{prefix}{folder}/", DIRECTORY_MODE, directory=True), b"")
        for name in sorted(content):
            mode = EXECUTABLE_FILE_MODE if name in EXECUTABLE_FILES else REGULAR_FILE_MODE
            archive.writestr(_entry(prefix + name, mode), content[name])
        for entry, data in extra_entries:
            archive.writestr(entry, data)
    return buffer.getvalue()


def write_archive(path: Path, version: str, files: dict[str, bytes], **options) -> Path:
    """Scrie arhiva (vezi archive_bytes) în `path` și întoarce calea."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(archive_bytes(version, files, **options))
    return path


def install_program(root: Path, version: str, files: dict[str, bytes] | None = None, *, with_manifest: bool = True) -> dict[str, bytes]:
    """Scrie în `root` un program inventat „instalat” (cu manifestul lui, dacă `with_manifest`) și întoarce fișierele scrise."""
    files = program_files(version) if files is None else files
    content = dict(files)
    if with_manifest:
        content[MANIFEST] = manifest_bytes(files)
    for name, data in content.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return content


def add_user_data(root: Path) -> dict[str, bytes]:
    """Date inventate ale utilizatorului, pe care actualizarea nu are voie să le atingă (D7): rezultate, reguli personale, fișier propriu."""
    data = {
        "iesiri/2026-10-05_12-00-00/raport.html": b"<p>raport inventat</p>\n",
        "config/categorii.personal.json": '{"Cărți": ["titlu inventat"]}\n'.encode("utf-8"),
        "notitele_mele.txt": "fișier propriu, nelistat în manifest\n".encode("utf-8"),
        "logs/sesiune.log": b"jurnal inventat\n",
        ".venv/pyvenv.cfg": b"home = inventat\n",
    }
    for name, content in data.items():
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    return data


def work_dir_leftovers(root: Path) -> list[str]:
    """Ce a rămas în .actualizare în afară de fișierul-lacăt gol (care rămâne mereu, N5); [] dacă folderul nu există."""
    work = root / Path(LOCK_FILE).parent
    if not os.path.lexists(work):
        return []
    found = sorted(name for name in os.listdir(work) if name != Path(LOCK_FILE).name)
    lock = root / LOCK_FILE
    if os.path.lexists(lock) and lock.stat().st_size:
        found.append(f"{lock.name} (nu e gol)")
    return found


def age_tree(folder: Path, seconds: float) -> None:
    """Dă înapoi cu `seconds` data modificării lui `folder` și a tot ce e în el (fără să intre în legături), ca după atâta timp neatins."""
    moment = time.time() - seconds
    with os.scandir(folder) as found:
        entries = list(found)
    for entry in entries:
        if entry.is_symlink() or entry.is_junction():
            continue  # os.walk ar intra într-o joncțiune: aici nu se atinge nimic din alt loc
        if entry.is_dir(follow_symlinks=False):
            age_tree(Path(entry.path), seconds)
        else:
            os.utime(entry.path, (moment, moment))
    os.utime(folder, (moment, moment))


def write_journal_by_hand(work: Path, from_version: str, to_version: str, **fields) -> None:
    """Scrie de mână un jurnal de aplicare (format 1, implicit în starea „aplicare”), cu listele date și restul goale."""
    journal = {"format": 1, "de_la": from_version, "la": to_version, "stare": "aplicare", "scrise": [], "existau": [], "sterse": [],
               "foldere_noi": [], "foldere_sterse": [], **fields}
    work.mkdir(parents=True, exist_ok=True)
    (work / "jurnal.json").write_text(json.dumps(journal), encoding="utf-8")


def make_link(target: Path, link: Path) -> None:
    """O legătură de folder spre `target`: joncțiune pe Windows (nu cere drepturi de administrator), legătură simbolică în rest."""
    if os.name == "nt":
        import _winapi
        _winapi.CreateJunction(str(target), str(link))
    else:
        os.symlink(target, link, target_is_directory=True)


def remove_link(link: Path) -> None:
    """Scoate doar legătura făcută de make_link (nu atinge ținta); nimic dacă a dispărut deja."""
    if os.path.lexists(link):
        os.rmdir(link) if os.name == "nt" else os.unlink(link)


def fingerprint(root: Path, *, skip: tuple[str, ...] = (".actualizare",)) -> dict[str, str]:
    """Arborele de sub `root`, octet cu octet: cale relativă → SHA-256 (fișiere), <folder> sau <legătură>; fără primul nivel din `skip`.

    O legătură (simbolică sau joncțiune) apare ca <legătură> și nu se parcurge: ținta ei se compară separat, cu propria amprentă.
    """
    found: dict[str, str] = {}
    for folder, dirs, files in os.walk(root):
        base = Path(folder)
        if base == root:
            dirs[:] = [name for name in dirs if name not in skip]
            files = [name for name in files if name not in skip]
        for name in dirs:
            path = base / name
            found[path.relative_to(root).as_posix()] = LINK_MARK if path.is_symlink() or path.is_junction() else DIRECTORY_MARK
        dirs[:] = [name for name in dirs if found[(base / name).relative_to(root).as_posix()] != LINK_MARK]  # nu intră în legături
        for name in files:
            path = base / name
            found[path.relative_to(root).as_posix()] = LINK_MARK if path.is_symlink() else hashlib.sha256(path.read_bytes()).hexdigest()
    return found


# ---------- GitHub fals (pentru update_http) ----------

class FakeResponse:
    """Un răspuns HTTP inventat, cu ce citește update_http: status, antete (get), read(n) și close()."""

    def __init__(self, status: int, body: bytes = b"", headers: dict[str, str] | None = None):
        """Răspunsul cu codul, corpul și antetele date; Content-Length se pune singur."""
        self.status = status
        self._body = io.BytesIO(body)
        self.headers = email.message.Message()
        for name, value in {"Content-Length": str(len(body)), **(headers or {})}.items():
            self.headers[name] = value
        self.closed = False

    def read(self, size: int = -1) -> bytes:
        """Următorii `size` octeți din corp."""
        return self._body.read(size)

    def close(self) -> None:
        """Marchează răspunsul închis."""
        self.closed = True


class FakeGitHub:
    """Lansarea `version` a depozitului din setări, servită fără rețea: JSON-ul API, arhiva (prin redirecționare) și SHA256SUMS.txt.

    `install(monkeypatch)` înlocuiește update_http._build_opener; `requests` păstrează adresele cerute, în ordine.
    """

    ASSET_HOST = "https://release-assets.githubusercontent.com/inventat/"

    def __init__(self, version: str, archive: bytes, *, notes: str = "- o schimbare inventată\n"):
        """Pregătește răspunsurile pentru lansarea v{version} cu arhiva dată."""
        repository = settings.UPDATE_REPOSITORY
        tag = f"v{version}"
        self.zip_name = f"cheltuieli-emag-{tag}.zip"
        digest = hashlib.sha256(archive).hexdigest()
        download = f"https://github.com/{repository}/releases/download/{tag}/"
        release = {
            "tag_name": tag, "draft": False, "prerelease": False, "published_at": "2026-10-05T12:00:00Z",
            "html_url": f"https://github.com/{repository}/releases/tag/{tag}",
            "body": f"## Ce e nou în {tag}\n\n{notes}\n## Cum îl folosești\n\ntext inventat\n",
            "assets": [
                {"name": self.zip_name, "browser_download_url": download + self.zip_name, "size": len(archive),
                 "state": "uploaded", "digest": f"sha256:{digest}"},
                {"name": "SHA256SUMS.txt", "browser_download_url": download + "SHA256SUMS.txt", "size": 100, "state": "uploaded"},
            ],
        }
        self.routes = {
            f"https://api.github.com/repos/{repository}/releases/latest": FakeResponse(200, json.dumps(release).encode("utf-8")),
            download + self.zip_name: FakeResponse(302, headers={"Location": self.ASSET_HOST + self.zip_name}),
            self.ASSET_HOST + self.zip_name: FakeResponse(200, archive),
            download + "SHA256SUMS.txt": FakeResponse(200, f"{digest}  {self.zip_name}\n".encode("utf-8")),
        }
        self.requests: list[str] = []

    def open(self, request, timeout=None):
        """Ce face OpenerDirector.open: întoarce răspunsul inventat pentru adresa cerută (404 pentru orice altă adresă)."""
        url = request.full_url
        self.requests.append(url)
        response = self.routes.get(url)
        if response is None:
            return FakeResponse(404)
        response._body.seek(0)
        return response

    def install(self, monkeypatch) -> "FakeGitHub":
        """Pune GitHub-ul fals în locul deschizătorului real din update_http (nicio cerere nu iese din proces)."""
        monkeypatch.setattr(update_http, "_build_opener", lambda: self)
        return self

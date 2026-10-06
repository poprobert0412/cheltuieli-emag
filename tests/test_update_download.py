"""Testele descărcării și verificării arhivei unei versiuni noi (emag_spend/update_download.py), fără nicio cerere reală.

Verifică: ordinea (SHA256SUMS.txt întâi, apoi arhiva), limitele cu nume, etapele „descarc” / „verific”; mărimea primită ==
cea anunțată; amprenta == SHA256SUMS.txt (parsat strict) și == digest-ul din API; arhiva greșită ștearsă, SHA256SUMS.txt
niciodată lăsat pe disc; activele refuzate înaintea oricărei cereri dacă sunt greșite. Un test merge cap-coadă prin clientul
real update_http cu un deschizător fals (inclusiv redirecționarea spre gazda activelor). Folderul descărcării (download_folder, N9):
unic, șters la final oricum s-ar termina, fără să urmeze legături și fără să scoată o legătură a utilizatorului; refuzat înainte de
orice dacă .actualizare sau descarcari e legătură (P8); la început, descărcările lăsate de un proces omorât (inclusiv unul omorât
de-adevăratelea în test) se șterg, una vie nu (P7). Datele sunt inventate.
"""

import dataclasses
import hashlib
import http.client
import inspect
import io
import os
import shutil
import subprocess
import sys

import pytest

from emag_spend import settings, update_apply, update_download, update_http, update_recovery
from emag_spend.update_check import ReleaseAssets
from emag_spend.update_download import download_folder, download_release, expected_sha256
from emag_spend.update_errors import UpdateError
from tests.update_archive_support import (
    age_tree, fingerprint, install_program, make_link, newer_than, program_files, remove_link, work_dir_leftovers, write_archive,
)

TAG = "v2.4.0"
ZIP_NAME = f"cheltuieli-emag-{TAG}.zip"
BASE = f"https://github.com/exemplu-org/cheltuieli-test/releases/download/{TAG}/"
ZIP_URL, SUMS_URL = BASE + ZIP_NAME, BASE + "SHA256SUMS.txt"
CONTENT = b"PK\x03\x04" + bytes(range(256)) * 40  # o „arhivă” inventată; conținutul nu se deschide aici
SHA = hashlib.sha256(CONTENT).hexdigest()
SUMS = f"{SHA}  {ZIP_NAME}\n".encode("ascii")


def assets(**changes) -> ReleaseAssets:
    """Activele inventate ale unei lansări corecte, cu modificările date."""
    values = dict(tag=TAG, version=TAG[1:], zip_name=ZIP_NAME, zip_url=ZIP_URL, zip_size=len(CONTENT), zip_digest="sha256:" + SHA, sums_url=SUMS_URL)
    values.update(changes)
    return ReleaseAssets(**values)


class FakeDownload:
    """download_to fals: scrie octeții pregătiți pentru fiecare adresă (sau ridică excepția) și notează cererile."""

    def __init__(self, routes: dict[str, object]):
        self.routes = routes
        self.calls: list[tuple[str, str, int, float]] = []

    def __call__(self, url, target, *, max_bytes, timeout):
        """Aceeași semnătură ca update_http.download_to; o eroare poate veni după o scriere parțială (tuple: octeți, excepție)."""
        self.calls.append((url, target.name, max_bytes, timeout))
        outcome = self.routes[url]
        if isinstance(outcome, tuple):
            partial, error = outcome
            target.write_bytes(partial)
            raise error
        if isinstance(outcome, BaseException):
            raise outcome
        target.write_bytes(outcome)
        return len(outcome)


def run(routes: dict[str, object], work_dir, release: ReleaseAssets | None = None, progress=None):
    """Rulează download_release cu un download_to fals; întoarce (rezultat sau excepție, falsul)."""
    fake = FakeDownload(routes)
    try:
        return download_release(release or assets(), work_dir, download_to=fake, progress=progress), fake
    except (UpdateError, KeyboardInterrupt) as error:
        return error, fake


GOOD_ROUTES = {SUMS_URL: SUMS, ZIP_URL: CONTENT}


# ---------- drumul bun ----------

def test_a_correct_release_is_downloaded_and_verified(tmp_path):
    """Arhiva corectă: întoarsă din folderul de lucru, cu exact octeții primiți; SHA256SUMS.txt nu rămâne; etapele în ordine."""
    stages: list[str] = []
    result, fake = run(GOOD_ROUTES, tmp_path / "lucru", progress=stages.append)
    assert result == tmp_path / "lucru" / ZIP_NAME and result.read_bytes() == CONTENT
    assert sorted(p.name for p in (tmp_path / "lucru").iterdir()) == [ZIP_NAME]
    assert stages == ["descarc", "verific"]
    assert fake.calls == [
        (SUMS_URL, "SHA256SUMS.txt", update_download.MAX_SUMS_BYTES, update_download.DOWNLOAD_TIMEOUT_SECONDS),
        (ZIP_URL, ZIP_NAME, len(CONTENT), update_download.DOWNLOAD_TIMEOUT_SECONDS),
    ], "SHA256SUMS.txt se cere primul (un fișier de amprente greșit oprește totul înainte de arhivă), iar arhiva cu limita = mărimea anunțată"


def test_without_a_digest_from_the_api_the_sums_file_is_enough(tmp_path):
    """Fără digest în API (lansări mai vechi), verificarea cu SHA256SUMS.txt ajunge."""
    result, _ = run(GOOD_ROUTES, tmp_path, release=assets(zip_digest=None))
    assert result == tmp_path / ZIP_NAME


def test_the_default_downloader_is_the_https_client():
    """Fără parametru, descărcarea trece prin update_http.download_to (singurul client HTTPS)."""
    assert inspect.signature(download_release).parameters["download_to"].default is update_http.download_to


def test_the_limits_are_named_and_sane():
    """SHA256SUMS ≤ 64 KiB și arhiva ≤ 100 MB, constante cu nume."""
    assert update_download.MAX_SUMS_BYTES == 64 * 1024 and update_download.MAX_ZIP_BYTES == 100 * 1024 * 1024


# ---------- mutațiile de siguranță: amprentă, digest, mărime ----------

def _left(work_dir) -> list[str]:
    """Ce a rămas în folderul de lucru."""
    return sorted(p.name for p in work_dir.iterdir()) if work_dir.exists() else []


def test_a_wrong_hash_deletes_the_archive(tmp_path):
    """Amprenta din SHA256SUMS.txt diferă de arhivă: eroare, arhiva ștearsă, nimic pe disc."""
    other = hashlib.sha256(b"alt continut").hexdigest()
    result, _ = run({SUMS_URL: f"{other}  {ZIP_NAME}\n".encode(), ZIP_URL: CONTENT}, tmp_path, release=assets(zip_digest=None))
    assert isinstance(result, UpdateError) and str(result) == update_download.MESSAGE_WRONG_HASH
    assert _left(tmp_path) == []


def test_a_tampered_archive_with_the_published_hash_is_refused(tmp_path):
    """Arhiva primită e modificată (un octet), amprentele publicate sunt cele bune: eroare, ștearsă."""
    tampered = CONTENT[:-1] + bytes([CONTENT[-1] ^ 1])
    result, _ = run({SUMS_URL: SUMS, ZIP_URL: tampered}, tmp_path)
    assert isinstance(result, UpdateError) and str(result) == update_download.MESSAGE_WRONG_HASH
    assert _left(tmp_path) == []


def test_a_different_digest_from_the_api_deletes_the_archive(tmp_path):
    """SHA256SUMS.txt se potrivește, dar digest-ul anunțat de API nu: eroare, arhiva ștearsă."""
    result, _ = run(GOOD_ROUTES, tmp_path, release=assets(zip_digest="sha256:" + "0" * 64))
    assert isinstance(result, UpdateError) and str(result) == update_download.MESSAGE_WRONG_DIGEST
    assert _left(tmp_path) == []


def test_fewer_bytes_than_announced_deletes_the_archive(tmp_path):
    """Mărimea primită diferă de cea din API (transfer scurtat): eroare, arhiva ștearsă."""
    result, fake = run(GOOD_ROUTES, tmp_path, release=assets(zip_size=len(CONTENT) + 1))
    assert isinstance(result, UpdateError) and "GitHub anunța" in str(result) and str(len(CONTENT)) in str(result)
    assert fake.calls[1][2] == len(CONTENT) + 1, "limita descărcării arhivei trebuie să fie exact mărimea anunțată"
    assert _left(tmp_path) == []


def test_more_bytes_than_announced_is_stopped_by_the_client(tmp_path):
    """Mai mulți octeți decât anunțat: clientul oprește (limita = mărimea anunțată), eroarea trece mai departe, nimic pe disc."""
    result, _ = run({SUMS_URL: SUMS, ZIP_URL: UpdateError("Răspunsul GitHub depășește limita de 10 octeți; din siguranță, nu continui.")}, tmp_path)
    assert isinstance(result, UpdateError) and "depășește limita" in str(result)
    assert _left(tmp_path) == []


def test_a_previous_archive_is_removed_when_the_new_check_fails(tmp_path):
    """O arhivă rămasă de la o încercare veche nu supraviețuiește unei verificări eșuate (nu poate fi luată drept bună)."""
    (tmp_path / ZIP_NAME).write_bytes(CONTENT)
    result, fake = run({SUMS_URL: b"nu e un fisier de amprente\n", ZIP_URL: CONTENT}, tmp_path)
    assert isinstance(result, UpdateError) and len(fake.calls) == 1, "arhiva nu trebuia cerută după un SHA256SUMS.txt greșit"
    assert _left(tmp_path) == []


@pytest.mark.parametrize("routes", [
    {SUMS_URL: UpdateError("Nu pot ajunge la GitHub: fără internet sau conexiunea e blocată."), ZIP_URL: CONTENT},
    {SUMS_URL: SUMS, ZIP_URL: UpdateError("Conexiunea la GitHub s-a întrerupt în timpul transferului; încearcă din nou.")},
    {SUMS_URL: SUMS, ZIP_URL: (CONTENT[:100], UpdateError("întrerupt"))},
    {SUMS_URL: SUMS, ZIP_URL: (CONTENT[:100], KeyboardInterrupt())},
], ids=["sums-fara-internet", "arhiva-intrerupta", "arhiva-partiala", "ctrl-c"])
def test_a_network_failure_or_interruption_leaves_nothing_behind(tmp_path, routes):
    """Eroare de rețea la oricare fișier, sau Ctrl+C în mijlocul arhivei: eroarea trece mai departe și nu rămâne nimic."""
    result, _ = run(routes, tmp_path)
    assert isinstance(result, (UpdateError, KeyboardInterrupt))
    assert _left(tmp_path) == []


# ---------- activele sunt verificate din nou înaintea oricărei cereri ----------

@pytest.mark.parametrize("changes", [
    dict(zip_name="../cheltuieli-emag-v2.4.0.zip"), dict(zip_name="cheltuieli-emag-v2.4.1.zip"), dict(zip_name="x/cheltuieli-emag-v2.4.0.zip"),
    dict(tag="2.4.0", zip_name="cheltuieli-emag-2.4.0.zip"), dict(version="2.4.1"), dict(tag="v2.4", version="2.4", zip_name="cheltuieli-emag-v2.4.zip"),
    dict(tag="vv2.4.0", version="v2.4.0", zip_name="cheltuieli-emag-vv2.4.0.zip"),  # N10: „v” dublu, coerent în rest
    dict(zip_size=0), dict(zip_size=-5), dict(zip_size=True), dict(zip_size="10"), dict(zip_digest="sha256:" + SHA.upper()),
    dict(zip_digest="sha512:" + SHA), dict(zip_digest=SHA), dict(zip_url="http://github.com/x.zip"), dict(zip_url="https://exemplu.invalid/x.zip"),
    dict(sums_url="https://exemplu.invalid/SHA256SUMS.txt"),
], ids=lambda changes: ",".join(f"{k}={v!r}"[:40] for k, v in changes.items()))
def test_wrong_assets_are_refused_before_any_request(tmp_path, changes):
    """Nume care ar ieși din folder, etichetă sau versiune greșite, mărime absurdă, digest nenormalizat, adresă nepermisă: nicio cerere."""
    result, fake = run(GOOD_ROUTES, tmp_path, release=assets(**changes))
    assert isinstance(result, UpdateError) and fake.calls == []
    assert _left(tmp_path) == []


def test_an_archive_over_the_limit_is_refused_before_download(tmp_path):
    """Arhivă anunțată peste MAX_ZIP_BYTES: refuzată fără descărcare."""
    result, fake = run(GOOD_ROUTES, tmp_path, release=assets(zip_size=update_download.MAX_ZIP_BYTES + 1))
    assert isinstance(result, UpdateError) and str(result) == update_download.MESSAGE_TOO_BIG and fake.calls == []


def test_not_a_release_object_is_refused(tmp_path):
    """Altceva decât ReleaseAssets (ex. un dict) e refuzat clar, fără cereri și fără folder creat."""
    fake = FakeDownload({})
    with pytest.raises(UpdateError):
        download_release({"zip_url": ZIP_URL}, tmp_path / "lucru", download_to=fake)
    assert fake.calls == [] and not (tmp_path / "lucru").exists()


# ---------- SHA256SUMS.txt, parsat strict ----------

@pytest.mark.parametrize("text", [
    f"{SHA}  {ZIP_NAME}\n", f"{SHA} *{ZIP_NAME}\n", f"{SHA.upper()}  {ZIP_NAME}", f"{SHA}  {ZIP_NAME}\r\n",
    f"\n{'1' * 64}  alt-fisier.txt\n{SHA}  {ZIP_NAME}\n\n",
])
def test_valid_sums_files(text):
    """Forma lui `sha256sum` (text sau binar), hex cu litere mari, CRLF, rânduri goale și alte fișiere listate: acceptate."""
    assert expected_sha256(text, ZIP_NAME) == SHA


@pytest.mark.parametrize("text", [
    "", "\n\n", f"{SHA} {ZIP_NAME}", f"{SHA}\t{ZIP_NAME}", f"{SHA}   {ZIP_NAME}", f"{SHA[:-1]}  {ZIP_NAME}", f"{SHA}0  {ZIP_NAME}",
    f"{SHA}  {ZIP_NAME} ", f"{SHA}  dir/{ZIP_NAME}", f"{SHA}  ..\\{ZIP_NAME}", f" {SHA}  {ZIP_NAME}", f"\ufeff{SHA}  {ZIP_NAME}",
    f"{SHA}  {ZIP_NAME}\nrând stricat", f"{SHA}  {ZIP_NAME}\n{SHA}  {ZIP_NAME}", f"{SHA}  alt.zip", f"{'g' * 64}  {ZIP_NAME}",
    f"{SHA}  {ZIP_NAME.upper()}", f"# comentariu\n{SHA}  {ZIP_NAME}",
], ids=lambda text: repr(text)[:50])
def test_invalid_sums_files_are_refused(text):
    """Orice abatere (separator greșit, hex scurt sau lung, cale, BOM, rând stricat, intrare dublă sau lipsă): tot fișierul e refuzat."""
    with pytest.raises(UpdateError, match="SHA256SUMS.txt"):
        expected_sha256(text, ZIP_NAME)


def test_a_sums_file_that_is_not_utf8_is_refused(tmp_path):
    """SHA256SUMS.txt cu octeți invalizi: eroare clară, nimic pe disc."""
    result, _ = run({SUMS_URL: b"\xff\xfe" + SUMS, ZIP_URL: CONTENT}, tmp_path)
    assert isinstance(result, UpdateError) and "SHA256SUMS.txt" in str(result)
    assert _left(tmp_path) == []


def test_sha256_of_matches_hashlib(tmp_path):
    """Amprenta calculată pe bucăți e aceeași cu hashlib pe tot conținutul (și peste o bucată întreagă)."""
    path = tmp_path / "f.bin"
    data = b"x" * (update_download.HASH_CHUNK_BYTES + 17)
    path.write_bytes(data)
    assert update_download.sha256_of(path) == hashlib.sha256(data).hexdigest()
    with pytest.raises(UpdateError, match="Nu pot citi"):
        update_download.sha256_of(tmp_path / "lipsa.bin")


# ---------- cap-coadă prin clientul real, cu deschizător fals ----------

class _Reply:
    """Răspuns HTTP fals minim (status, antete, read, close)."""

    def __init__(self, status: int, body: bytes = b"", location: str | None = None):
        self.status = status
        self.headers = http.client.HTTPMessage()
        if location:
            self.headers["Location"] = location
        self._body = io.BytesIO(body)

    def read(self, size: int) -> bytes:
        """Următorii octeți."""
        return self._body.read(size)

    def close(self) -> None:
        """Nimic de închis."""


def test_end_to_end_through_the_real_client_with_a_fake_opener(tmp_path, monkeypatch):
    """Prin update_http.download_to real: github.com redirecționează spre release-assets.githubusercontent.com, ca GitHub;
    arhiva ajunge verificată, iar cererile au fost doar spre gazdele permise."""
    cdn = "https://release-assets.githubusercontent.com/github-production-release-asset/1/semnat?sig=inventat"
    routes = {SUMS_URL: _Reply(200, SUMS), ZIP_URL: _Reply(302, location=cdn), cdn: _Reply(200, CONTENT)}
    asked: list[str] = []

    class Opener:
        """Deschizător fals: răspunsul pregătit pentru fiecare adresă."""

        def open(self, request, timeout):
            """Notează adresa și întoarce răspunsul pregătit."""
            asked.append(request.full_url)
            return routes[request.full_url]

    monkeypatch.setattr(update_http, "_build_opener", Opener)
    result = download_release(assets(), tmp_path)
    assert result.read_bytes() == CONTENT and asked == [SUMS_URL, ZIP_URL, cdn]
    assert all(update_http.is_allowed_url(url) for url in asked)
    assert _left(tmp_path) == [ZIP_NAME]


def test_release_assets_is_immutable():
    """ReleaseAssets e înghețat: activele validate nu se pot schimba între verificare și descărcare."""
    with pytest.raises(dataclasses.FrozenInstanceError):
        assets().zip_url = "https://exemplu.invalid/x"


# ---------- folderul unei descărcări (decis 6 oct. 2026, N9) ----------

def test_each_download_folder_is_new_unique_and_inside_the_base(tmp_path):
    """Două descărcări simultane primesc foldere diferite, ambele direct în folderul de descărcări (creat dacă lipsește)."""
    base = tmp_path / "actualizare" / "descarcari"
    with download_folder(base) as first, download_folder(base) as second:
        assert first != second and first.parent == base and second.parent == base
        assert first.is_dir() and second.is_dir() and list(first.iterdir()) == []
        assert first.name.startswith(update_download.DOWNLOAD_FOLDER_PREFIX)
    assert not base.exists(), "după ultima descărcare, folderul de descărcări gol trebuie să dispară"


def test_the_download_folder_and_its_archive_are_removed_even_after_an_error(tmp_path):
    """O eroare în bloc (descărcare sau instalare picată) trece mai departe, iar folderul, cu arhiva și .part din el, dispare."""
    base = tmp_path / "descarcari"
    with pytest.raises(UpdateError, match="inventată"):
        with download_folder(base) as folder:
            (folder / ZIP_NAME).write_bytes(CONTENT)
            (folder / (ZIP_NAME + ".part")).write_bytes(b"jumatate")
            raise UpdateError("Eroare inventată la instalare.")
    assert not folder.exists() and not base.exists()


def test_a_download_folder_still_in_use_keeps_the_shared_base(tmp_path):
    """Cât altă descărcare lucrează în folderul de descărcări, acesta rămâne (doar subfolderul terminat dispare)."""
    base = tmp_path / "descarcari"
    with download_folder(base) as running:
        (running / ZIP_NAME).write_bytes(CONTENT)
        with download_folder(base) as finished:
            pass
        assert not finished.exists() and (running / ZIP_NAME).read_bytes() == CONTENT
    assert not base.exists()


def test_the_end_of_a_download_never_follows_a_link_inside_its_folder(tmp_path):
    """Siguranță (constatarea S1): o joncțiune / legătură pusă în folderul descărcării nu e urmată; ce e la capătul ei rămâne neatins.

    Arhiva (fișier obișnuit) se șterge; folderul cu legătura rămâne (cu avertisment în jurnal), pentru că nu se scoate nimic necunoscut.
    """
    outside = tmp_path / "in_afara"
    (outside / "sub").mkdir(parents=True)
    (outside / "important.txt").write_bytes(b"date ale utilizatorului")
    (outside / "sub" / "alt.txt").write_bytes(b"alte date")
    base = tmp_path / "descarcari"
    with download_folder(base) as folder:
        (folder / ZIP_NAME).write_bytes(CONTENT)
        make_link(outside, folder / "legatura")
    try:
        assert (outside / "important.txt").read_bytes() == b"date ale utilizatorului"
        assert (outside / "sub" / "alt.txt").read_bytes() == b"alte date"
        assert not (folder / ZIP_NAME).exists(), "arhiva trebuia ștearsă"
    finally:
        remove_link(folder / "legatura")


@pytest.mark.parametrize("linked", [".actualizare", ".actualizare/descarcari"])
def test_a_work_or_downloads_folder_that_is_a_link_is_refused_before_anything(tmp_path, linked):
    """P8: .actualizare sau .actualizare/descarcari legătură spre alt loc → UpdateError înainte de orice creare sau descărcare; legătura
    rămâne, iar folderul spre care arată (cu o descărcare „veche”, pe care curățenia ar șterge-o) e neatins."""
    root = tmp_path / "program"
    (root / ".actualizare").mkdir(parents=True)
    outside = tmp_path / "in_afara"
    (outside / "descarcare-veche").mkdir(parents=True)
    (outside / "descarcare-veche" / ZIP_NAME).write_bytes(b"al utilizatorului")
    age_tree(outside, update_recovery.STALE_DOWNLOAD_SECONDS + 60)
    before = fingerprint(outside, skip=())
    if linked == ".actualizare":
        (root / ".actualizare").rmdir()
    make_link(outside, root / linked)
    try:
        with pytest.raises(UpdateError, match="legătură spre alt loc") as refused:
            with download_folder(root / ".actualizare" / "descarcari"):
                pytest.fail("descărcarea n-ar fi trebuit să înceapă")
        assert f"«{linked}»" in str(refused.value), str(refused.value)
        assert os.path.lexists(root / linked) and fingerprint(outside, skip=()) == before
    finally:
        remove_link(root / linked)


def test_a_download_folder_that_cannot_be_created_is_an_update_error(tmp_path):
    """În locul folderului de descărcări e un fișier: UpdateError cu mesajul de disc, iar fișierul rămâne neatins."""
    base = tmp_path / "descarcari"
    base.write_bytes(b"un fisier")
    with pytest.raises(UpdateError) as caught:
        with download_folder(base):
            pytest.fail("blocul n-ar fi trebuit să ruleze")
    assert str(caught.value).startswith("Nu pot crea folderul de lucru al actualizării") and base.read_bytes() == b"un fisier"


def test_a_folder_that_cannot_be_removed_is_left_without_raising(tmp_path, monkeypatch, caplog):
    """Ștergerea de la final nu ridică (ar ascunde rezultatul actualizării): ce nu se poate șterge rămâne, cu avertisment în jurnal."""
    base = tmp_path / "descarcari"

    def busy(path):
        """os.rmdir care pică mereu, ca un folder ținut deschis de antivirus."""
        raise PermissionError(13, "ocupat de test")

    with download_folder(base) as folder:
        (folder / ZIP_NAME).write_bytes(CONTENT)
        monkeypatch.setattr(update_download.os, "rmdir", busy)
    assert folder.is_dir() and not (folder / ZIP_NAME).exists()
    assert "nu s-a putut șterge" in caplog.text


# ---------- descărcările lăsate de un proces omorât (decis 6 oct. 2026, P7) ----------

STALE = update_recovery.STALE_DOWNLOAD_SECONDS + 60  # cu un minut peste prag: „lăsată de mult”


def test_the_stale_limit_is_longer_than_any_live_download():
    """O descărcare vie are cel mult SHA256SUMS.txt + arhiva, fiecare cu termenul total din update_http, plus instalarea: pragul de
    ștergere trebuie să fie mai lung, cu marjă, altfel o fereastră ar șterge descărcarea vie a alteia. Numele vin dintr-un singur loc."""
    assert update_recovery.STALE_DOWNLOAD_SECONDS >= 2 * update_http.DOWNLOAD_TOTAL_SECONDS + 10 * 60
    assert update_download.DOWNLOAD_FOLDER_PREFIX == update_recovery.DOWNLOAD_FOLDER_PREFIX
    assert settings.UPDATE_DOWNLOAD_DIR.name == update_recovery.DOWNLOADS_DIR_NAME


def test_a_new_download_removes_the_ones_left_long_ago_but_not_a_live_one(tmp_path):
    """La începutul unei descărcări: descarcare-* neatinse de peste o oră dispar; una proaspătă (altă fereastră descarcă acum), un folder
    străin, un fișier cu același început de nume și o legătură rămân, iar ce e la capătul legăturii e neatins."""
    base = tmp_path / ".actualizare" / "descarcari"
    stale, live, foreign = base / "descarcare-oprita", base / "descarcare-vie", base / "al_utilizatorului"
    for folder in (stale, live, foreign):
        folder.mkdir(parents=True)
        (folder / (ZIP_NAME + ".part")).write_bytes(b"jumatate")
    (base / "descarcare-fisier.txt").write_bytes(b"nu e folder")
    outside = tmp_path / "in_afara"
    (outside / "sub").mkdir(parents=True)
    (outside / "sub" / "important.txt").write_bytes(b"date ale utilizatorului")
    for folder in (stale, foreign, outside):
        age_tree(folder, STALE)
    os.utime(base / "descarcare-fisier.txt", (0, 0))  # un fișier vechi de tot, cu numele unei descărcări: nu e folder, rămâne
    outside_before = fingerprint(outside, skip=())
    make_link(outside, base / "descarcare-legatura")
    try:
        with download_folder(base) as folder:
            assert not stale.exists(), "descărcarea lăsată de un proces omorât trebuia ștearsă la începutul descărcării noi"
            assert live.is_dir() and foreign.is_dir() and (base / "descarcare-fisier.txt").is_file() and folder.is_dir()
        assert os.path.lexists(base / "descarcare-legatura") and fingerprint(outside, skip=()) == outside_before
    finally:
        remove_link(base / "descarcare-legatura")


# Copilul începe o descărcare (download_folder + un .part pe jumătate) și așteaptă; testul îl omoară (TerminateProcess / SIGKILL),
# deci blocul `finally` care șterge folderul nu mai rulează: exact ce se întâmplă la Ctrl+C pe fereastră sau la o pană de curent.
DOWNLOADING_CHILD = r"""
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[2])
from emag_spend.update_download import download_folder
with download_folder(Path(sys.argv[1])) as folder:
    (folder / "cheltuieli-emag-v9.9.9.zip.part").write_bytes(b"x" * 4096)
    print("DESCARC", flush=True)
    sys.stdin.read()
"""
CHILD_ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", "EMAG_UPDATE_CHECK": "0"}
CHILD_TIMEOUT_SECONDS = 120


def test_a_download_killed_midway_is_removed_by_a_later_update_and_only_the_lock_stays(tmp_path):
    """P7 cap-coadă: procesul e omorât în timpul descărcării (arhiva pe jumătate rămâne), trece mai mult de o oră, apoi o actualizare
    reușită (download_folder + apply_update, ca aplicația și CLI): în .actualizare rămâne doar fișierul gol lacat."""
    version = newer_than("1.0.0")
    root = tmp_path / "program"
    install_program(root, "1.0.0")
    base = root / update_apply.WORK_DIR_NAME / update_recovery.DOWNLOADS_DIR_NAME
    child = subprocess.Popen([sys.executable, "-c", DOWNLOADING_CHILD, str(base), str(settings.PROJECT_ROOT)], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, env=CHILD_ENV)
    try:
        assert child.stdout.readline().strip() == b"DESCARC", "copilul n-a început descărcarea"
    finally:
        child.kill()
        child.wait(timeout=CHILD_TIMEOUT_SECONDS)
    (orphan,) = base.iterdir()
    assert (orphan / "cheltuieli-emag-v9.9.9.zip.part").is_file(), "omorât înainte de .part: testul n-ar dovedi nimic"
    age_tree(orphan, STALE)
    archive = write_archive(tmp_path / "arhiva" / f"cheltuieli-emag-v{version}.zip", version, program_files(version))
    with download_folder(base) as folder:
        copy = folder / archive.name
        shutil.copyfile(archive, copy)
        update_apply.apply_update(copy, root, version)
    assert work_dir_leftovers(root) == [], f"în .actualizare au rămas {work_dir_leftovers(root)}"


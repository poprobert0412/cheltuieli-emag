"""Testele verificării versiunii noi (emag_spend/update_check.py), cu un cititor JSON fals: nicio cerere reală.

Verifică: oprirea prin EMAG_UPDATE_CHECK=0 (citită la fiecare apel); o singură cerere, spre API-ul „latest” al depozitului
din settings; stările „la-zi” / „noua” / „eroare” / „dezactivat” și mesajele lor; validarea strictă a lansării (etichetă
vX.Y.Z, pagina și adresele activelor doar din depozitul programului, nume exacte, mărime, digest sha256); „Ce e nou” (D20);
fără downgrade și fără reinstalarea aceleiași versiuni; check_for_update nu ridică niciodată. Datele sunt inventate.
"""

import copy
import inspect

import pytest

from emag_spend import settings, update_check, update_http
from emag_spend.update_check import ReleaseAssets, check_for_update, release_notes
from emag_spend.update_errors import UpdateError

REPO = "exemplu-org/cheltuieli-test"
CURRENT = "2.3.4"
NEWER_TAG = "v2.4.0"
DIGEST_HEX = "ab" * 32
NOTES_BODY = (
    "## Ce e nou în v2.4.0\n\n- Buton nou pentru export.\n- Reparat totalul pe luni.\n\n### Detalii\nMai rapid.\n\n"
    "## Cum îl folosești\n\n1. Descarcă arhiva.\n"
)


def release(tag: str = NEWER_TAG, repo: str = REPO) -> dict:
    """JSON-ul inventat al unei lansări publicate corect (ca lansare.yml): arhiva, SHA256SUMS.txt, pagina și notele."""
    zip_name = f"cheltuieli-emag-{tag}.zip"
    base = f"https://github.com/{repo}/releases/download/{tag}/"
    return {
        "tag_name": tag, "name": f"Cheltuieli eMAG {tag}", "draft": False, "prerelease": False,
        "html_url": f"https://github.com/{repo}/releases/tag/{tag}", "published_at": "2026-10-05T12:00:00Z", "body": NOTES_BODY,
        "assets": [
            {"name": zip_name, "browser_download_url": base + zip_name, "size": 123456, "state": "uploaded", "digest": "sha256:" + DIGEST_HEX},
            {"name": "SHA256SUMS.txt", "browser_download_url": base + "SHA256SUMS.txt", "size": 92, "state": "uploaded", "digest": None},
        ],
    }


class FakeGetJson:
    """Cititor JSON fals: notează cererile (adresă, limită, timeout) și întoarce JSON-ul dat sau ridică eroarea dată."""

    def __init__(self, outcome):
        self.outcome = outcome
        self.calls: list[tuple[str, int, float]] = []

    def __call__(self, url: str, *, max_bytes: int, timeout: float):
        """Aceeași semnătură ca update_http.get_json."""
        self.calls.append((url, max_bytes, timeout))
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        return copy.deepcopy(self.outcome)


@pytest.fixture(autouse=True)
def invented_repository_and_version(monkeypatch):
    """Depozit și versiune curentă inventate, ca testele să nu depindă de lansarea reală; verificarea pornită implicit."""
    monkeypatch.setattr(settings, "UPDATE_REPOSITORY", REPO)
    monkeypatch.setattr(update_check, "VERSION", CURRENT)
    monkeypatch.delenv("EMAG_UPDATE_CHECK", raising=False)


def check(data) -> tuple[update_check.UpdateCheck, FakeGetJson]:
    """Rulează verificarea cu un cititor fals care întoarce `data` (sau ridică, dacă e excepție)."""
    fake = FakeGetJson(data)
    return check_for_update(get_json=fake, enabled=True), fake


# ---------- oprirea verificării ----------

def test_disabled_check_makes_no_request():
    """enabled=False: starea „dezactivat”, nicio cerere, linkul spre pagina lansărilor pentru verificarea manuală."""
    fake = FakeGetJson(release())
    result = check_for_update(get_json=fake, enabled=False)
    assert fake.calls == []
    assert (result.status, result.current, result.latest, result.release) == ("dezactivat", CURRENT, None, None)
    assert result.message == update_check.MESSAGE_DISABLED
    assert result.page_url == f"https://github.com/{REPO}/releases/latest"


@pytest.mark.parametrize("value, requests", [("0", 0), (" 0 ", 0), ("1", 1), ("", 1), ("nu", 1), (None, 1)])
def test_the_environment_variable_is_read_on_every_call(monkeypatch, value, requests):
    """enabled=None citește EMAG_UPDATE_CHECK la FIECARE apel: doar „0” oprește; lipsa ei sau altă valoare o lasă pornită."""
    if value is None:
        monkeypatch.delenv("EMAG_UPDATE_CHECK", raising=False)
    else:
        monkeypatch.setenv("EMAG_UPDATE_CHECK", value)
    fake = FakeGetJson(release())
    result = check_for_update(get_json=fake)
    assert len(fake.calls) == requests
    assert (result.status == "dezactivat") is (requests == 0)


def test_settings_reads_the_variable_at_call_time_not_at_import(monkeypatch):
    """settings.update_check_enabled() urmărește schimbările variabilei fără reîncărcarea modulului."""
    monkeypatch.setenv("EMAG_UPDATE_CHECK", "0")
    assert settings.update_check_enabled() is False
    monkeypatch.setenv("EMAG_UPDATE_CHECK", "1")
    assert settings.update_check_enabled() is True
    monkeypatch.delenv("EMAG_UPDATE_CHECK")
    assert settings.update_check_enabled() is True


# ---------- cererea ----------

def test_exactly_one_request_to_the_latest_release_of_the_configured_repository():
    """D2/D4: o singură cerere, la /repos/{UPDATE_REPOSITORY}/releases/latest, cu limita și timeout-ul cu nume."""
    _, fake = check(release())
    assert fake.calls == [(f"https://api.github.com/repos/{REPO}/releases/latest", update_check.MAX_RELEASE_JSON_BYTES, update_check.CHECK_TIMEOUT_SECONDS)]


def test_the_default_reader_is_the_https_client():
    """Fără parametru, verificarea folosește update_http.get_json (singurul client HTTPS)."""
    assert inspect.signature(check_for_update).parameters["get_json"].default is update_http.get_json


@pytest.mark.parametrize("repository", ["", "fara-bara", "a/b/c", "x/..", "x/.", "-x/y", "x y/z", "x/y?z", "exemplu/proiect#x", None])
def test_an_invalid_repository_in_settings_stops_before_any_request(monkeypatch, repository):
    """Un depozit greșit în settings.py (care ar schimba calea cererii) oprește verificarea înaintea oricărei cereri."""
    monkeypatch.setattr(settings, "UPDATE_REPOSITORY", repository)
    result, fake = check(release())
    assert fake.calls == [] and result.status == "eroare" and result.message == update_check.MESSAGE_BAD_REPOSITORY


# ---------- stările ----------

def test_a_newer_release_is_reported_with_validated_assets():
    """Versiune mai nouă: „noua”, mesajul benzii, notele, data, pagina și activele exacte."""
    result, _ = check(release())
    assert result.status == "noua" and result.current == CURRENT and result.latest == "2.4.0"
    assert result.message == "Versiune nouă: 2.4.0 (ai 2.3.4)."
    assert result.notes == "- Buton nou pentru export.\n- Reparat totalul pe luni.\n\n### Detalii\nMai rapid."
    assert result.published == "2026-10-05T12:00:00Z"
    assert result.page_url == f"https://github.com/{REPO}/releases/tag/v2.4.0"
    base = f"https://github.com/{REPO}/releases/download/v2.4.0/"
    assert result.release == ReleaseAssets(
        tag="v2.4.0", version="2.4.0", zip_name="cheltuieli-emag-v2.4.0.zip", zip_url=base + "cheltuieli-emag-v2.4.0.zip",
        zip_size=123456, zip_digest="sha256:" + DIGEST_HEX, sums_url=base + "SHA256SUMS.txt")


def test_the_same_version_is_up_to_date_and_offers_nothing_to_install():
    """Aceeași versiune: „la-zi”, fără active (nu se reinstalează aceeași versiune, D6)."""
    result, _ = check(release(tag="v" + CURRENT))
    assert (result.status, result.latest, result.release) == ("la-zi", CURRENT, None)
    assert result.message == "Ai ultima versiune (2.3.4)."


@pytest.mark.parametrize("tag", ["v2.3.3", "v1.9.9", "v0.0.1", "v2.2.10"])
def test_an_older_release_is_never_offered(tag):
    """Mutație „downgrade”: o lansare mai veche decât versiunea curentă nu e niciodată „noua” și nu are active."""
    result, _ = check(release(tag=tag))
    assert result.status == "la-zi" and result.release is None
    assert result.message == f"Ai o versiune mai nouă (2.3.4) decât ultima lansare publicată ({tag[1:]})."


def test_the_comparison_is_numeric():
    """2.10.0 e mai nouă decât 2.3.4 (comparare numerică, nu ca text)."""
    result, _ = check(release(tag="v2.10.0"))
    assert result.status == "noua" and result.latest == "2.10.0"


def test_broken_assets_do_not_matter_when_there_is_nothing_to_install():
    """La aceeași versiune activele nu se folosesc, deci nici nu dau eroare."""
    data = release(tag="v" + CURRENT)
    data["assets"] = []
    assert check(data)[0].status == "la-zi"


def test_a_network_error_becomes_the_error_state_with_its_message():
    """UpdateError de la client (ex. fără internet): „eroare”, exact mesajul lui și linkul spre pagina lansărilor."""
    result, _ = check(UpdateError("Nu pot ajunge la GitHub: fără internet sau conexiunea e blocată."))
    assert (result.status, result.latest, result.release) == ("eroare", None, None)
    assert result.message == "Nu pot ajunge la GitHub: fără internet sau conexiunea e blocată."
    assert result.page_url == f"https://github.com/{REPO}/releases/latest"


@pytest.mark.parametrize("error", [RuntimeError("defect"), KeyError("x"), ValueError("y"), TypeError("z")])
def test_an_unexpected_error_never_escapes(error):
    """Orice excepție neașteptată (un defect) devine „eroare” cu mesaj generic: verificarea din fundal nu oprește aplicația."""
    result, _ = check(error)
    assert result.status == "eroare" and result.message == update_check.MESSAGE_UNEXPECTED


def test_an_error_while_reading_the_settings_never_escapes(monkeypatch):
    """Chiar și o eroare la citirea setării devine „eroare”, nu excepție."""
    def broken() -> bool:
        """Setare care pică."""
        raise OSError("mediu inaccesibil")

    monkeypatch.setattr(settings, "update_check_enabled", broken)
    result = check_for_update(get_json=FakeGetJson(release()))
    assert result.status == "eroare"


# ---------- validarea strictă a lansării ----------

def _mutated(change) -> dict:
    """O lansare corectă, modificată de `change(data)`."""
    data = release()
    change(data)
    return data


def _zip(data: dict) -> dict:
    """Activul arhivei din lansare."""
    return data["assets"][0]


def _sums(data: dict) -> dict:
    """Activul SHA256SUMS.txt din lansare."""
    return data["assets"][1]


INVALID_RELEASES = {
    "obiect fără câmpurile lansării": lambda d: d.clear() or d.update({"x": []}),
    "ciornă": lambda d: d.update(draft=True),
    "de test": lambda d: d.update(prerelease=True),
    "etichetă fără v": lambda d: d.update(tag_name="2.4.0"),
    "etichetă cu V mare": lambda d: d.update(tag_name="V2.4.0"),
    "etichetă scurtă": lambda d: d.update(tag_name="v2.4"),
    "etichetă beta": lambda d: d.update(tag_name="v2.4.0-beta"),
    "etichetă cu zero în față": lambda d: d.update(tag_name="v2.04.0"),
    "etichetă număr": lambda d: d.update(tag_name=240),
    "etichetă lipsă": lambda d: d.pop("tag_name"),
    "pagină din alt depozit": lambda d: d.update(html_url="https://github.com/altcineva/cheltuieli-test/releases/tag/v2.4.0"),
    "pagină http": lambda d: d.update(html_url=f"http://github.com/{REPO}/releases/tag/v2.4.0"),
    "pagină pe altă gazdă": lambda d: d.update(html_url=f"https://exemplu.invalid/{REPO}/releases/tag/v2.4.0"),
    "pagină în afara lansărilor": lambda d: d.update(html_url=f"https://github.com/{REPO}/issues/1"),
    "pagină doar prefix": lambda d: d.update(html_url=f"https://github.com/{REPO}/releases/"),
    "pagină lipsă": lambda d: d.pop("html_url"),
    "fără listă de active": lambda d: d.pop("assets"),
    "active nu e listă": lambda d: d.update(assets={"a": 1}),
    "fără arhivă": lambda d: d["assets"].pop(0),
    "fără SHA256SUMS": lambda d: d["assets"].pop(1),
    "arhivă dublă": lambda d: d["assets"].append(dict(_zip(d))),
    "arhivă cu alt nume": lambda d: _zip(d).update(name="cheltuieli-emag-v2.4.0.ZIP"),
    "arhivă pentru altă etichetă": lambda d: _zip(d).update(name="cheltuieli-emag-v2.3.9.zip"),
    "adresă arhivă din alt depozit": lambda d: _zip(d).update(browser_download_url="https://github.com/altcineva/x/releases/download/v2.4.0/cheltuieli-emag-v2.4.0.zip"),
    "adresă arhivă altă etichetă": lambda d: _zip(d).update(browser_download_url=f"https://github.com/{REPO}/releases/download/v2.3.9/cheltuieli-emag-v2.4.0.zip"),
    "adresă arhivă http": lambda d: _zip(d).update(browser_download_url=f"http://github.com/{REPO}/releases/download/v2.4.0/cheltuieli-emag-v2.4.0.zip"),
    "adresă arhivă direct pe CDN": lambda d: _zip(d).update(browser_download_url="https://objects.githubusercontent.com/cheltuieli-emag-v2.4.0.zip"),
    "adresă arhivă alt fișier": lambda d: _zip(d).update(browser_download_url=f"https://github.com/{REPO}/releases/download/v2.4.0/altceva.zip"),
    "adresă arhivă cu parametri": lambda d: _zip(d).update(browser_download_url=f"https://github.com/{REPO}/releases/download/v2.4.0/cheltuieli-emag-v2.4.0.zip?x=1"),
    "adresă arhivă cu cale în plus": lambda d: _zip(d).update(browser_download_url=f"https://github.com/{REPO}/releases/download/v2.4.0/x/cheltuieli-emag-v2.4.0.zip"),
    "adresă arhivă lipsă": lambda d: _zip(d).pop("browser_download_url"),
    "mărime zero": lambda d: _zip(d).update(size=0),
    "mărime negativă": lambda d: _zip(d).update(size=-1),
    "mărime text": lambda d: _zip(d).update(size="123"),
    "mărime bool": lambda d: _zip(d).update(size=True),
    "mărime reală": lambda d: _zip(d).update(size=1.5),
    "mărime lipsă": lambda d: _zip(d).pop("size"),
    "arhivă încă în încărcare": lambda d: _zip(d).update(state="open"),
    "digest sha512": lambda d: _zip(d).update(digest="sha512:" + "ab" * 64),
    "digest scurt": lambda d: _zip(d).update(digest="sha256:" + "a" * 63),
    "digest nehex": lambda d: _zip(d).update(digest="sha256:" + "g" * 64),
    "digest cu SHA256 mare": lambda d: _zip(d).update(digest="SHA256:" + DIGEST_HEX),
    "digest număr": lambda d: _zip(d).update(digest=123),
    "adresă SHA256SUMS din alt depozit": lambda d: _sums(d).update(browser_download_url="https://github.com/altcineva/x/releases/download/v2.4.0/SHA256SUMS.txt"),
    "adresă SHA256SUMS alt fișier": lambda d: _sums(d).update(browser_download_url=f"https://github.com/{REPO}/releases/download/v2.4.0/SHA256SUMS.txt.asc"),
}


@pytest.mark.parametrize("name", sorted(INVALID_RELEASES))
def test_an_unexpected_release_is_refused(name):
    """Orice abatere de la forma publicată de lansare.yml dă „eroare”, fără active de descărcat (nimic nu se instalează din ea)."""
    result, _ = check(_mutated(INVALID_RELEASES[name]))
    assert result.status == "eroare", f"«{name}» a trecut: {result}"
    assert result.release is None and result.message.startswith("Lansarea de pe GitHub are date neașteptate")


def test_a_tag_with_a_doubled_v_is_refused_even_when_its_assets_match():
    """Mutație „vv” (decis 6 oct. 2026, N10): eticheta e EXACT „v” + X.Y.Z; „vv2.4.0”, cu arhiva și adresele potrivite ei, nu e anunțată.

    parse_version acceptă și un „v” în față, deci o verificare „începe cu v și restul se parsează” ar lua „vv2.4.0” drept versiunea „v2.4.0”.
    """
    result, fake = check(release(tag="vv2.4.0"))
    assert len(fake.calls) == 1, "cererea spre API trebuie să plece (refuzul vine din răspuns, nu dinainte)"
    assert (result.status, result.latest, result.release) == ("eroare", None, None), result
    assert result.message == update_check.MESSAGE_BAD_RELEASE.format(detail="eticheta nu e de forma vX.Y.Z")


@pytest.mark.parametrize("tag, accepted", [
    ("v1.2.3", True), ("v0.0.1", True), ("v10.20.30", True), ("vv1.2.3", False), ("v v1.2.3", False), ("V1.2.3", False), ("1.2.3", False),
    ("v", False), ("", False), ("v1.2", False), ("v01.2.3", False), ("v1.2.3 ", False), (" v1.2.3", False), (None, False), (123, False),
    ("v" + chr(0x661) + ".2.3", False),
])
def test_is_release_tag_accepts_exactly_v_followed_by_x_y_z(tag, accepted):
    """is_release_tag: un singur „v” mic, apoi direct X.Y.Z în cifre ASCII; orice altceva (alt tip, spații, „vv”, cifre arabe) e False."""
    assert update_check.is_release_tag(tag) is accepted


@pytest.mark.parametrize("data", [[], "text", None, 42])
def test_a_response_that_is_not_an_object_is_refused(data):
    """Un JSON care nu e obiect (listă, text, null) nu e o lansare."""
    assert check(data)[0].status == "eroare"


def test_accepted_variations_of_a_valid_release():
    """Variante legitime: fără digest, digest null, digest cu litere mari (normalizat), fără „state”, alte fișiere în plus,
    proprietarul scris cu altă combinație de litere mari/mici în adrese (GitHub nu le deosebește)."""
    variations = [
        lambda d: _zip(d).pop("digest"), lambda d: _zip(d).update(digest=None), lambda d: _zip(d).update(digest="sha256:" + DIGEST_HEX.upper()),
        lambda d: _zip(d).pop("state"), lambda d: d["assets"].append({"name": "alt.txt", "browser_download_url": "x", "size": 1}),
        lambda d: [a.update(browser_download_url=a["browser_download_url"].replace(REPO, REPO.upper())) for a in d["assets"]],
        lambda d: d.update(html_url=d["html_url"].replace(REPO, REPO.upper())),
    ]
    for index, change in enumerate(variations):
        result, _ = check(_mutated(change))
        assert result.status == "noua", f"varianta {index} a fost refuzată: {result.message}"
    assert check(_mutated(lambda d: _zip(d).update(digest="sha256:" + DIGEST_HEX.upper())))[0].release.zip_digest == "sha256:" + DIGEST_HEX
    assert check(_mutated(lambda d: _zip(d).pop("digest")))[0].release.zip_digest is None


@pytest.mark.parametrize("value", ["ieri", "2026-13-45T00:00:00Z", 1759660000, None, "2026-10-05T12:00:00Z" + " " * 40])
def test_an_unreadable_publication_date_is_ignored_not_fatal(value):
    """Data publicării neclară devine None; restul verificării merge."""
    result, _ = check(_mutated(lambda d: d.update(published_at=value)))
    assert result.status == "noua" and result.published is None


# ---------- „Ce e nou” (D20) ----------

def test_notes_take_the_section_under_the_first_ce_e_nou_heading():
    """Secțiunea de sub primul „## Ce e nou…”, până la următorul „## ” (subtitlurile „###” rămân), fără spații la capete."""
    body = "Introducere\n## Ce e nou în v2.4.0\nA\n### Sub\nB\n## Cum îl folosești\nC\n## Ce e nou (a doua)\nD"
    assert release_notes(body) == "A\n### Sub\nB"


def test_notes_heading_is_matched_without_case():
    """„## CE E NOU” e același titlu."""
    assert release_notes("## CE E NOU\nx\n## Alt") == "x"


def test_without_the_heading_notes_are_the_first_lines():
    """Fără titlul „## Ce e nou”: primele NOTES_FALLBACK_LINES rânduri."""
    body = "\n".join(f"rând {i}" for i in range(1, 40))
    notes = release_notes(body)
    assert notes.split("\n") == [f"rând {i}" for i in range(1, update_check.NOTES_FALLBACK_LINES + 1)]


def test_notes_are_cut_at_the_named_limit():
    """Un corp uriaș se taie la MAX_NOTES_CHARS caractere, cu „…” la final."""
    notes = release_notes("## Ce e nou\n" + "x" * (update_check.MAX_NOTES_CHARS * 3))
    assert len(notes) == update_check.MAX_NOTES_CHARS and notes.endswith("…")
    exact = release_notes("## Ce e nou\n" + "y" * update_check.MAX_NOTES_CHARS)
    assert exact == "y" * update_check.MAX_NOTES_CHARS, "un text de exact limita nu se taie"


def test_notes_are_plain_text_without_hidden_characters():
    """CRLF devine LF; caracterele de control și marcajele de direcție (bidi) dispar; HTML-ul rămâne text (interfața folosește textContent)."""
    body = "## Ce e nou\r\n- unu\r\n- doi\u202e\u2066ascuns\x07\x1b[31m\r\n<b>gros</b>\r\n## Alt"
    assert release_notes(body) == "- unu\n- doiascuns[31m\n<b>gros</b>"


@pytest.mark.parametrize("body", [None, 42, ["## Ce e nou"], ""])
def test_missing_notes_are_empty_text(body):
    """Corp lipsă sau de alt tip: note goale, fără eroare."""
    assert release_notes(body) == ""


def test_the_current_version_is_the_program_version_by_default(monkeypatch):
    """Fără înlocuirea din test, „current” e chiar version.VERSION (sursa unică)."""
    from emag_spend import version
    monkeypatch.setattr(update_check, "VERSION", version.VERSION)
    result = check_for_update(get_json=FakeGetJson(release(tag="v" + version.VERSION)), enabled=True)
    assert result.current == version.VERSION and result.status == "la-zi"

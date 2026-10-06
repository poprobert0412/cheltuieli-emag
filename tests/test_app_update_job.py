"""Teste pentru starea actualizării din aplicația locală (emag_spend/app_update_job.py), cu dependențe false: fără rețea, fără scrieri.

Verifică: verificarea pornește o singură dată (în fundal doar dacă e permisă), toate tranzițiile aplicării (descarc → verific →
instalez → gata → oprirea serverului după pauză), refuzurile 409 (analiză în curs, nicio versiune nouă, copie git, deja în curs),
erorile (UpdateError cu mesajul lui, excepții neașteptate cu mesaj generic), reîncercarea după eroare, că două cereri simultane
nu pornesc două aplicări, că oprirea serverului așteaptă doar instalarea și că fiecare descărcare are folderul ei, șters la final
(decis 6 oct. 2026, N9). Plus lanțul REAL (check_for_update → download_release → apply_update) peste GitHub-ul fals din
tests/update_archive_support.py, pe un program inventat în tmp. Valorile (versiuni, adrese) sunt inventate.
"""

import json
import threading
import time
from pathlib import Path

import pytest

from emag_spend import app_update_job, settings, update_apply, update_check, version
from emag_spend.app_update_job import ApplyRefused, UpdateJob
from emag_spend.update_errors import UpdateError
from tests.app_support import WAIT_SECONDS, wait_for
from tests.update_archive_support import (
    MANIFEST, FakeGitHub, add_user_data, archive_bytes, install_program, manifest_bytes, newer_than, program_files, work_dir_leftovers,
)

NEW_VERSION = "9.8.7"
REPOSITORY = "exemplu-inventat/program-inventat"
PARALLEL_REQUESTS = 20  # destule cereri simultane cât să prindă o verificare „citește, apoi scrie” fără lacăt
DISK_CHECK_SECONDS = 0.02  # durata simulată a verificării copiei git (o citire de pe disc), în mijlocul pornirii aplicării
FAKE_ARCHIVE_BYTES = b"arhiva inventata"  # ce „descarcă” download_release-ul fals: un fișier real, ca ștergerea folderului să conteze


def make_release(new_version: str = NEW_VERSION) -> update_check.ReleaseAssets:
    """Activele inventate ale unei lansări noi (forma reală din update_check)."""
    tag = f"v{new_version}"
    base = f"https://github.com/{REPOSITORY}/releases/download/{tag}/"
    return update_check.ReleaseAssets(tag=tag, version=new_version, zip_name=f"cheltuieli-emag-{tag}.zip", zip_url=base + f"cheltuieli-emag-{tag}.zip",
                                      zip_size=1234, zip_digest=None, sums_url=base + "SHA256SUMS.txt")


def make_check(status: str = update_check.STATUS_NEW, notes: str = "- o schimbare inventată") -> update_check.UpdateCheck:
    """Un rezultat de verificare inventat; doar „noua” are active de descărcat."""
    release = make_release() if status == update_check.STATUS_NEW else None
    latest = NEW_VERSION if status in (update_check.STATUS_NEW, update_check.STATUS_UP_TO_DATE) else None
    return update_check.UpdateCheck(status=status, current=version.VERSION, latest=latest, notes=notes, published="2026-10-05T10:00:00Z",
                                    page_url=f"https://github.com/{REPOSITORY}/releases/tag/v{NEW_VERSION}", release=release,
                                    message=f"Mesaj inventat pentru {status}.")


class Fakes:
    """Dependențele false ale job-ului: fiecare notează apelurile; porțile (Event) țin pe loc etapa cât vrea testul."""

    def __init__(self, tmp_path: Path):
        self.root = tmp_path / "program"
        self.work_dir = tmp_path / "lucru"
        self.calls: list[tuple] = []
        self.check_result: object = make_check()
        self.check_error: BaseException | None = None
        self.check_gate: threading.Event | None = None
        self.download_error: BaseException | None = None
        self.download_gate: threading.Event | None = None
        self.verify_gate: threading.Event | None = None
        self.apply_error: BaseException | None = None
        self.apply_gate: threading.Event | None = None
        self.git = False
        self.git_delay = 0.0  # cât „citește discul” is_git_checkout: lărgește fereastra în care o verificare fără lacăt s-ar suprapune
        self.busy = False
        self.applied = threading.Event()
        self.sleeps: list[float] = []
        self.sleep_gate: threading.Event | None = None
        self.states_when_applied: list[str] = []
        self.archive_present_at_apply: bool | None = None

    def check_for_update(self, *, enabled=None):
        """check_for_update fals: notează `enabled`, poate aștepta poarta sau ridica eroarea comandată."""
        self.calls.append(("check", enabled))
        if self.check_gate is not None:
            assert self.check_gate.wait(WAIT_SECONDS)
        if self.check_error is not None:
            raise self.check_error
        return self.check_result

    def download_release(self, release, work_dir, *, progress=None):
        """download_release fals: scrie arhiva inventată în `work_dir`, raportează „descarc” și „verific” (cu porți) și întoarce calea."""
        self.calls.append(("download", release.version, Path(work_dir)))
        archive = Path(work_dir) / release.zip_name
        archive.parent.mkdir(parents=True, exist_ok=True)  # ca download_release real, care își creează folderul primit
        archive.write_bytes(FAKE_ARCHIVE_BYTES)
        progress("descarc")
        if self.download_gate is not None:
            assert self.download_gate.wait(WAIT_SECONDS)
        progress("verific")
        if self.verify_gate is not None:
            assert self.verify_gate.wait(WAIT_SECONDS)
        if self.download_error is not None:
            raise self.download_error
        return archive

    def apply_update(self, zip_path, root, expected_version, *, progress=None):
        """apply_update fals: notează argumentele (și dacă arhiva e încă pe disc), poate aștepta poarta sau ridica eroarea comandată."""
        self.calls.append(("apply", Path(zip_path).name, Path(root), expected_version))
        self.archive_present_at_apply = Path(zip_path).read_bytes() == FAKE_ARCHIVE_BYTES
        if self.apply_gate is not None:
            assert self.apply_gate.wait(WAIT_SECONDS)
        if self.apply_error is not None:
            raise self.apply_error
        return object()

    def is_git_checkout(self, root):
        """is_git_checkout fals: valoarea comandată de test (după `git_delay` secunde, ca o citire de pe disc)."""
        self.calls.append(("git", Path(root)))
        if self.git_delay:
            time.sleep(self.git_delay)
        return self.git

    def sleep(self, seconds):
        """Pauza dinaintea opririi: notată; fără așteptare reală, doar poarta testului (dacă există)."""
        self.sleeps.append(seconds)
        if self.sleep_gate is not None:
            assert self.sleep_gate.wait(WAIT_SECONDS)

    def job(self, **overrides) -> UpdateJob:
        """Un UpdateJob legat de aceste dependențe false (și de „rulează o analiză?” / „oprește serverul” ale testului)."""
        options = dict(check_for_update=self.check_for_update, download_release=self.download_release, apply_update=self.apply_update,
                       is_git_checkout=self.is_git_checkout, root=self.root, work_dir=self.work_dir, sleep=self.sleep)
        options.update(overrides)
        job = UpdateJob(**options)
        job.attach(is_run_busy=lambda: self.busy, on_applied=lambda: self._on_applied(job))
        return job

    def _on_applied(self, job: UpdateJob) -> None:
        """Ce face serverul după „gata”: aici notează starea văzută în acel moment."""
        self.states_when_applied.append(job.snapshot()["apply"]["state"])
        self.applied.set()

    def called(self, name: str) -> list[tuple]:
        """Apelurile unei dependențe, în ordine."""
        return [call for call in self.calls if call[0] == name]

    def download_folders(self) -> list[Path]:
        """Folderele primite de download_release, în ordine (câte unul per descărcare)."""
        return [call[2] for call in self.called("download")]


@pytest.fixture(autouse=True)
def update_folders_in_tmp(tmp_path, monkeypatch):
    """Plasă de siguranță: rădăcina programului și folderele actualizării din settings arată în tmp pentru FIECARE test de aici.

    Un job construit cu implicitele lui (sau un cod regresat care ar ignora folderul primit) scrie astfel tot în tmp, niciodată în proiect.
    """
    work = tmp_path / "proiect_implicit" / ".actualizare"
    monkeypatch.setattr(settings, "PROJECT_ROOT", work.parent)
    monkeypatch.setattr(settings, "UPDATE_WORK_DIR", work)
    monkeypatch.setattr(settings, "UPDATE_DOWNLOAD_DIR", work / "descarcari")


@pytest.fixture
def fakes(tmp_path) -> Fakes:
    """Dependențele false ale testului curent."""
    return Fakes(tmp_path)


def _apply_state(job: UpdateJob) -> str:
    """Starea aplicării acum."""
    return job.snapshot()["apply"]["state"]


def _checked(job: UpdateJob, fakes: Fakes) -> UpdateJob:
    """Pornește verificarea (în fundal) și așteaptă rezultatul ei."""
    job.start_check(enabled=True)
    wait_for(lambda: job.snapshot()["check"]["status"] != app_update_job.CHECK_VERIFYING, "verificarea s-a terminat")
    return job


def _refusal(job: UpdateJob) -> ApplyRefused:
    """Excepția ridicată de start_apply (testul pică dacă aplicarea pornește)."""
    with pytest.raises(ApplyRefused) as refused:
        job.start_apply()
    return refused.value


# ---------- verificarea ----------

def test_before_the_check_starts_the_snapshot_says_not_started_and_nothing_is_applying(fakes):
    """Înainte de start_check: versiunea curentă, verificarea „dezactivat” cu mesaj, aplicarea „inactiv”; nicio dependență chemată."""
    snapshot = fakes.job().snapshot()
    assert snapshot["current"] == version.VERSION
    assert snapshot["check"]["status"] == update_check.STATUS_DISABLED and snapshot["check"]["message"]
    assert snapshot["apply"] == {"state": "inactiv", "message": "", "to_version": None}
    assert fakes.calls == []


def test_the_check_runs_in_the_background_shows_checking_then_the_result(fakes):
    """start_check(enabled=True) se întoarce imediat cu starea „verific”; rezultatul apare când termină firul (o singură cerere)."""
    fakes.check_gate = threading.Event()
    job = fakes.job()
    job.start_check(enabled=True)
    snapshot = job.snapshot()
    assert snapshot["check"]["status"] == "verific" and snapshot["check"]["message"].startswith("Verific")
    fakes.check_gate.set()
    wait_for(lambda: job.snapshot()["check"]["status"] == "noua", "verificarea a ajuns la „noua”")
    check = job.snapshot()["check"]
    assert check == {"status": "noua", "latest": NEW_VERSION, "notes": "- o schimbare inventată", "published": "2026-10-05T10:00:00Z",
                     "page_url": f"https://github.com/{REPOSITORY}/releases/tag/v{NEW_VERSION}", "message": "Mesaj inventat pentru noua."}
    job.start_check(enabled=True)
    assert fakes.called("check") == [("check", True)], "verificarea a pornit de două ori"


def test_a_disabled_check_answers_at_once_without_a_thread(fakes):
    """start_check(enabled=False): check_for_update(enabled=False) chemat pe loc (fără fir, fără rețea), rezultatul e imediat cel „dezactivat”."""
    fakes.check_result = make_check(update_check.STATUS_DISABLED)
    job = fakes.job()
    threads_before = threading.active_count()
    job.start_check(enabled=False)
    assert fakes.called("check") == [("check", False)]
    assert job.snapshot()["check"]["status"] == update_check.STATUS_DISABLED and threading.active_count() == threads_before


def test_an_unexpected_check_error_becomes_a_check_error_not_a_crash(fakes):
    """O excepție din check_for_update (deși contractul spune că nu ridică) devine verificare „eroare”, cu mesaj în română."""
    fakes.check_error = RuntimeError("detaliu intern inventat")
    job = _checked(fakes.job(), fakes)
    check = job.snapshot()["check"]
    assert check["status"] == update_check.STATUS_ERROR and "detaliu intern" not in check["message"] and check["message"].startswith("Nu am putut")


def test_the_snapshot_never_carries_the_download_addresses(fakes):
    """GET /api/update nu trimite paginii adresele arhivei și ale amprentelor: pagina nu are ce face cu ele."""
    job = _checked(fakes.job(), fakes)
    text = json.dumps(job.snapshot())
    assert "release" not in job.snapshot()["check"] and "releases/download" not in text and "SHA256SUMS" not in text


# ---------- refuzurile (409) ----------

@pytest.mark.parametrize("status", [update_check.STATUS_UP_TO_DATE, update_check.STATUS_ERROR, update_check.STATUS_DISABLED])
def test_apply_without_a_new_version_is_refused(fakes, status):
    """Verificare „la-zi”, „eroare” sau „dezactivat”: aplicarea e refuzată cu no_update și nu se descarcă nimic."""
    fakes.check_result = make_check(status)
    job = _checked(fakes.job(), fakes)
    assert _refusal(job).code == "no_update"
    assert fakes.called("download") == [] and _apply_state(job) == "inactiv"


def test_a_release_attached_to_a_check_that_is_not_new_is_ignored(fakes):
    """Apărare în adâncime: o verificare „la-zi” care (contrar contractului) are active de descărcat nu pornește nicio instalare."""
    up_to_date = make_check(update_check.STATUS_UP_TO_DATE)
    fakes.check_result = update_check.UpdateCheck(**{**up_to_date.__dict__, "release": make_release()})
    job = _checked(fakes.job(), fakes)
    assert _refusal(job).code == "no_update" and fakes.called("download") == []


def test_apply_before_any_check_is_refused(fakes):
    """Fără verificare (încă în lucru sau nepornită): nu se știe ce versiune să se instaleze, deci no_update."""
    fakes.check_gate = threading.Event()
    job = fakes.job()
    assert _refusal(job).code == "no_update"
    job.start_check(enabled=True)
    assert _refusal(job).code == "no_update", "aplicarea a pornit cât verificarea era încă în lucru"
    fakes.check_gate.set()


def test_apply_while_an_analysis_runs_is_refused(fakes):
    """Cât rulează o analiză: run_in_progress, cu mesaj în română, fără descărcare."""
    job = _checked(fakes.job(), fakes)
    fakes.busy = True
    refused = _refusal(job)
    assert refused.code == "run_in_progress" and "analiză" in refused.message
    assert fakes.called("download") == []


def test_apply_in_a_git_checkout_is_refused_with_the_decided_message(fakes):
    """Copie git: git_checkout cu exact mesajul din D9 („actualizează cu git pull”), fără descărcare."""
    fakes.git = True
    job = _checked(fakes.job(), fakes)
    refused = _refusal(job)
    assert refused.code == "git_checkout" and refused.message == "Folderul ăsta e o copie git: actualizează cu git pull."
    assert fakes.called("git") == [("git", fakes.root)] and fakes.called("download") == []


# ---------- tranzițiile ----------

def test_a_successful_update_goes_through_every_state_and_then_asks_for_the_restart(fakes):
    """descarc → verific → instalez → gata, apoi pauza RESTART_DELAY_SECONDS și abia apoi oprirea serverului; argumentele ajung corect."""
    fakes.download_gate, fakes.verify_gate, fakes.apply_gate = threading.Event(), threading.Event(), threading.Event()
    job = _checked(fakes.job(), fakes)
    first = job.start_apply()
    assert first == {"state": "descarc", "message": f"Descarc versiunea {NEW_VERSION}…", "to_version": NEW_VERSION}
    assert job.is_blocking()
    fakes.download_gate.set()
    wait_for(lambda: _apply_state(job) == "verific", "starea „verific”")
    assert "amprenta" in job.snapshot()["apply"]["message"]
    fakes.verify_gate.set()
    wait_for(lambda: _apply_state(job) == "instalez", "starea „instalez”")
    assert NEW_VERSION in job.snapshot()["apply"]["message"] and not fakes.applied.is_set()
    fakes.apply_gate.set()
    assert fakes.applied.wait(WAIT_SECONDS), "serverul nu a fost rugat să se oprească după „gata”"
    assert fakes.states_when_applied == ["gata"], "oprirea a fost cerută înainte ca starea să fie „gata”"
    assert fakes.sleeps == [app_update_job.RESTART_DELAY_SECONDS], "lipsește pauza dinaintea opririi (pagina n-ar apuca să arate „gata”)"
    done = job.snapshot()["apply"]
    assert done["state"] == "gata" and "repornește" in done["message"] and "filă nouă" in done["message"]
    [folder] = fakes.download_folders()
    assert fakes.called("download") == [("download", NEW_VERSION, folder)] and folder.parent == fakes.work_dir
    assert fakes.called("apply") == [("apply", f"cheltuieli-emag-v{NEW_VERSION}.zip", fakes.root, NEW_VERSION)]
    assert job.is_blocking(), "după „gata” nu trebuie să pornească nicio analiză (serverul se oprește)"


def test_the_default_download_folder_is_the_one_from_settings(fakes, monkeypatch, tmp_path):
    """Implicit, descărcarea se face sub settings.UPDATE_DOWNLOAD_DIR (aceeași constantă ca în ruleaza.py --actualizeaza, N9)."""
    monkeypatch.setattr(settings, "UPDATE_DOWNLOAD_DIR", tmp_path / "actualizare" / "descarcari")
    job = _checked(fakes.job(work_dir=None), fakes)
    job.start_apply()
    assert fakes.applied.wait(WAIT_SECONDS)
    assert fakes.download_folders()[0].parent == tmp_path / "actualizare" / "descarcari"


@pytest.mark.parametrize("outcome", ["succes", "eroare-descarcare", "eroare-instalare", "eroare-neasteptata"])
def test_each_download_gets_its_own_folder_removed_at_the_end_whatever_the_outcome(fakes, outcome):
    """N9 (decis 6 oct. 2026): fiecare descărcare primește un subfolder NOU sub folderul de descărcări, cu arhiva încă pe disc la
    instalare; la final subfolderul (cu arhiva din el) și folderul de descărcări rămas gol dispar, oricum s-ar fi terminat."""
    fakes.download_error = UpdateError("Amprentă inventată greșită.") if outcome == "eroare-descarcare" else None
    fakes.apply_error = {"eroare-instalare": UpdateError("Fișier inventat ocupat; am revenit."),
                         "eroare-neasteptata": RuntimeError("defect inventat")}.get(outcome)
    job = _checked(fakes.job(), fakes)
    job.start_apply()
    final = "gata" if outcome == "succes" else "eroare"
    wait_for(lambda: _apply_state(job) == final, f"starea „{final}”")
    [folder] = fakes.download_folders()
    assert folder.parent == fakes.work_dir and folder != fakes.work_dir
    if outcome != "eroare-descarcare":
        assert fakes.archive_present_at_apply is True, "arhiva trebuie să existe cât rulează instalarea"
    assert not fakes.work_dir.exists(), "folderul de descărcări (cu arhiva) a rămas după ce starea a ajuns la capăt"


def test_two_downloads_never_share_a_folder(fakes):
    """Două descărcări (aici: o eroare, apoi o reîncercare) primesc foldere diferite: eșecul uneia nu poate atinge arhiva celeilalte."""
    fakes.download_error = UpdateError("Eroare inventată.")
    job = _checked(fakes.job(), fakes)
    job.start_apply()
    wait_for(lambda: _apply_state(job) == "eroare", "starea „eroare”")
    fakes.download_error = None
    job.start_apply()
    assert fakes.applied.wait(WAIT_SECONDS)
    first, second = fakes.download_folders()
    assert first != second and first.parent == second.parent == fakes.work_dir


def test_a_download_folder_that_cannot_be_created_is_an_error_not_a_crash(fakes):
    """Folderul de descărcări nu se poate crea (aici: în locul lui e un fișier): „eroare” cu mesajul de disc, fără descărcare."""
    fakes.work_dir.parent.mkdir(parents=True, exist_ok=True)
    fakes.work_dir.write_bytes(b"un fisier in locul folderului")
    job = _checked(fakes.job(), fakes)
    job.start_apply()
    wait_for(lambda: _apply_state(job) == "eroare", "starea „eroare”")
    assert job.snapshot()["apply"]["message"].startswith("Nu pot crea folderul de lucru al actualizării")
    assert fakes.called("download") == [] and fakes.work_dir.read_bytes() == b"un fisier in locul folderului"


def test_a_second_apply_while_working_or_after_success_is_refused(fakes):
    """Încă o apăsare cât lucrează (update_in_progress) sau după „gata” (tot update_in_progress, alt mesaj): nicio a doua descărcare."""
    fakes.apply_gate = threading.Event()
    job = _checked(fakes.job(), fakes)
    job.start_apply()
    wait_for(lambda: _apply_state(job) == "instalez", "starea „instalez”")
    working = _refusal(job)
    assert working.code == "update_in_progress"
    fakes.apply_gate.set()
    assert fakes.applied.wait(WAIT_SECONDS)
    after = _refusal(job)
    assert after.code == "update_in_progress" and after.message != working.message
    assert len(fakes.called("download")) == 1


def test_a_download_error_shows_its_message_and_allows_a_retry(fakes):
    """UpdateError la descărcare: starea „eroare” cu exact mesajul erorii, fără instalare și fără oprire; o nouă apăsare pornește din nou."""
    fakes.download_error = UpdateError("Amprenta inventată nu se potrivește; am șters arhiva.")
    job = _checked(fakes.job(), fakes)
    job.start_apply()
    wait_for(lambda: _apply_state(job) == "eroare", "starea „eroare”")
    assert job.snapshot()["apply"]["message"] == "Amprenta inventată nu se potrivește; am șters arhiva."
    assert fakes.called("apply") == [] and not fakes.applied.is_set() and not job.is_blocking()
    fakes.download_error = None
    assert job.start_apply()["state"] == "descarc", "după o eroare, utilizatorul trebuie să poată încerca din nou"
    assert fakes.applied.wait(WAIT_SECONDS)


def test_an_install_error_shows_its_message_and_keeps_the_server_running(fakes):
    """UpdateError la instalare (versiunea veche a fost refăcută de update_apply): „eroare” cu mesajul lui, serverul nu se oprește."""
    fakes.apply_error = UpdateError("Un fișier inventat e folosit de alt program; am revenit la versiunea veche.")
    job = _checked(fakes.job(), fakes)
    job.start_apply()
    wait_for(lambda: _apply_state(job) == "eroare", "starea „eroare”")
    assert "am revenit la versiunea veche" in job.snapshot()["apply"]["message"]
    assert not fakes.applied.is_set() and fakes.sleeps == []


@pytest.mark.parametrize("where", ["download", "apply"])
def test_an_unexpected_error_becomes_a_generic_message_without_details(fakes, where):
    """O excepție neprevăzută (nu UpdateError): „eroare” cu mesaj generic în română (versiunea rămasă, jurnalul), fără detaliul tehnic."""
    setattr(fakes, f"{where}_error", RuntimeError("detaliu-intern-secret"))
    job = _checked(fakes.job(), fakes)
    job.start_apply()
    wait_for(lambda: _apply_state(job) == "eroare", "starea „eroare”")
    message = job.snapshot()["apply"]["message"]
    assert "detaliu-intern-secret" not in message and version.VERSION in message and "logs" in message
    assert not job.is_blocking()


def test_a_failing_restart_callback_does_not_break_the_finished_state(fakes):
    """Dacă oprirea serverului ridică o excepție, starea rămâne „gata” (firul nu moare cu ea)."""
    def broken_stop():
        raise RuntimeError("oprire stricată")

    job = _checked(fakes.job(), fakes)
    job.attach(is_run_busy=lambda: False, on_applied=broken_stop)
    job.start_apply()
    wait_for(lambda: _apply_state(job) == "gata" and len(fakes.sleeps) == 1, "starea „gata”")
    assert _apply_state(job) == "gata"


# ---------- concurența ----------

def test_simultaneous_apply_requests_start_exactly_one_update(fakes):
    """Multe cereri simultane: exact una pornește (202), celelalte primesc update_in_progress; o singură descărcare.

    Verificarea copiei git (o citire de pe disc) durează puțin: fără lacăt, alte cereri ar trece de verificarea stării între timp.
    """
    fakes.download_gate = threading.Event()
    fakes.git_delay = DISK_CHECK_SECONDS
    job = _checked(fakes.job(), fakes)
    start = threading.Barrier(PARALLEL_REQUESTS)
    started, refused = [], []

    def press():
        start.wait(WAIT_SECONDS)
        try:
            started.append(job.start_apply())
        except ApplyRefused as error:
            refused.append(error.code)

    threads = [threading.Thread(target=press) for _ in range(PARALLEL_REQUESTS)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(WAIT_SECONDS)
    fakes.download_gate.set()
    assert len(started) == 1 and refused == ["update_in_progress"] * (PARALLEL_REQUESTS - 1), f"pornite: {len(started)}, refuzate: {refused}"
    assert fakes.applied.wait(WAIT_SECONDS)
    assert len(fakes.called("download")) == 1


def test_is_blocking_follows_the_apply_state(fakes):
    """is_blocking: fals la „inactiv” și „eroare”, adevărat cât lucrează și după „gata” (atunci nu pornește nicio analiză)."""
    fakes.apply_gate = threading.Event()
    fakes.apply_error = UpdateError("Eroare inventată.")
    job = _checked(fakes.job(), fakes)
    assert not job.is_blocking()
    job.start_apply()
    assert job.is_blocking()
    fakes.apply_gate.set()
    wait_for(lambda: _apply_state(job) == "eroare", "starea „eroare”")
    assert not job.is_blocking()


def test_shutdown_waits_only_for_the_install_step(fakes):
    """wait_for_install: nu așteaptă descărcarea (întreruptă nu schimbă nimic), dar așteaptă instalarea până termină sau până la termen."""
    fakes.download_gate, fakes.apply_gate = threading.Event(), threading.Event()
    job = _checked(fakes.job(), fakes)
    assert job.wait_for_install(0.01) is True, "fără nicio aplicare, oprirea nu are ce aștepta"
    job.start_apply()
    assert job.wait_for_install(0.01) is True, "descărcarea nu trebuie așteptată la oprire"
    fakes.download_gate.set()
    wait_for(lambda: _apply_state(job) == "instalez", "starea „instalez”")
    assert job.wait_for_install(0.05) is False, "instalarea în lucru trebuie așteptată (aici, până la termen)"
    fakes.apply_gate.set()
    wait_for(lambda: job.wait_for_install(WAIT_SECONDS), "instalarea s-a terminat")


# ---------- lanțul real al aplicației (N9, constatarea C4) ----------

@pytest.fixture
def real_program(tmp_path, monkeypatch):
    """Un program inventat „instalat” în tmp la versiunea curentă, cu date ale utilizatorului, ca rădăcină a programului.

    settings.PROJECT_ROOT, UPDATE_WORK_DIR și UPDATE_DOWNLOAD_DIR arată spre el, deci UpdateJob() cu implicitele lui (rădăcina și
    folderul de descărcări din settings) lucrează doar în tmp. Întoarce (rădăcina, datele utilizatorului, fișierele versiunii noi).
    """
    root = tmp_path / "program"
    install_program(root, version.VERSION, program_files(version.VERSION, extra={"docs/vechi.md": b"doar in versiunea veche\n"}))
    user = add_user_data(root)
    new_files = program_files(newer_than(), extra={"docs/nou.md": "pagină nouă\n".encode("utf-8")})
    work = root / update_apply.WORK_DIR_NAME
    monkeypatch.setattr(settings, "PROJECT_ROOT", root)
    monkeypatch.setattr(settings, "UPDATE_WORK_DIR", work)
    monkeypatch.setattr(settings, "UPDATE_DOWNLOAD_DIR", work / "descarcari")
    return root, user, new_files


def _real_job() -> tuple[UpdateJob, threading.Event]:
    """UpdateJob cu dependențele REALE (verificare, descărcare, aplicare, copie git), fără pauză la repornire; plus evenimentul „gata”."""
    applied = threading.Event()
    job = UpdateJob(sleep=lambda seconds: None)
    job.attach(is_run_busy=lambda: False, on_applied=applied.set)
    job.start_check(enabled=True)
    wait_for(lambda: job.snapshot()["check"]["status"] != app_update_job.CHECK_VERIFYING, "verificarea s-a terminat")
    return job, applied


def test_the_real_chain_installs_the_new_version_and_leaves_only_the_lock(real_program, monkeypatch):
    """UpdateJob → check_for_update → download_release → apply_update, toate reale, peste GitHub-ul fals (fără rețea):
    starea ajunge la „gata”, programul e exact versiunea nouă, datele utilizatorului rămân, redirecționarea spre active e urmată,
    iar în .actualizare nu rămâne decât cel mult fișierul gol al lacătului (nicio arhivă, N9)."""
    root, user, new_files = real_program
    user_before = {name: (root / name).read_bytes() for name in user}
    new = newer_than()
    github = FakeGitHub(new, archive_bytes(new, new_files)).install(monkeypatch)
    job, applied = _real_job()
    assert job.snapshot()["check"]["status"] == update_check.STATUS_NEW and job.snapshot()["check"]["latest"] == new
    assert job.start_apply()["state"] == app_update_job.APPLY_DOWNLOADING
    assert applied.wait(WAIT_SECONDS), job.snapshot()["apply"]
    assert job.snapshot()["apply"]["state"] == app_update_job.APPLY_DONE
    expected = {**new_files, MANIFEST: manifest_bytes(new_files)}
    assert {name: (root / name).read_bytes() for name in expected} == expected
    assert not (root / "docs" / "vechi.md").exists(), "fișierul scos din versiunea nouă trebuia șters"
    assert {name: (root / name).read_bytes() for name in user} == user_before
    assert any("release-assets.githubusercontent.com" in url for url in github.requests), "redirecționarea spre active nu a fost urmată"
    assert work_dir_leftovers(root) == [], "în .actualizare are voie să rămână doar fișierul gol al lacătului"


def test_the_real_chain_refuses_a_tampered_archive_changes_nothing_and_keeps_no_download(real_program, monkeypatch):
    """Lanțul real cu o arhivă modificată pe drum: „eroare” cu mesajul amprentei, programul neatins, nicio arhivă rămasă."""
    root, _, new_files = real_program
    new = newer_than()
    github = FakeGitHub(new, archive_bytes(new, new_files)).install(monkeypatch)
    good = github.routes[github.ASSET_HOST + github.zip_name]
    tampered = bytearray(good._body.getvalue())
    tampered[len(tampered) // 2] ^= 0xFF
    good._body = type(good._body)(bytes(tampered))
    before = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*")
              if path.is_file() and update_apply.WORK_DIR_NAME not in path.relative_to(root).parts}
    job, applied = _real_job()
    job.start_apply()
    wait_for(lambda: _apply_state(job) == app_update_job.APPLY_ERROR, "starea „eroare”")
    assert "Amprenta" in job.snapshot()["apply"]["message"] and not applied.is_set()
    after = {path.relative_to(root).as_posix(): path.read_bytes() for path in root.rglob("*")
             if path.is_file() and update_apply.WORK_DIR_NAME not in path.relative_to(root).parts}
    assert after == before
    assert work_dir_leftovers(root) == [], "în .actualizare are voie să rămână doar fișierul gol al lacătului"

"""Teste pentru actualizarea din linia de comandă: --versiune, --actualizeaza, recuperarea la pornire și run_info.json.

Fluxul --actualizeaza se verifică în două feluri: cu verificarea, descărcarea și aplicarea înlocuite (mesaje, coduri, confirmarea DA,
folderul unic de descărcare din settings.UPDATE_DOWNLOAD_DIR, șters la final oricum, N9) și cap-coadă, cu modulele reale pe un
program INVENTAT dintr-un folder temporar și cu un GitHub fals (update_http._build_opener înlocuit): nicio cerere nu iese pe
internet, nimic nu se scrie în proiect. Recuperarea rulează la importul lui ruleaza.py (N2); aici se verifică ce face main cu
rezultatul ei (mesaj și mers mai departe, sau eroare și cod 1) și că ce a notat recuperarea înaintea jurnalului ajunge în logs/ (P6);
omorârea reală a procesului e în test_update_recovery.py. Un folder de descărcări care e legătură oprește --actualizeaza înaintea
oricărei descărcări (P8).
"""

import errno
import json
import os

import pytest

import ruleaza
from emag_spend import settings, update_apply, update_recovery
from emag_spend.update_check import STATUS_ERROR, STATUS_NEW, STATUS_UP_TO_DATE, ReleaseAssets, UpdateCheck
from emag_spend.update_errors import UpdateError
from emag_spend.version import VERSION
from tests.garda_audit import isolated_program
from tests.update_archive_support import (
    LOCK_FILE, FakeGitHub, add_user_data, archive_bytes, fingerprint, install_program, make_link, manifest_bytes, newer_than,
    program_files, remove_link, work_dir_leftovers, write_journal_by_hand,
)

NEW = newer_than(VERSION)
RELEASE = ReleaseAssets(tag=f"v{NEW}", version=NEW, zip_name=f"cheltuieli-emag-v{NEW}.zip",
                        zip_url=f"https://github.com/inventat/inventat/releases/download/v{NEW}/cheltuieli-emag-v{NEW}.zip",
                        zip_size=123, zip_digest=None, sums_url="https://github.com/inventat/inventat/releases/download/x/SHA256SUMS.txt")


def _check(status, *, release=RELEASE, notes="- o schimbare inventată", message="mesaj inventat"):
    """Un rezultat de verificare inventat, cu starea dată."""
    latest = NEW if status == STATUS_NEW else VERSION
    page = "https://github.com/inventat/inventat/releases/latest"
    return UpdateCheck(status, VERSION, latest, notes, "2026-10-05T12:00:00Z", page, release if status == STATUS_NEW else None, message)


def _move_work_dirs(monkeypatch, root):
    """Mută folderul de lucru al actualizării și pe cel al descărcărilor în programul din tmp (UPDATE_DOWNLOAD_DIR se calculează la import)."""
    monkeypatch.setattr(settings, "UPDATE_WORK_DIR", root / update_apply.WORK_DIR_NAME)
    monkeypatch.setattr(settings, "UPDATE_DOWNLOAD_DIR", root / update_apply.WORK_DIR_NAME / "descarcari", raising=False)


@pytest.fixture
def cli(tmp_path, monkeypatch):
    """ruleaza.main cu folderele programului în tmp și verificarea/descărcarea/aplicarea înlocuite; notează apelurile."""
    calls = {"check": [], "download": [], "apply": []}
    state = {"check": _check(STATUS_NEW), "download_error": None, "apply_error": None, "git": False}

    def fake_check(**kwargs):
        """Verificarea înlocuită: notează argumentele și întoarce rezultatul ales de test."""
        calls["check"].append(kwargs)
        return state["check"]

    def fake_download(release, work_dir, *, progress=None):
        """Descărcarea înlocuită: raportează etapele și scrie o arhivă inventată (și o urmă .part) în folderul primit."""
        calls["download"].append((release, work_dir))
        if progress:
            progress("descarc")
            progress("verific")
        work_dir.mkdir(parents=True, exist_ok=True)
        (work_dir / "SHA256SUMS.txt.part").write_bytes(b"descarcare intrerupta, inventata")
        if state["download_error"]:
            raise state["download_error"]
        archive = work_dir / release.zip_name
        archive.write_bytes(b"arhiva inventata")
        return archive

    def fake_apply(archive, root, version, *, progress=None):
        """Aplicarea înlocuită: notează argumentele, raportează etapa, ridică eroarea aleasă de test."""
        calls["apply"].append((archive, root, version))
        if progress:
            progress("instalez")
        if state["apply_error"]:
            raise state["apply_error"]
        return update_apply.ApplyResult(VERSION, version, 10, 1)

    monkeypatch.setattr(settings, "PROJECT_ROOT", tmp_path / "program")
    _move_work_dirs(monkeypatch, tmp_path / "program")
    monkeypatch.setattr(ruleaza, "check_for_update", fake_check)
    monkeypatch.setattr(ruleaza, "download_release", fake_download)
    monkeypatch.setattr(ruleaza, "apply_update", fake_apply)
    monkeypatch.setattr(ruleaza, "is_git_checkout", lambda root: state["git"])
    with isolated_program(monkeypatch, tmp_path) as layout:
        layout.calls, layout.state = calls, state
        yield layout


def _answer(monkeypatch, reply):
    """Înlocuiește input(): `reply` e textul tastat sau o excepție ridicată (EOF, Ctrl+C)."""
    asked = []

    def fake_input(prompt=""):
        """input() înlocuit: notează întrebarea și dă răspunsul ales."""
        asked.append(prompt)
        if isinstance(reply, BaseException):
            raise reply
        return reply

    monkeypatch.setattr("builtins.input", fake_input)
    return asked


def _assert_download_folder_gone(cli):
    """N9: descărcarea a mers într-un subfolder propriu din settings.UPDATE_DOWNLOAD_DIR, iar la final nu mai rămâne nimic din ea."""
    (release, work_dir), = cli.calls["download"]
    assert work_dir.parent == settings.UPDATE_DOWNLOAD_DIR, f"descărcarea trebuia să meargă într-un subfolder al lui {settings.UPDATE_DOWNLOAD_DIR}"
    assert not work_dir.exists() and not settings.UPDATE_DOWNLOAD_DIR.exists(), "descărcarea a lăsat urme"
    assert work_dir_leftovers(settings.PROJECT_ROOT) == [], "în .actualizare a rămas ceva după descărcare"
    return work_dir


# ---------- --versiune ----------

def test_versiune_prints_the_program_version_and_writes_nothing(cli, capsys):
    """--versiune scrie „Cheltuieli eMAG X.Y.Z”, iese cu 0 și nu creează jurnal."""
    assert ruleaza.main(["--versiune"]) == 0
    assert capsys.readouterr().out.strip() == f"Cheltuieli eMAG {VERSION}"
    assert not cli.logs.exists(), "--versiune nu are de ce să creeze un jurnal"
    assert cli.calls == {"check": [], "download": [], "apply": []}


# ---------- --actualizeaza cu dependențe înlocuite ----------

def test_typing_da_downloads_and_installs_and_says_to_start_again(cli, monkeypatch, capsys):
    """DA → descarcă într-un subfolder unic din .actualizare/descarcari, instalează, spune să fie pornit din nou și șterge descărcarea."""
    asked = _answer(monkeypatch, "DA")
    assert ruleaza.main(["--actualizeaza"]) == 0
    output = capsys.readouterr().out
    assert cli.calls["check"] == [{"enabled": True}], "--actualizeaza verifică și cu EMAG_UPDATE_CHECK=0 (cererea e explicită)"
    work_dir = _assert_download_folder_gone(cli)
    (archive, root, version), = cli.calls["apply"]
    assert archive == work_dir / RELEASE.zip_name and root == settings.PROJECT_ROOT and version == NEW
    assert f"Versiunea instalată: {VERSION}" in output and f"Versiune nouă: {NEW} (ai {VERSION}, publicată 2026-10-05)" in output
    assert "Ce e nou:\n- o schimbare inventată" in output
    assert "Descarc arhiva" in output and "Verific amprenta SHA-256" in output and "Instalez versiunea nouă" in output
    assert f"Actualizat la {NEW}. Pornește din nou programul." in output
    assert len(asked) == 1 and "DA" in asked[0] and NEW in asked[0]


def test_every_download_gets_its_own_folder(cli, monkeypatch):
    """N9: două descărcări (de exemplu din două ferestre) nu folosesc același folder: fiecare primește unul unic."""
    _answer(monkeypatch, "DA")
    folder = settings.UPDATE_DOWNLOAD_DIR / "al_altei_descarcari"
    folder.mkdir(parents=True)
    (folder / RELEASE.zip_name).write_bytes(b"arhiva altei ferestre, inventata")
    assert ruleaza.main(["--actualizeaza"]) == 0
    assert ruleaza.main(["--actualizeaza"]) == 0
    first, second = (work_dir for _, work_dir in cli.calls["download"])
    assert first != second and folder not in (first, second) and first.parent == second.parent == settings.UPDATE_DOWNLOAD_DIR
    assert (folder / RELEASE.zip_name).read_bytes() == b"arhiva altei ferestre, inventata", "a fost atinsă descărcarea altei ferestre"
    assert not first.exists() and not second.exists()


@pytest.mark.parametrize("reply", ["da", "nu", "", "DA, sigur", EOFError(), KeyboardInterrupt()],
                         ids=["da-mic", "nu", "gol", "text-in-plus", "eof", "ctrl-c"])
def test_anything_but_exactly_da_cancels_without_downloading(cli, monkeypatch, capsys, reply):
    """Orice altceva decât exact DA (și EOF, Ctrl+C) anulează fără descărcare."""
    _answer(monkeypatch, reply)
    assert ruleaza.main(["--actualizeaza"]) == 0
    assert "Anulat: nu am schimbat nimic." in capsys.readouterr().out
    assert cli.calls["download"] == [] and cli.calls["apply"] == []
    assert not settings.UPDATE_WORK_DIR.exists(), "o anulare nu creează nimic în .actualizare"


def test_fara_confirmare_installs_without_asking(cli, monkeypatch, capsys):
    """Cu --fara-confirmare nu se întreabă nimic."""
    def no_question(prompt=""):
        """input() care pică testul: cu --fara-confirmare nu se întreabă nimic."""
        raise AssertionError("cu --fara-confirmare nu se întreabă nimic")

    monkeypatch.setattr("builtins.input", no_question)
    assert ruleaza.main(["--actualizeaza", "--fara-confirmare"]) == 0
    assert len(cli.calls["apply"]) == 1 and f"Actualizat la {NEW}" in capsys.readouterr().out


def test_already_up_to_date_is_not_an_error(cli, capsys):
    """„Ai ultima versiune” nu e eroare: cod 0."""
    cli.state["check"] = _check(STATUS_UP_TO_DATE, message=f"Ai ultima versiune ({VERSION}).")
    assert ruleaza.main(["--actualizeaza"]) == 0
    assert f"Ai ultima versiune ({VERSION})." in capsys.readouterr().out
    assert cli.calls["download"] == []


def test_a_failed_check_ends_with_code_1_and_the_releases_page(cli, capsys):
    """O verificare eșuată → cod 1, mesaj și pagina lansărilor."""
    cli.state["check"] = UpdateCheck(STATUS_ERROR, VERSION, None, "", None, "https://github.com/inventat/inventat/releases/latest",
                                     None, "Nu pot ajunge la GitHub: fără internet sau conexiunea e blocată.")
    assert ruleaza.main(["--actualizeaza"]) == 1
    output = capsys.readouterr().out
    assert "EROARE: Nu pot ajunge la GitHub" in output and "Pagina lansărilor: https://github.com/inventat" in output
    assert "Traceback" not in output and cli.calls["download"] == []


def test_a_git_checkout_is_refused_before_downloading(cli, monkeypatch, capsys):
    """Într-o copie git se refuză înainte de descărcare (D9)."""
    cli.state["git"] = True
    _answer(monkeypatch, "DA")
    assert ruleaza.main(["--actualizeaza"]) == 1
    assert "copie git: actualizează cu git pull" in capsys.readouterr().out
    assert cli.calls["download"] == []


@pytest.mark.parametrize("stage", ["download", "apply"])
def test_update_errors_end_in_code_1_without_traceback_and_remove_the_download(cli, capsys, stage):
    """Erorile de descărcare sau aplicare → cod 1, fără traceback, descărcarea ștearsă cu tot cu urme, urmă în jurnal."""
    cli.state[f"{stage}_error"] = UpdateError("Amprenta arhivei descărcate nu se potrivește (mesaj inventat).")
    assert ruleaza.main(["--actualizeaza", "--fara-confirmare"]) == 1
    output = capsys.readouterr().out
    assert "EROARE: Amprenta arhivei descărcate nu se potrivește" in output and "Traceback" not in output
    assert (cli.calls["apply"] == []) == (stage == "download")
    _assert_download_folder_gone(cli)
    log_text = next(cli.logs.glob("*.log")).read_text(encoding="utf-8")
    assert "actualizare la" in log_text and "eșuată" in log_text


def test_a_downloads_folder_that_is_a_link_stops_the_update_before_any_download(cli, tmp_path, capsys):
    """P8: .actualizare/descarcari legătură spre alt loc → cod 1 și mesajul, fără nicio descărcare; ținta legăturii rămâne goală."""
    outside = tmp_path / "in_afara"
    outside.mkdir()
    settings.UPDATE_WORK_DIR.mkdir(parents=True)
    make_link(outside, settings.UPDATE_DOWNLOAD_DIR)
    try:
        assert ruleaza.main(["--actualizeaza", "--fara-confirmare"]) == 1
        output = capsys.readouterr().out
        assert "EROARE: Folderul «.actualizare/descarcari» al actualizării e o legătură" in output and "Traceback" not in output, output
        assert cli.calls["download"] == [] and cli.calls["apply"] == [] and list(outside.iterdir()) == []
    finally:
        remove_link(settings.UPDATE_DOWNLOAD_DIR)


def test_ctrl_c_during_the_update_ends_with_a_message_not_a_traceback(cli, capsys):
    """Ctrl+C în timpul actualizării → mesaj și cod 1, fără traceback, fără urme de descărcare."""
    cli.state["apply_error"] = KeyboardInterrupt()
    assert ruleaza.main(["--actualizeaza", "--fara-confirmare"]) == 1
    output = capsys.readouterr().out
    assert "oprită cu Ctrl+C" in output and "versiunea veche" in output and "Traceback" not in output
    _assert_download_folder_gone(cli)


# ---------- recuperarea la pornire (N2): ce face main cu rezultatul ei ----------

def _startup_recovery(monkeypatch, *, message=None, error=None):
    """Pune în ruleaza rezultatul recuperării de la import (cel adevărat se calculează o singură dată, la importul lui ruleaza.py)."""
    from emag_spend.update_recovery import RecoveryOutcome

    monkeypatch.setattr(ruleaza, "STARTUP_RECOVERY", RecoveryOutcome(message, error))


def test_after_a_recovery_the_message_is_shown_and_the_command_still_runs(cli, monkeypatch, capsys):
    """După o revenire reușită programul spune ce s-a întâmplat și face comanda cerută (fără 75, fără repornire)."""
    _startup_recovery(monkeypatch, message=f"Actualizarea la versiunea {NEW} a fost întreruptă; am revenit la versiunea {VERSION}.")
    assert ruleaza.main(["--versiune"]) == 0
    output = capsys.readouterr().out
    assert output.index("a fost întreruptă") < output.index(f"Cheltuieli eMAG {VERSION}"), output
    assert "a fost întreruptă" in next(cli.logs.glob("*.log")).read_text(encoding="utf-8"), "recuperarea trebuie să lase urmă în jurnal"


def test_after_a_recovery_a_bad_option_is_still_reported_normally(cli, monkeypatch, capsys):
    """Mesajul recuperării apare înaintea citirii opțiunilor; o opțiune greșită e apoi tratată ca de obicei (cod 2 de la argparse)."""
    _startup_recovery(monkeypatch, message="Actualizarea a fost întreruptă (mesaj inventat).")
    with pytest.raises(SystemExit) as stopped:
        ruleaza.main(["--prag", "nu-e-numar"])
    assert stopped.value.code == 2 and "a fost întreruptă" in capsys.readouterr().out


def test_a_recovery_that_cannot_run_now_ends_with_code_1_and_runs_nothing(cli, monkeypatch, capsys):
    """O recuperare imposibilă acum (lacăt ocupat, jurnal deteriorat) → eroarea, cod 1, nimic altceva."""
    _startup_recovery(monkeypatch, error="O altă actualizare e în curs (mesaj inventat).")
    assert ruleaza.main(["--versiune"]) == 1
    output = capsys.readouterr().out
    assert "EROARE: O altă actualizare e în curs" in output and "Cheltuieli eMAG" not in output
    assert "O altă actualizare e în curs" in next(cli.logs.glob("*.log")).read_text(encoding="utf-8")


def test_nothing_to_recover_lets_the_program_run(cli, monkeypatch, capsys):
    """Fără nimic de recuperat, programul continuă normal."""
    _startup_recovery(monkeypatch)
    assert ruleaza.main(["--versiune"]) == 0 and VERSION in capsys.readouterr().out


def _real_recovery_with_a_blocked_file(tmp_path, monkeypatch):
    """Rezultatul ADEVĂRAT al lui recover_before_start pe un program inventat pe jumătate actualizat, cu ruleaza.py blocat la revenire."""
    root = tmp_path / "recuperat"
    install_program(root, VERSION)
    work = root / update_apply.WORK_DIR_NAME
    (work / update_apply.OLD_DIR_NAME).mkdir(parents=True)
    os.replace(root / "ruleaza.py", work / update_apply.OLD_DIR_NAME / "ruleaza.py")
    (root / "ruleaza.py").write_text("print('versiunea nouă, pe jumătate instalată')\n", encoding="utf-8")
    write_journal_by_hand(work, VERSION, NEW, scrise=["ruleaza.py"], existau=["ruleaza.py"])
    real, blocked = os.replace, os.path.normcase(os.path.abspath(root / "ruleaza.py"))

    def held_open(source, target, *args, **kwargs):
        """Ca un fișier ținut deschis de alt program: înlocuirea lui ruleaza.py din rădăcină pică, cu sursa și ținta în eroare."""
        if os.path.normcase(os.path.abspath(target)) == blocked:
            raise PermissionError(errno.EACCES, "folosit de alt program (eroare inventată)", os.fspath(source), None, os.fspath(target))
        return real(source, target, *args, **kwargs)

    with monkeypatch.context() as patch:
        patch.setattr(update_recovery, "REPLACE_RETRY_DELAY_SECONDS", 0)
        patch.setattr(os, "replace", held_open)
        return update_recovery.recover_before_start(root)


def test_what_the_recovery_noted_before_the_log_existed_ends_up_in_the_log(cli, tmp_path, monkeypatch, capsys):
    """P6: un fișier blocat la revenire e notat de recuperare înainte de setup_logging; main îl scrie în jurnal (cu ora lui), apoi
    eroarea, și iese cu 1. Fără asta, logs/ n-ar spune ce fișier a blocat pornirea."""
    outcome = _real_recovery_with_a_blocked_file(tmp_path, monkeypatch)
    assert outcome.error and outcome.records, "recuperarea trebuia să eșueze și să noteze de ce: testul n-ar dovedi nimic"
    monkeypatch.setattr(ruleaza, "STARTUP_RECOVERY", outcome)
    assert ruleaza.main(["--versiune"]) == 1
    log_text = next(cli.logs.glob("*.log")).read_text(encoding="utf-8")
    assert "[emag_spend.update_recovery] ERROR: actualizare: nu am putut reface ruleaza.py" in log_text, log_text
    assert update_recovery.LOG_STARTUP_OUTCOME % outcome.error in log_text, log_text
    assert "EROARE: Actualizarea a eșuat" in capsys.readouterr().out


def test_a_cleanup_without_a_message_is_still_written_to_the_log(cli, tmp_path, monkeypatch, capsys):
    """P6: un jurnal „gata” (doar curățenie, fără mesaj pentru utilizator) lasă totuși urma în logs/, chiar și la --versiune."""
    root = tmp_path / "curatat"
    install_program(root, NEW)
    write_journal_by_hand(root / update_apply.WORK_DIR_NAME, VERSION, NEW, stare="gata")
    outcome = update_recovery.recover_before_start(root)
    assert outcome.message is None and outcome.error is None and outcome.records
    monkeypatch.setattr(ruleaza, "STARTUP_RECOVERY", outcome)
    assert ruleaza.main(["--versiune"]) == 0 and capsys.readouterr().out.strip().endswith(f"Cheltuieli eMAG {VERSION}")
    log_text = next(cli.logs.glob("*.log")).read_text(encoding="utf-8")
    assert f"curățenia după instalarea versiunii {NEW} s-a terminat acum" in log_text, log_text


def test_the_real_startup_recovery_ran_on_this_program():
    """La importul lui ruleaza.py recuperarea a rulat pe folderul lui (aici: depozitul, fără nimic de recuperat)."""
    from emag_spend.update_recovery import RecoveryOutcome

    assert ruleaza.STARTUP_RECOVERY == RecoveryOutcome(None, None)


# ---------- cap-coadă: modulele reale, GitHub fals, program inventat ----------

@pytest.fixture
def fake_install(tmp_path, monkeypatch):
    """Un program inventat la versiunea curentă (cu date ale utilizatorului) ca rădăcină a programului, plus arhiva versiunii NEW."""
    root = tmp_path / "program"
    install_program(root, VERSION, program_files(VERSION, extra={"docs/vechi.md": b"doar in versiunea veche\n"}))
    user = add_user_data(root)
    files = program_files(NEW, extra={"docs/nou.md": "pagină nouă\n".encode("utf-8")})
    monkeypatch.setattr(settings, "PROJECT_ROOT", root)
    _move_work_dirs(monkeypatch, root)
    with isolated_program(monkeypatch, tmp_path) as layout:
        layout.program, layout.user, layout.new_files = root, user, files
        layout.github = FakeGitHub(NEW, archive_bytes(NEW, files)).install(monkeypatch)
        yield layout


def test_actualizeaza_end_to_end_installs_the_release_and_keeps_user_data(fake_install, monkeypatch, capsys):
    """Cap-coadă cu GitHub fals: instalează, șterge fișierul vechi, păstrează datele, urmează redirecționarea; în .actualizare rămâne doar lacătul."""
    root = fake_install.program
    user_before = {name: (root / name).read_bytes() for name in fake_install.user}
    monkeypatch.setenv("EMAG_UPDATE_CHECK", "0")  # verificarea automată oprită nu oprește cererea explicită
    assert ruleaza.main(["--actualizeaza", "--fara-confirmare"]) == 0
    output = capsys.readouterr().out
    assert f"Actualizat la {NEW}. Pornește din nou programul." in output, output
    expected = {**fake_install.new_files, "instalare/fisiere.txt": manifest_bytes(fake_install.new_files)}
    assert all((root / name).read_bytes() == data for name, data in expected.items())
    assert not (root / "docs" / "vechi.md").exists(), "fișierul scos din versiunea nouă trebuia șters"
    assert {name: (root / name).read_bytes() for name in fake_install.user} == user_before
    assert work_dir_leftovers(root) == [], "după instalare în .actualizare rămâne doar lacătul gol"
    assert (root / LOCK_FILE).is_file()
    assert any("api.github.com" in url for url in fake_install.github.requests)
    assert any("release-assets.githubusercontent.com" in url for url in fake_install.github.requests), "redirecționarea nu a fost urmată"


def test_actualizeaza_end_to_end_refuses_a_tampered_archive_and_changes_nothing(fake_install, capsys):
    """Cap-coadă: o arhivă modificată pe drum e refuzată la amprentă și nu schimbă nimic."""
    root = fake_install.program
    before = fingerprint(root)
    good = fake_install.github.routes[fake_install.github.ASSET_HOST + fake_install.github.zip_name]
    tampered = bytearray(good._body.getvalue())
    tampered[len(tampered) // 2] ^= 0xFF
    good._body = type(good._body)(bytes(tampered))
    assert ruleaza.main(["--actualizeaza", "--fara-confirmare"]) == 1
    output = capsys.readouterr().out
    assert "EROARE:" in output and "Amprenta" in output and "Traceback" not in output
    assert fingerprint(root) == before and work_dir_leftovers(root) == []


def test_actualizeaza_end_to_end_when_already_at_the_latest_version(tmp_path, monkeypatch, capsys):
    """Cap-coadă: la ultima versiune, cod 0 și mesajul „Ai ultima versiune”."""
    root = tmp_path / "program"
    install_program(root, VERSION)
    monkeypatch.setattr(settings, "PROJECT_ROOT", root)
    _move_work_dirs(monkeypatch, root)
    with isolated_program(monkeypatch, tmp_path):
        FakeGitHub(VERSION, archive_bytes(VERSION, program_files(VERSION))).install(monkeypatch)
        assert ruleaza.main(["--actualizeaza"]) == 0
    assert f"Ai ultima versiune ({VERSION})" in capsys.readouterr().out


# ---------- run_info.json ----------

def test_run_info_records_the_program_version(tmp_path, monkeypatch):
    """run_info.json al unei rulări are program_version (D19)."""
    with isolated_program(monkeypatch, tmp_path) as layout:
        assert ruleaza.main(["--demo", "--iesire", str(layout.out)]) == 0
    (run_info,) = layout.out.rglob("run_info.json")
    assert json.loads(run_info.read_text(encoding="utf-8"))["program_version"] == VERSION

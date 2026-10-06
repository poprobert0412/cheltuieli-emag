"""Teste pentru aplicarea unei versiuni noi (update_apply.py, update_archive.py, update_lock.py), pe arhive și programe INVENTATE.

Fiecare test lucrează într-un folder temporar: un program „instalat” la versiunea veche (cu manifestul lui și date ale
utilizatorului) și o arhivă construită în test cu zipfile (.bat cu CRLF, lansatoarele Unix cu 0o100755). Verifică: fiecare regulă de
refuz (rădăcina rămâne identică, octet cu octet), că un fișier al programului nu lipsește din rădăcină în nicio clipă (N1),
revenirea la eșecul fiecărui os.replace și la Ctrl+C, recuperarea după o cădere, ștergerile doar din manifestul vechi, legăturile
(joncțiunile) care nu se urmează niciodată (N4), trecerile fișier ↔ folder (N6), lacătul și lungimea căilor pe Windows. După 6 oct.
2026: versiunea instalată citită sub lacăt, cu două procese REALE care aplică simultan (P2); un fișier „doar citire” înlocuit și pus la
loc cu atributul lui (P3); mesajul de eroare numește fișierul din program, nu copia lui din .actualizare (P4).
Recuperarea la pornire (update_recovery.py) are testele ei în test_update_recovery.py. Fără rețea, fără scrieri în proiect.
"""

import contextlib
import errno
import io
import json
import os
import stat
import subprocess
import sys
import time
import zipfile

import pytest

from emag_spend import settings, update_apply, update_archive, update_lock, update_recovery
from emag_spend.update_apply import apply_update, check_path_lengths, is_git_checkout, recover_interrupted
from emag_spend.update_errors import UpdateError
from emag_spend.version import VERSION
from tests.update_archive_support import (
    LINK_MARK, LOCK_FILE, MANIFEST, add_user_data, archive_bytes, fingerprint, install_program, make_link, manifest_bytes, program_files,
    remove_link, work_dir_leftovers, write_archive, write_journal_by_hand,
)

OLD = "1.4.2"  # versiuni inventate, independente de versiunea reală a programului
NEW = "1.5.0"
PREFIX = f"cheltuieli-emag-v{NEW}/"
DELETED_IN_NEW = "docs/ghid.md"  # există în versiunea veche, lipsește din cea nouă: trebuie șters (D8)
ADDED_IN_NEW = "docs/nou/pagina.md"  # fișier nou, într-un folder nou
REWRITTEN = "config/categorii.json"  # există în ambele versiuni, cu alt conținut: se rescrie
OUTSIDE_FILES = {"important.txt": "al altcuiva, în afara programului\n", "sub/alt.txt": "tot în afara programului\n"}


def new_release_files(**changes) -> dict[str, bytes]:
    """Fișierele versiunii noi: ca cea veche, cu un fișier scos (DELETED_IN_NEW) și unul adăugat într-un folder nou."""
    extra = {ADDED_IN_NEW: "pagină nouă, inventată\n".encode("utf-8"), **changes.pop("extra", {})}
    return program_files(NEW, extra=extra, without=(DELETED_IN_NEW, *changes.pop("without", ())))


@pytest.fixture
def program(tmp_path):
    """Un program instalat la versiunea OLD, cu manifestul lui și date ale utilizatorului (rezultate, reguli personale, fișier propriu)."""
    root = tmp_path / "program"
    install_program(root, OLD)
    add_user_data(root)
    return root


def _no_pauses(monkeypatch):
    """Reîncercările la PermissionError fără pauze: testele nu așteaptă antivirusul."""
    monkeypatch.setattr(update_recovery, "REPLACE_RETRY_DELAY_SECONDS", 0)


@pytest.fixture(autouse=True)
def no_retry_pauses(monkeypatch):
    """Toate testele de aici rulează fără pauzele de reîncercare (vezi _no_pauses)."""
    _no_pauses(monkeypatch)


def release(tmp_path, files=None, **options):
    """Scrie arhiva versiunii NEW în tmp (în afara programului) și întoarce calea."""
    return write_archive(tmp_path / "descarcari" / f"cheltuieli-emag-v{NEW}.zip", NEW, new_release_files() if files is None else files,
                         **options)


def assert_work_dir_clean(root):
    """După orice aplicare, în .actualizare rămâne cel mult fișierul-lacăt gol: fără extragere, copie veche sau jurnal (N5, N9)."""
    leftovers = work_dir_leftovers(root)
    assert not leftovers, f"au rămas în {update_apply.WORK_DIR_NAME}: {leftovers}"


def outside_folder(tmp_path):
    """Un folder din afara programului, cu fișiere care nu au voie să fie atinse; întoarce (calea, amprenta lui)."""
    outside = tmp_path / "in_afara"
    for name, text in OUTSIDE_FILES.items():
        (outside / name).parent.mkdir(parents=True, exist_ok=True)
        (outside / name).write_text(text, encoding="utf-8")
    return outside, fingerprint(outside, skip=())


# ---------- aplicarea reușită ----------

def test_apply_installs_the_new_files_deletes_only_old_manifest_files_and_keeps_user_data(program, tmp_path):
    """Aplicarea reușită: fișierele noi octet cu octet (.bat cu CRLF), cel scos din versiune șters, datele utilizatorului neatinse."""
    before = fingerprint(program)
    stages = []
    files = new_release_files()
    result = apply_update(release(tmp_path, files), program, NEW, progress=stages.append)
    expected = {**files, MANIFEST: manifest_bytes(files)}
    assert result == update_apply.ApplyResult(OLD, NEW, len(expected), 1)
    for name, data in expected.items():
        assert (program / name).read_bytes() == data, f"{name} nu are conținutul versiunii noi"
    assert b"\r\n" in (program / "porneste.bat").read_bytes(), "lansatorul Windows și-a pierdut CRLF"
    assert not (program / DELETED_IN_NEW).exists(), "fișierul scos din versiunea nouă a rămas"
    after = fingerprint(program)
    for name in ("iesiri/2026-10-05_12-00-00/raport.html", "config/categorii.personal.json", "notitele_mele.txt", "logs/sesiune.log", ".venv/pyvenv.cfg"):
        assert after[name] == before[name], f"{name} (al utilizatorului) s-a schimbat"
    assert stages == [update_apply.PROGRESS_INSTALLING]
    assert_work_dir_clean(program)
    assert (program / LOCK_FILE).is_file(), "lacătul e un fișier permanent (N5): rămâne, gol"


def test_a_file_of_the_program_never_disappears_from_the_program_folder(program, tmp_path, monkeypatch):
    """N1: după fiecare os.replace al aplicării, fiecare fișier prezent în ambele versiuni există în rădăcină (vechi sau nou, întreg).

    Fără asta, un proces omorât între două mutări lasă un modul lipsă, iar ruleaza.py crapă la import înainte să poată reveni (R1).
    """
    files = new_release_files()
    rewritten = sorted(set(files) & set(program_files(OLD)))
    real, missing, calls = os.replace, [], []

    def watch(source, target):
        """os.replace adevărat, urmat de verificarea că niciun fișier rescris nu lipsește din rădăcină."""
        real(source, target)
        calls.append(target)
        missing.extend(f"{name} (după mutarea nr. {len(calls)})" for name in rewritten if not (program / name).is_file())

    monkeypatch.setattr(os, "replace", watch)
    apply_update(release(tmp_path, files), program, NEW)
    assert len(calls) > len(rewritten), "spionul n-a văzut mutările: testul n-ar dovedi nimic"
    assert not missing, f"fișiere lipsă din rădăcină în timpul aplicării: {missing[:5]}"


def test_a_folder_emptied_by_the_deletions_is_removed_but_one_with_user_files_stays(program, tmp_path):
    """Un folder golit de ștergeri dispare; unul în care utilizatorul are fișiere rămâne, cu fișierele lui."""
    install_program(program, OLD, program_files(OLD, extra={"vechi/doar_vechi.txt": b"x\n", "vechi2/doar_vechi.txt": b"y\n"}))
    (program / "vechi2" / "al_meu.txt").write_text("al utilizatorului\n", encoding="utf-8")
    apply_update(release(tmp_path), program, NEW)
    assert not (program / "vechi").exists()
    assert (program / "vechi2" / "al_meu.txt").is_file() and not (program / "vechi2" / "doar_vechi.txt").exists()


def test_without_a_local_manifest_nothing_is_deleted(tmp_path):
    """Fără manifest local (instalare din ZIP vechi) nu se șterge nimic (D8)."""
    root = tmp_path / "program"
    install_program(root, OLD, with_manifest=False)
    apply_update(release(tmp_path), root, NEW)
    assert (root / DELETED_IN_NEW).is_file(), "fără manifest local (prima instalare din ZIP vechi) nu se șterge nimic"
    assert (root / MANIFEST).read_bytes() == manifest_bytes(new_release_files())


def _add_to_local_manifest(program, lines):
    """Adaugă rânduri la manifestul local, în octeți cu LF (write_text pe Windows ar pune CRLF și ar strica tot manifestul)."""
    path = program / MANIFEST
    path.write_bytes(path.read_bytes() + "".join(f"{line}\n" for line in lines).encode("utf-8"))


def test_the_local_manifest_with_an_extra_valid_line_still_deletes(program, tmp_path):
    """Martor pentru testele de mai jos: un rând în plus, valid, nu oprește ștergerile (deci acolo le oprește chiar rândul greșit)."""
    _add_to_local_manifest(program, ["docs/inexistent.md"])
    apply_update(release(tmp_path), program, NEW)
    assert not (program / DELETED_IN_NEW).exists()


@pytest.mark.parametrize("bad_line", ["../evadat.txt", "C:/Windows/x", "docs//x.md", "iesiri/../../x"])
def test_a_damaged_local_manifest_means_no_deletions_at_all(program, tmp_path, bad_line):
    """Un rând nepermis în manifestul local oprește TOATE ștergerile."""
    _add_to_local_manifest(program, [bad_line])
    apply_update(release(tmp_path), program, NEW)
    assert (program / DELETED_IN_NEW).is_file()


def test_a_local_manifest_rewritten_with_crlf_still_works(program, tmp_path):
    """Manifestul local rescris cu CRLF (editor, script Windows) se citește la fel; cel nou, din arhivă, rămâne strict LF (test mai jos)."""
    path = program / MANIFEST
    path.write_bytes(path.read_bytes().replace(b"\n", b"\r\n"))
    apply_update(release(tmp_path), program, NEW)
    assert not (program / DELETED_IN_NEW).exists()


def test_protected_paths_listed_in_the_old_manifest_are_never_deleted(program, tmp_path):
    """Căile protejate (D7) scrise în manifestul local nu se șterg, chiar dacă manifestul e altfel valid."""
    tampered = ["config/categorii.personal.json", "iesiri/2026-10-05_12-00-00/raport.html", "logs/sesiune.log", ".venv/pyvenv.cfg"]
    _add_to_local_manifest(program, tampered)
    before = fingerprint(program)
    apply_update(release(tmp_path), program, NEW)
    after = fingerprint(program)
    assert not (program / DELETED_IN_NEW).exists(), "manifestul local trebuia folosit (altfel testul n-ar dovedi nimic)"
    assert all(after.get(name) == before[name] for name in tampered)


def test_the_profile_folder_from_emag_profile_dir_listed_in_the_old_manifest_is_never_deleted(program, tmp_path, monkeypatch):
    """N8a: profilul din EMAG_PROFILE_DIR, în folderul programului și listat în manifestul vechi, rămâne după aplicare (D7)."""
    monkeypatch.setattr(settings, "PROFILE_DIR", program / "sesiunea_mea")
    cookies = program / "sesiunea_mea" / "Cookies"
    cookies.parent.mkdir()
    cookies.write_bytes(b"sesiune inventata")
    _add_to_local_manifest(program, ["sesiunea_mea/Cookies"])
    apply_update(release(tmp_path), program, NEW)
    assert not (program / DELETED_IN_NEW).exists(), "manifestul local trebuia folosit (altfel testul n-ar dovedi nimic)"
    assert cookies.read_bytes() == b"sesiune inventata", "sesiunea din EMAG_PROFILE_DIR a fost ștearsă la actualizare"


def test_a_user_file_not_in_any_manifest_stays_even_inside_program_folders(program, tmp_path):
    """Un fișier al utilizatorului, nelistat în niciun manifest, rămâne chiar dacă stă în emag_spend/."""
    (program / "emag_spend" / "extensia_mea.py").write_text("# al utilizatorului\n", encoding="utf-8")
    apply_update(release(tmp_path), program, NEW)
    assert (program / "emag_spend" / "extensia_mea.py").read_text(encoding="utf-8") == "# al utilizatorului\n"


def test_a_name_that_changes_only_case_keeps_the_new_file(program, tmp_path):
    """Un fișier redenumit doar prin litere mari/mici nu e șters ca „vechi” peste cel nou (Windows nu le deosebește)."""
    files = new_release_files(without=("config/categorii.json",), extra={"config/Categorii.json": b'{"nou": true}\n'})
    apply_update(release(tmp_path, files), program, NEW)
    assert (program / "config" / "Categorii.json").read_bytes() == b'{"nou": true}\n'
    assert_work_dir_clean(program)


def test_the_profile_folder_from_emag_profile_dir_inside_the_program_is_protected(program, tmp_path, monkeypatch):
    """Profilul din EMAG_PROFILE_DIR, dacă e în folderul programului, e protejat ca .profil_browser."""
    monkeypatch.setattr(settings, "PROFILE_DIR", program / "sesiunea_mea")
    before = fingerprint(program)
    with pytest.raises(UpdateError, match="cale protejată"):
        apply_update(release(tmp_path, new_release_files(extra={"sesiunea_mea/Cookies": b"x"})), program, NEW)
    assert fingerprint(program) == before


@pytest.mark.skipif(os.name == "nt", reason="biții de execuție Unix nu există pe Windows")
def test_unix_launchers_keep_their_execute_bit(program, tmp_path):
    """Pe macOS/Linux lansatoarele rămân executabile după aplicare (D14)."""
    apply_update(release(tmp_path), program, NEW)
    for name in ("porneste.sh", "porneste.command"):
        assert os.stat(program / name).st_mode & 0o111 == 0o111, f"{name} nu mai e executabil"
    assert not os.stat(program / "ruleaza.py").st_mode & 0o111


def test_the_execute_bit_is_read_from_the_archive_mode():
    """Bitul de execuție se citește din modul intrării (external_attr >> 16)."""
    with zipfile.ZipFile(io.BytesIO(archive_bytes(NEW, new_release_files()))) as archive:
        executable = {info.filename[len(PREFIX):] for info in archive.infolist()
                      if not info.is_dir() and update_archive.is_executable_entry(info)}
    assert executable == {"porneste.sh", "porneste.command", "instalare/pregatire.sh"}


# ---------- copia de siguranță a fișierelor vechi (N1) ----------

def test_without_hard_links_the_backup_is_a_full_copy_and_every_failure_still_reverts(tmp_path, monkeypatch):
    """Pe un disc fără legături tari (FAT32, exFAT) copia veche se face cu shutil.copy2; aplicarea reușește și revenirea merge oriunde."""
    def no_hard_links(*args, **kwargs):
        """os.link pe un disc care nu știe legături tari."""
        raise OSError(errno.EXDEV, "legături tari nesuportate (eroare inventată)")

    monkeypatch.setattr(os, "link", no_hard_links)
    real = os.replace
    total = _count_replaces(tmp_path, monkeypatch)
    monkeypatch.setattr(os, "link", no_hard_links)
    for k in range(1, total + 1):
        root = tmp_path / f"program_{k}"
        install_program(root, OLD)
        before = fingerprint(root)
        monkeypatch.setattr(os, "replace", _ReplaceSpy(real, k, OSError(errno.EIO, "eroare inventată de disc")))
        with pytest.raises(UpdateError, match="am revenit la versiunea 1.4.2"):
            apply_update(release(tmp_path / f"a{k}"), root, NEW)
        monkeypatch.setattr(os, "replace", real)
        assert fingerprint(root) == before, f"fără legături tari, după eșecul la os.replace nr. {k}, rădăcina nu e ca înainte"
        assert_work_dir_clean(root)
    root = tmp_path / "program_reusit"
    install_program(root, OLD)
    apply_update(release(tmp_path / "ok"), root, NEW)
    assert (root / REWRITTEN).read_bytes() == new_release_files()[REWRITTEN]
    assert_work_dir_clean(root)


# ---------- refuzuri înainte de orice scriere ----------

def test_git_checkout_detection_accepts_a_folder_or_a_file(tmp_path):
    """O copie git are .git folder sau fișier (worktree, submodul)."""
    assert not is_git_checkout(tmp_path)
    (tmp_path / ".git").write_text("gitdir: ../alt\n", encoding="utf-8")  # worktree / submodul
    assert is_git_checkout(tmp_path)


def test_a_git_checkout_is_refused_and_nothing_is_written(program, tmp_path):
    """Într-o copie git actualizarea e refuzată și nu se scrie nimic, nici .actualizare (D9)."""
    (program / ".git").mkdir()
    before = fingerprint(program, skip=())
    with pytest.raises(UpdateError, match="copie git: actualizează cu git pull"):
        apply_update(release(tmp_path), program, NEW)
    assert fingerprint(program, skip=()) == before


@pytest.mark.parametrize("version", [OLD, "1.4.1", "0.9.9"], ids=["aceeasi", "mai-veche", "mult-mai-veche"])
def test_the_same_or_an_older_version_is_refused(program, tmp_path, version):
    """Aceeași versiune sau una mai veche se refuză (fără downgrade, D6), fără nicio schimbare și fără „instalez”.

    Versiunea instalată se citește sub lacăt (P2), deci după refuz în .actualizare există doar fișierul-lacăt gol (permanent, N5).
    """
    archive = write_archive(tmp_path / "a.zip", version, program_files(version))
    before = fingerprint(program, skip=())
    stages = []
    with pytest.raises(UpdateError, match="nu e mai nouă"):
        apply_update(archive, program, version, progress=stages.append)
    assert _without_lock(fingerprint(program, skip=())) == before and stages == []
    assert_work_dir_clean(program)


def test_an_expected_version_that_is_not_x_y_z_is_refused(program, tmp_path):
    """Versiunea așteptată trebuie să fie X.Y.Z."""
    with pytest.raises(UpdateError, match="X.Y.Z"):
        apply_update(release(tmp_path), program, "1.5")


def test_the_installed_version_must_be_readable(program, tmp_path):
    """Fără VERSION citibil în version.py-ul instalat, aplicarea se refuză."""
    (program / "emag_spend" / "version.py").write_text("VERSION = calcul()\n", encoding="utf-8")
    with pytest.raises(UpdateError, match="Nu găsesc versiunea instalată"):
        apply_update(release(tmp_path), program, NEW)


def _refused(program, archive, match):
    """Aplicarea trebuie refuzată cu mesajul dat, fără să schimbe nimic în rădăcină și fără resturi în .actualizare (în afară de lacăt)."""
    before = fingerprint(program)
    with pytest.raises(UpdateError, match=match):
        apply_update(archive, program, NEW)
    assert fingerprint(program) == before, "un refuz a schimbat rădăcina programului"
    assert_work_dir_clean(program)


def _entry(name, mode=0o100644):
    """O intrare de arhivă capcană, cu modul Unix dat."""
    info = zipfile.ZipInfo(name, date_time=(2026, 10, 5, 12, 0, 0))
    info.create_system = 3
    info.external_attr = mode << 16
    return info


TRAP_ENTRIES = {
    "in-afara-prefixului": ("altceva.txt", "nu e în folderul"),
    "absolut-fara-prefix": ("/etc/evadat", "nu e în folderul"),
    "absolut-dupa-prefix": (PREFIX + "/etc/evadat", "cale absolută"),
    "punct-punct": (PREFIX + "../evadat.txt", "«..»"),
    "punct-punct-adanc": (PREFIX + "emag_spend/../../evadat.txt", "«..»"),
    "punct": (PREFIX + "./x.txt", "«..»"),
    "componenta-goala": (PREFIX + "docs//x.md", "componentă goală"),
    "litera-de-unitate": (PREFIX + "C:/evadat.txt", "caracterul «:»"),
    "flux-ntfs": (PREFIX + "ruleaza.py::$DATA", "caracterul «:»"),
    "CON": (PREFIX + "CON", "rezervat"),
    "nul-cu-extensie": (PREFIX + "docs/nul.txt", "rezervat"),
    "aux-mic": (PREFIX + "aux.md", "rezervat"),
    "COM1": (PREFIX + "COM1.py", "rezervat"),
    "LPT9": (PREFIX + "docs/lpt9", "rezervat"),
    "COM-superscript": (PREFIX + "COM¹.txt", "rezervat"),
    "con-cu-spatiu": (PREFIX + "con .txt", "rezervat"),
    "punct-la-final": (PREFIX + "docs/fisier.", "punct sau spațiu"),
    "spatiu-la-final": (PREFIX + "docs/fisier ", "punct sau spațiu"),
    "nume-scurt-8.3": (PREFIX + "config/CATEGO~1.JSO", "nume scurt"),
    "tab": (PREFIX + "docs/a\tb.md", "control"),
    "semn-intrebare": (PREFIX + "docs/a?.md", "caracterul"),
    "bara-verticala": (PREFIX + "docs/a|b.md", "caracterul"),
    "ghilimele": (PREFIX + 'docs/a"b.md', "caracterul"),
    "mai-mic": (PREFIX + "docs/a<b.md", "caracterul"),
}


@pytest.mark.parametrize("name, reason", TRAP_ENTRIES.values(), ids=TRAP_ENTRIES.keys())
def test_entries_with_forbidden_paths_refuse_the_whole_archive(program, tmp_path, name, reason):
    """Fiecare cale nepermisă (.., absolută, unitate, rezervată, 8.3, control) refuză toată arhiva, cu motivul ei."""
    archive = release(tmp_path, extra_entries=((_entry(name), b"capcana\n"),))
    _refused(program, archive, reason)


def _with_raw_name(data: bytes, placeholder: str, raw: str) -> bytes:
    """Arhiva cu un nume schimbat direct în octeți (zipfile nu poate scrie NUL sau «\\» în nume); aceeași lungime."""
    assert len(placeholder.encode()) == len(raw.encode()) and data.count(placeholder.encode()) == 2  # antet local + director central
    return data.replace(placeholder.encode(), raw.encode())


@pytest.mark.parametrize("raw, reason", [("ruleaza.py\x00.txt", "conține NUL"), ("docs\\..\\..\\x.md", "«\\\\»"), ("..\\..\\evadat.md", "«\\\\»")],
                         ids=["nul", "backslash-adanc", "backslash"])
def test_names_with_nul_or_backslash_are_refused(program, tmp_path, raw, reason):
    """zipfile taie numele la NUL și (pe Windows) face din «\\» «/»: numele real trebuie refuzat pentru ce e, nu pentru ce pare."""
    placeholder = "Z" * len(raw)
    data = archive_bytes(NEW, new_release_files(), extra_entries=((_entry(PREFIX + placeholder), b"capcana\n"),))
    archive = tmp_path / "capcana.zip"
    archive.write_bytes(_with_raw_name(data, placeholder, raw))
    _refused(program, archive, reason)


@pytest.mark.parametrize("mode, reason", [(0o120777, "legătură simbolică"), (0o010644, "fișier obișnuit"), (0o020644, "fișier obișnuit")],
                         ids=["symlink", "fifo", "dispozitiv"])
def test_links_and_special_files_are_refused(program, tmp_path, mode, reason):
    """Legăturile simbolice și fișierele speciale din arhivă se refuză."""
    archive = release(tmp_path, extra_entries=((_entry(PREFIX + "docs/legatura", mode), b"../../../evadat"),))
    _refused(program, archive, reason)


@pytest.mark.parametrize("duplicate", ["ruleaza.py", "RULEAZA.PY", "Ruleaza.py"])
def test_duplicate_entries_are_refused_even_with_other_letter_case(program, tmp_path, duplicate):
    # doar numele identic dă avertismentul zipfile «Duplicate name» la scriere; cele cu alte litere sunt, pentru zipfile, alte nume
    """Intrările duplicate se refuză, și cele care diferă doar prin litere mari/mici."""
    with pytest.warns(UserWarning) if duplicate == "ruleaza.py" else contextlib.nullcontext():
        archive = release(tmp_path, extra_entries=((_entry(PREFIX + duplicate), b"print('a doua')\n"),))
    _refused(program, archive, "de două ori")


def test_a_path_that_is_both_a_file_and_a_folder_is_refused(program, tmp_path):
    """O cale care e și fișier, și folder se refuză."""
    archive = release(tmp_path, extra_entries=((_entry(PREFIX + "ruleaza.py/x.txt"), b"x"),))
    _refused(program, archive, "și fișier, și folder")


def test_a_folder_entry_with_the_name_of_a_file_is_refused(program, tmp_path):
    """O intrare de folder cu numele unui fișier se refuză."""
    folder = _entry(PREFIX + "ruleaza.py/", 0o40755)
    archive = release(tmp_path, extra_entries=((folder, b""),))
    _refused(program, archive, "și fișier, și folder")


PROTECTED = ["iesiri/x/raport.html", "logs/a.log", ".profil_browser/Default/Cookies", ".uv/bin/uv", ".venv/pyvenv.cfg",
             ".actualizare/jurnal.json", ".git/config", "config/categorii.personal.json", "Config/Categorii.Personal.JSON",
             "IESIRI/x.html", "emag_spend/.git/config", ".Venv/x"]


@pytest.mark.parametrize("path", PROTECTED)
def test_an_archive_with_a_protected_path_is_refused_entirely(program, tmp_path, path):
    """O arhivă cu o cale protejată (D7) se refuză în întregime, fără litere mari/mici."""
    archive = release(tmp_path, new_release_files(extra={path: b"capcana\n"}))
    _refused(program, archive, "cale protejată")


def test_a_protected_folder_entry_is_refused_too(program, tmp_path):
    """Și o intrare de folder protejat se refuză."""
    archive = release(tmp_path, extra_entries=((_entry(PREFIX + "iesiri/", 0o40755), b""),))
    _refused(program, archive, "cale protejată")


@pytest.mark.parametrize("required", update_archive.REQUIRED_FILES)
def test_each_required_file_must_be_in_the_archive(program, tmp_path, required):
    """Fiecare fișier obligatoriu (version.py, manifest, ruleaza.py, lansatoarele, recuperarea) trebuie să existe."""
    files = new_release_files(without=(required,))
    archive = release(tmp_path, files)
    if required == MANIFEST:  # archive_bytes pune mereu manifestul: aici îl scoatem din arhivă
        data = archive.read_bytes()
        archive = tmp_path / "fara_manifest.zip"
        with zipfile.ZipFile(archive, "w") as clean, zipfile.ZipFile(io.BytesIO(data)) as source:
            for info in source.infolist():
                if info.filename != PREFIX + MANIFEST:
                    clean.writestr(info, source.read(info))
    _refused(program, archive, "nu conține")


def test_the_files_that_installed_versions_rely_on_are_required_in_every_archive():
    """N7: fișierele-contract cu versiunile deja instalate (lansatorul vechi le cheamă pe cele noi; recuperarea rulează prima) sunt obligatorii."""
    contract = {"instalare/dupa_rulare.bat", "instaleaza.bat", "instalare/mediu.bat", "instalare/mediu.sh", "instalare/pregatire.sh",
                "emag_spend/__init__.py", "emag_spend/update_recovery.py", "emag_spend/update_lock.py",
                "ruleaza.py", "porneste.bat", "porneste.sh", "porneste.command", "emag_spend/version.py", MANIFEST}
    missing = contract - set(update_archive.REQUIRED_FILES)
    assert not missing, f"lipsesc din update_archive.REQUIRED_FILES: {sorted(missing)}"


@pytest.mark.parametrize("source, found", [('VERSION = "9.9.9"\n', "9.9.9"), ("X = 1\n", "necunoscută"), ('VERSION = "1.5.0" +\n', "necunoscută"),
                                           ('VERSION: str = "1.4.9"\n', "1.4.9")])
def test_the_version_inside_the_archive_must_be_the_expected_one(program, tmp_path, source, found):
    """VERSION din arhivă trebuie să fie exact versiunea așteptată."""
    files = new_release_files(extra={"emag_spend/version.py": source.encode("utf-8")})
    _refused(program, release(tmp_path, files), f"versiunea «{found}»")


def test_the_version_file_is_read_without_running_it(tmp_path):
    """version.py din arhivă se citește din AST, fără să fie executat."""
    trap = tmp_path / "executat.txt"
    source = f'open({str(trap)!r}, "w").close()\nVERSION = "1.5.0"\n'
    assert update_archive.version_from_source(source) == "1.5.0" and not trap.exists()


@pytest.mark.parametrize("manifest, detail", [
    (lambda files: manifest_bytes([*files, "nu_exista.txt"]), "nu_exista.txt"),
    (lambda files: manifest_bytes([name for name in files if name != "ruleaza.py"]), "lipsește din listă «ruleaza.py»"),
    (lambda files: manifest_bytes(files) + b"../evadat\n", "«..»"),
    (lambda files: manifest_bytes(files) + b"ruleaza.py\n", "de două ori"),
    (lambda files: manifest_bytes(files).replace(b"\n", b"\r\n"), "control"),
    (lambda files: b"\xff\xfe" + manifest_bytes(files), "utf-8"),
], ids=["fisier-in-plus", "fisier-lipsa", "cale-nepermisa", "duplicat", "crlf", "nu-e-utf8"])
def test_the_new_manifest_must_match_the_archive_exactly(program, tmp_path, manifest, detail):
    """Manifestul nou trebuie să fie exact lista fișierelor arhivei, LF, fără căi nepermise."""
    files = new_release_files()
    _refused(program, release(tmp_path, files, manifest=manifest(files)), detail)


def test_too_many_entries_are_refused(program, tmp_path, monkeypatch):
    """Peste limita de intrări, arhiva se refuză."""
    monkeypatch.setattr(update_archive, "MAX_ARCHIVE_ENTRIES", 5)
    _refused(program, release(tmp_path), "prea multe intrări")


def test_too_many_unpacked_bytes_are_refused(program, tmp_path, monkeypatch):
    """Peste limita de octeți dezarhivați, arhiva se refuză."""
    monkeypatch.setattr(update_archive, "MAX_UNPACKED_BYTES", 100)
    _refused(program, release(tmp_path), "prea mare după dezarhivare")


def test_metadata_files_that_are_too_big_are_refused(program, tmp_path, monkeypatch):
    """version.py sau manifestul peste limită nu se citesc în memorie."""
    monkeypatch.setattr(update_archive, "MAX_METADATA_BYTES", 10)
    _refused(program, release(tmp_path), "prea mare")


def test_an_encrypted_entry_is_refused():
    """O intrare criptată se refuză înainte de citire."""
    with zipfile.ZipFile(io.BytesIO(archive_bytes(NEW, new_release_files()))) as archive:
        archive.getinfo(PREFIX + "ruleaza.py").flag_bits |= update_archive.ZIP_ENCRYPTED_FLAG
        with pytest.raises(UpdateError, match="criptată"):
            update_archive.validate_archive(archive, NEW)


def test_a_file_that_is_not_a_zip_is_refused(program, tmp_path):
    """Un fișier care nu e ZIP se refuză fără să schimbe nimic."""
    archive = tmp_path / "nu_e_zip.zip"
    archive.write_bytes(b"nu e o arhiva, doar text inventat")
    _refused(program, archive, "nu e un fișier ZIP valid")


def _corrupt_member(data: bytes, name: str) -> bytes:
    """Strică un octet din datele comprimate ale intrării `name` (CRC-ul nu se mai potrivește la citire)."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        info = archive.getinfo(name)
    header = 30 + len(info.filename.encode("utf-8")) + len(info.extra)
    position = info.header_offset + header + info.compress_size // 2
    return data[:position] + bytes([data[position] ^ 0xFF]) + data[position + 1:]


@pytest.mark.parametrize("member", ["emag_spend/version.py", "docs/nou/pagina.md"], ids=["citit-la-validare", "citit-la-extragere"])
def test_a_damaged_archive_changes_nothing(program, tmp_path, member):
    """O arhivă deteriorată (la validare sau la extragere) nu schimbă nimic și nu lasă resturi."""
    padding = f'VERSION = "{NEW}"\n' + "# umplutură inventată, ca intrarea să aibă ce comprima\n" * 50
    files = new_release_files(extra={member: padding.encode("utf-8")})
    archive = tmp_path / "stricata.zip"
    archive.write_bytes(_corrupt_member(archive_bytes(NEW, files), PREFIX + member))
    _refused(program, archive, "deteriorată")


def test_a_folder_in_the_place_of_a_new_file_is_refused(program, tmp_path):
    """Un folder al utilizatorului în locul unui fișier nou oprește aplicarea, fără să-l mute."""
    (program / ADDED_IN_NEW).mkdir(parents=True)
    (program / ADDED_IN_NEW / "al_meu.txt").write_text("x", encoding="utf-8")
    _refused(program, release(tmp_path), "există un folder")


def test_a_user_file_in_the_place_of_a_new_folder_is_refused(program, tmp_path):
    """Un fișier al utilizatorului (nelistat în manifest) în locul unui folder nou oprește aplicarea, fără să-l mute."""
    (program / "docs" / "nou").write_text("al utilizatorului\n", encoding="utf-8")
    _refused(program, release(tmp_path), "există un fișier")


# ---------- legături și joncțiuni: nu se urmează niciodată (N4, S1) ----------

def test_a_program_folder_that_is_a_link_elsewhere_is_refused(program, tmp_path):
    """Un folder al programului care e legătură spre alt loc oprește aplicarea; ținta rămâne neatinsă."""
    outside, outside_before = outside_folder(tmp_path)
    for child in (program / "docs").iterdir():
        child.unlink()
    (program / "docs").rmdir()
    make_link(outside, program / "docs")
    try:
        _refused(program, release(tmp_path), "legătură spre alt loc")
        assert fingerprint(outside, skip=()) == outside_before
    finally:
        remove_link(program / "docs")


def test_a_link_in_the_place_of_a_file_to_write_is_refused_and_its_target_is_untouched(program, tmp_path):
    """S1/J1: o joncțiune în locul unui fișier rescris de versiunea nouă oprește aplicarea; folderul spre care arată rămâne întreg."""
    outside, outside_before = outside_folder(tmp_path)
    (program / REWRITTEN).unlink()
    make_link(outside, program / REWRITTEN)
    try:
        _refused(program, release(tmp_path), "legătură")
        assert fingerprint(outside, skip=()) == outside_before, "aplicarea a atins folderul din afara programului"
    finally:
        remove_link(program / REWRITTEN)


def test_a_link_in_the_place_of_a_file_to_delete_is_skipped_and_its_target_is_untouched(program, tmp_path):
    """S1/J2: o joncțiune în locul unui fișier scos din versiunea nouă nu se mută și nu se urmează; aplicarea reușește."""
    outside, outside_before = outside_folder(tmp_path)
    (program / DELETED_IN_NEW).unlink()
    make_link(outside, program / DELETED_IN_NEW)
    try:
        result = apply_update(release(tmp_path), program, NEW)
        assert result.deleted == 0, "legătura nu e un fișier al programului: nu se șterge"
        assert fingerprint(outside, skip=()) == outside_before, "curățenia a golit folderul din afara programului"
        assert fingerprint(program)[DELETED_IN_NEW] == LINK_MARK, "legătura trebuia lăsată pe loc"
        assert_work_dir_clean(program)
    finally:
        remove_link(program / DELETED_IN_NEW)


def test_old_manifest_files_under_a_linked_folder_are_never_deleted(program, tmp_path):
    """N8d: manifestul vechi listează un fișier de sub un folder-joncțiune: nimic nu se șterge prin legătură."""
    outside, _ = outside_folder(tmp_path)
    (outside / "vechi.md").write_text("al altcuiva\n", encoding="utf-8")
    outside_before = fingerprint(outside, skip=())
    make_link(outside, program / "extra")
    _add_to_local_manifest(program, ["extra/vechi.md"])
    try:
        apply_update(release(tmp_path), program, NEW)
        assert not (program / DELETED_IN_NEW).exists(), "manifestul local trebuia folosit (altfel testul n-ar dovedi nimic)"
        assert fingerprint(outside, skip=()) == outside_before, "un fișier a fost șters prin legătură"
    finally:
        remove_link(program / "extra")


@pytest.mark.parametrize("linked", [".actualizare", ".actualizare/nou", ".actualizare/vechi", ".actualizare/copie", ".actualizare/descarcari"])
def test_a_work_folder_that_is_a_link_is_refused_and_its_target_is_untouched(program, tmp_path, linked):
    """N8b, S1/J3, P8: .actualizare (sau nou/, vechi/, copie/, descarcari/ din el) legătură spre alt loc → refuz; ținta rămâne neatinsă."""
    outside, outside_before = outside_folder(tmp_path)
    (program / linked).parent.mkdir(parents=True, exist_ok=True)
    make_link(outside, program / linked)
    before = fingerprint(program)
    try:
        with pytest.raises(UpdateError, match="legătură"):
            apply_update(release(tmp_path), program, NEW)
        assert fingerprint(program) == before
        assert fingerprint(outside, skip=()) == outside_before, "aplicarea a scris sau a șters în folderul spre care arată legătura"
    finally:
        remove_link(program / linked)


def test_an_apply_with_a_pending_journal_refuses_a_linked_backup_folder_before_reverting(program, tmp_path):
    """N4: jurnal „aplicare” rămas și .actualizare/vechi legătură spre alt loc: aplicarea refuză ÎNAINTE să revină (revenirea ar
    muta în program fișiere din folderul spre care arată legătura)."""
    outside, outside_before = outside_folder(tmp_path)
    work = program / update_apply.WORK_DIR_NAME
    _journal(work, sterse=["important.txt"])
    make_link(outside, work / update_apply.OLD_DIR_NAME)
    before = fingerprint(program)
    try:
        with pytest.raises(UpdateError, match="legătură"):
            apply_update(release(tmp_path), program, NEW)
        assert fingerprint(program) == before and fingerprint(outside, skip=()) == outside_before
    finally:
        remove_link(work / update_apply.OLD_DIR_NAME)


def test_recovery_refuses_a_work_folder_that_is_a_link(tmp_path):
    """N4: o recuperare cu .actualizare/nou legătură spre alt loc se refuză; nici programul, nici ținta nu se ating."""
    root = tmp_path / "program"
    install_program(root, OLD)
    outside, outside_before = outside_folder(tmp_path)
    work = root / update_apply.WORK_DIR_NAME
    _journal(work, scrise=["ruleaza.py"], existau=[])
    make_link(outside, work / update_apply.NEW_DIR_NAME)
    before = fingerprint(root)
    try:
        with pytest.raises(UpdateError, match="legătură"):
            recover_interrupted(root)
        assert fingerprint(root) == before and fingerprint(outside, skip=()) == outside_before
    finally:
        remove_link(work / update_apply.NEW_DIR_NAME)


# ---------- fișier ↔ folder între versiuni (N6, C3) ----------

FILE_TO_FOLDER = {"docs/ghid.md/index.md": "ghidul devine folder\n".encode("utf-8")}  # docs/ghid.md era fișier în versiunea veche
FOLDER_TO_FILE_OLD = {"docs/vechi/a.md": b"a\n", "docs/vechi/sub/b.md": b"b\n"}
FOLDER_TO_FILE_NEW = {"docs/vechi": "folderul devine fișier\n".encode("utf-8")}


def _install_transition(root, transition):
    """Programul vechi pentru o trecere fișier ↔ folder; pentru folder → fișier, și un subfolder gol (nu apare în manifest)."""
    install_program(root, OLD, program_files(OLD, extra=FOLDER_TO_FILE_OLD) if transition == "folder-in-fisier" else None)
    if transition == "folder-in-fisier":
        (root / "docs" / "vechi" / "gol").mkdir()


def _transition_files(transition):
    """Fișierele versiunii noi pentru trecerea cerută."""
    return new_release_files(extra=FILE_TO_FOLDER if transition == "fisier-in-folder" else FOLDER_TO_FILE_NEW)


@pytest.mark.parametrize("transition", ["fisier-in-folder", "folder-in-fisier"])
def test_a_file_that_becomes_a_folder_or_back_installs(tmp_path, transition):
    """N6: o versiune care face dintr-un fișier al programului un folder (sau invers) se instalează."""
    root = tmp_path / "program"
    _install_transition(root, transition)
    files = _transition_files(transition)
    apply_update(release(tmp_path, files), root, NEW)
    for name, data in files.items():
        assert (root / name).read_bytes() == data, f"{name} nu are conținutul versiunii noi"
    assert not any(name in fingerprint(root) for name in FOLDER_TO_FILE_OLD), "fișierele vechi din folder trebuiau scoase"
    assert_work_dir_clean(root)


@pytest.mark.parametrize("transition", ["fisier-in-folder", "folder-in-fisier"])
def test_a_file_folder_transition_reverts_after_a_failure_at_any_move(tmp_path, monkeypatch, transition):
    """N6: la eșecul oricărui os.replace din aplicare, trecerea fișier ↔ folder se anulează octet cu octet (și subfolderul gol revine)."""
    real = os.replace
    counter = tmp_path / "numarare"
    _install_transition(counter, transition)
    spy = _ReplaceSpy(real)
    monkeypatch.setattr(os, "replace", spy)
    apply_update(release(tmp_path / "n", _transition_files(transition)), counter, NEW)
    monkeypatch.setattr(os, "replace", real)
    for k in range(1, spy.calls + 1):
        root = tmp_path / f"program_{k}"
        _install_transition(root, transition)
        before = fingerprint(root)
        monkeypatch.setattr(os, "replace", _ReplaceSpy(real, k, OSError(errno.EIO, "eroare inventată de disc")))
        with pytest.raises(UpdateError, match="am revenit la versiunea 1.4.2"):
            apply_update(release(tmp_path / f"a{k}", _transition_files(transition)), root, NEW)
        monkeypatch.setattr(os, "replace", real)
        assert fingerprint(root) == before, f"după eșecul la os.replace nr. {k}, trecerea {transition} nu s-a anulat"
        assert_work_dir_clean(root)


@pytest.mark.parametrize("transition", ["fisier-in-folder", "folder-in-fisier"])
def test_a_file_folder_transition_interrupted_anywhere_is_reverted_at_the_next_start(tmp_path, monkeypatch, transition):
    """N6: o cădere la oricare os.replace în timpul unei treceri fișier ↔ folder se anulează la pornirea următoare."""
    real = os.replace
    counter = tmp_path / "numarare"
    _install_transition(counter, transition)
    spy = _ReplaceSpy(real)
    monkeypatch.setattr(os, "replace", spy)
    apply_update(release(tmp_path / "n", _transition_files(transition)), counter, NEW)
    monkeypatch.setattr(os, "replace", real)
    for k in range(2, spy.calls + 1):
        root = tmp_path / f"program_{k}"
        _install_transition(root, transition)
        before = fingerprint(root)
        _crash_at(monkeypatch, k, lambda: apply_update(release(tmp_path / f"a{k}", _transition_files(transition)), root, NEW))
        recover_interrupted(root)
        assert fingerprint(root) == before, f"după căderea la os.replace nr. {k}, trecerea {transition} nu s-a anulat"
        assert_work_dir_clean(root)


def test_a_folder_with_a_user_file_in_the_place_of_a_new_file_is_still_refused(tmp_path):
    """N6: folderul care devine fișier se acceptă doar dacă tot ce e în el e al programului; un fișier al utilizatorului îl oprește."""
    root = tmp_path / "program"
    _install_transition(root, "folder-in-fisier")
    (root / "docs" / "vechi" / "al_meu.txt").write_text("al utilizatorului\n", encoding="utf-8")
    _refused(root, release(tmp_path, _transition_files("folder-in-fisier")), "există un folder")


# ---------- lungimea căilor pe Windows ----------

def test_path_length_check_uses_the_deepest_path_in_the_backup_folder():
    """Limita de 259 de caractere se verifică pe calea din .actualizare/vechi (cea mai adâncă), doar pe Windows."""
    root = "C:\\" + "r" * 100
    fits = "d/" + "x" * (update_apply.WINDOWS_MAX_PATH - 1 - len(root) - 3 - len(".actualizare") - len("vechi") - 2)
    check_path_lengths(root, ["scurt.txt", fits], windows=True)
    with pytest.raises(UpdateError, match=r"C:\\cheltuieli-emag") as refused:
        check_path_lengths(root, ["scurt.txt", fits + "y"], windows=True)
    assert "prea lungă pentru Windows" in str(refused.value) and fits + "y" in str(refused.value)
    check_path_lengths(root, [fits + "y" * 500], windows=False)


def test_apply_checks_path_lengths_with_writes_and_deletions(program, tmp_path, monkeypatch):
    """Aplicarea verifică lungimea și pentru fișierele scrise, și pentru cele șterse."""
    seen = {}

    def spy(root, relatives, *, windows):
        """Notează cum a fost chemată verificarea lungimii căilor."""
        seen.update(root=root, relatives=list(relatives), windows=windows)

    monkeypatch.setattr(update_apply, "check_path_lengths", spy)
    apply_update(release(tmp_path), program, NEW)
    assert seen["windows"] == (os.name == "nt") and DELETED_IN_NEW in seen["relatives"] and ADDED_IN_NEW in seen["relatives"]


@pytest.mark.skipif(os.name != "nt", reason="limita clasică de cale există doar pe Windows")
def test_a_too_long_path_on_windows_refuses_before_writing(program, tmp_path, monkeypatch):
    """Pe Windows, o cale prea lungă oprește aplicarea înainte de orice scriere."""
    monkeypatch.setattr(update_apply, "WINDOWS_MAX_PATH", len(str(program.resolve())) + 30)
    _refused(program, release(tmp_path), "prea lungă pentru Windows")


# ---------- revenirea după o eroare ----------

class _ReplaceSpy:
    """os.replace care numără apelurile și, la al `fail_at`-lea, ridică `error` (o singură dată); altfel mută de-adevăratelea."""

    def __init__(self, real, fail_at=None, error=None):
        """`real` = os.replace adevărat; fără `fail_at` doar numără."""
        self.real, self.fail_at, self.error, self.calls = real, fail_at, error, 0

    def __call__(self, source, target):
        """Numără apelul, ridică eroarea la apelul ales, altfel mută."""
        self.calls += 1
        if self.calls == self.fail_at:
            raise self.error
        return self.real(source, target)


def _count_replaces(tmp_path, monkeypatch) -> int:
    """Câte os.replace face o aplicare reușită a aceleiași arhive (jurnalul, mutările, încă un jurnal)."""
    root = tmp_path / "numarare"
    install_program(root, OLD)
    spy = _ReplaceSpy(os.replace)
    monkeypatch.setattr(os, "replace", spy)
    apply_update(release(tmp_path / "n"), root, NEW)
    monkeypatch.undo()
    _no_pauses(monkeypatch)
    return spy.calls


def test_a_failure_at_any_os_replace_reverts_everything_byte_for_byte(tmp_path, monkeypatch):
    """Eșec la oricare os.replace → revenire completă, octet cu octet, fără resturi."""
    real = os.replace
    total = _count_replaces(tmp_path, monkeypatch)
    assert total >= 2 + len(new_release_files()), "numărarea nu a văzut mutările: testul n-ar dovedi nimic"
    for k in range(1, total + 1):
        root = tmp_path / f"program_{k}"
        install_program(root, OLD)
        add_user_data(root)
        before = fingerprint(root)
        archive = release(tmp_path / f"a{k}")
        monkeypatch.setattr(os, "replace", _ReplaceSpy(real, k, OSError(errno.EIO, "eroare inventată de disc")))
        with pytest.raises(UpdateError, match="am revenit la versiunea 1.4.2") as refused:
            apply_update(archive, root, NEW)
        monkeypatch.setattr(os, "replace", real)
        assert fingerprint(root) == before, f"după eșecul la os.replace nr. {k}, rădăcina nu e ca înainte"
        assert_work_dir_clean(root)
        assert str(tmp_path) not in str(refused.value), "mesajul conține calea absolută (cu numele contului)"


@pytest.mark.parametrize("position", ["primul", "mijloc", "ultimul"])
def test_ctrl_c_during_the_moves_reverts_and_then_propagates(tmp_path, monkeypatch, position):
    """Ctrl+C în timpul mutărilor: întâi revenire completă, apoi KeyboardInterrupt merge mai departe."""
    real = os.replace
    total = _count_replaces(tmp_path, monkeypatch)
    k = {"primul": 1, "mijloc": total // 2, "ultimul": total}[position]
    root = tmp_path / "program"
    install_program(root, OLD)
    add_user_data(root)
    before = fingerprint(root)
    archive = release(tmp_path / "a")
    monkeypatch.setattr(os, "replace", _ReplaceSpy(real, k, KeyboardInterrupt()))
    with pytest.raises(KeyboardInterrupt):
        apply_update(archive, root, NEW)
    monkeypatch.setattr(os, "replace", real)
    assert fingerprint(root) == before
    assert_work_dir_clean(root)


def test_a_short_permission_error_is_retried_and_the_update_succeeds(program, tmp_path, monkeypatch):
    """O PermissionError scurtă (antivirus) se reîncearcă și aplicarea reușește."""
    real, blocked = os.replace, []

    def antivirus(source, target):
        """Blochează de două ori punerea la loc a lui ruleaza.py, ca un antivirus."""
        if str(target).endswith("ruleaza.py") and update_apply.OLD_DIR_NAME not in str(target) and len(blocked) < 2:
            blocked.append(target)
            raise PermissionError(errno.EACCES, "folosit de antivirus")
        return real(source, target)

    monkeypatch.setattr(os, "replace", antivirus)
    apply_update(release(tmp_path), program, NEW)
    assert len(blocked) == 2 and (program / "ruleaza.py").read_bytes() == new_release_files()["ruleaza.py"]


def test_a_permanent_permission_error_reverts(program, tmp_path, monkeypatch):
    """Un fișier blocat permanent → revenire completă și mesaj."""
    real = os.replace

    def locked(source, target):
        """Versiunea nouă a lui porneste.bat nu poate fi pusă la loc (doar mutarea din .actualizare/nou e blocată)."""
        if str(target).endswith("porneste.bat") and f"{os.sep}{update_apply.NEW_DIR_NAME}{os.sep}" in str(source):
            raise PermissionError(errno.EACCES, "folosit de alt program")
        return real(source, target)

    before = fingerprint(program)
    monkeypatch.setattr(os, "replace", locked)
    with pytest.raises(UpdateError, match="am revenit"):
        apply_update(release(tmp_path), program, NEW)
    monkeypatch.setattr(os, "replace", real)
    assert fingerprint(program) == before


def test_the_error_message_names_the_blocked_program_file_not_its_copy_in_the_work_folder(program, tmp_path, monkeypatch):
    """P4: os.replace pune sursa (.actualizare/nou/…) în `filename` și ținta (fișierul din program) în `filename2`; mesajul numește
    fișierul din program, pe care utilizatorul îl poate închide, fără calea absolută."""
    real = os.replace

    def locked(source, target):
        """Ca sistemul: fișierul porneste.bat din program e ținut deschis, eroarea are sursa și ținta."""
        if os.path.normcase(os.fspath(target)) == os.path.normcase(os.fspath(program / "porneste.bat")):
            raise PermissionError(errno.EACCES, "Access is denied", os.fspath(source), None, os.fspath(target))
        return real(source, target)

    monkeypatch.setattr(os, "replace", locked)
    with pytest.raises(UpdateError, match="am revenit") as refused:
        apply_update(release(tmp_path), program, NEW)
    message = str(refused.value)
    assert "Access is denied: porneste.bat)" in message and update_apply.WORK_DIR_NAME not in message, message
    assert str(tmp_path) not in message, "mesajul conține calea absolută (cu numele contului)"


def test_an_error_on_a_work_folder_path_only_is_still_named(tmp_path):
    """P4: când eroarea are doar o cale din .actualizare (de ex. jurnalul), mesajul o numește pe aceea, relativă la program."""
    root = tmp_path / "program"
    error = OSError(errno.EIO, "eroare inventată de disc", str(root / update_apply.WORK_DIR_NAME / update_apply.JOURNAL_NAME))
    assert update_apply._describe(error, root) == f"eroare inventată de disc: {update_apply.WORK_DIR_NAME}/{update_apply.JOURNAL_NAME}"
    moved_out = OSError(errno.EACCES, "folosit", str(root / "ruleaza.py"), None, str(root / update_apply.WORK_DIR_NAME / "vechi" / "ruleaza.py"))
    assert update_apply._describe(moved_out, root) == "folosit: ruleaza.py", "la mutarea în vechi/ blocat e fișierul din program (sursa)"


@pytest.mark.skipif(os.name != "nt", reason="un fișier ținut deschis blochează înlocuirea lui doar pe Windows")
def test_a_program_file_held_open_is_named_in_the_message(program, tmp_path):
    """P4 la execuție (Windows): porneste.bat ținut deschis (editor, antivirus) → revenire completă, iar mesajul numește porneste.bat."""
    before = fingerprint(program)
    with open(program / "porneste.bat", "rb"):
        with pytest.raises(UpdateError, match="am revenit") as refused:
            apply_update(release(tmp_path), program, NEW)
    assert ": porneste.bat)" in str(refused.value) and update_apply.WORK_DIR_NAME not in str(refused.value), str(refused.value)
    assert fingerprint(program) == before
    assert_work_dir_clean(program)


# ---------- un fișier „doar citire” al programului (Windows, P3) ----------

READ_ONLY = "README.md"  # un fișier al programului, în ambele versiuni, marcat „doar citire” (copiat de pe un CD, dintr-o copie de siguranță)


def _read_only_program(root):
    """Programul OLD cu README.md „doar citire”; întoarce fișierele lui."""
    files = program_files(OLD, extra={READ_ONLY: b"readme vechi, inventat\n"})
    install_program(root, OLD, files)
    os.chmod(root / READ_ONLY, stat.S_IREAD)
    return files


def _has_read_only_attribute(path) -> bool:
    """True dacă fișierul are atributul Windows „doar citire”."""
    return bool(os.stat(path).st_file_attributes & stat.FILE_ATTRIBUTE_READONLY)


def _read_only_release_files():
    """Versiunea NEW, cu README.md schimbat."""
    return new_release_files(extra={READ_ONLY: b"readme nou, inventat\n"})


@pytest.mark.skipif(os.name != "nt", reason="atributul „doar citire” care blochează os.replace există doar pe Windows")
def test_a_read_only_program_file_does_not_block_the_update(tmp_path):
    """P3: MoveFileEx nu înlocuiește o țintă „doar citire”; aplicarea scoate atributul (copia de siguranță există) și reușește."""
    root = tmp_path / "program"
    _read_only_program(root)
    apply_update(release(tmp_path, _read_only_release_files()), root, NEW)
    assert (root / READ_ONLY).read_bytes() == b"readme nou, inventat\n" and (root / REWRITTEN).read_bytes() == new_release_files()[REWRITTEN]
    assert_work_dir_clean(root)


@pytest.mark.skipif(os.name != "nt", reason="atributul „doar citire” care blochează os.replace există doar pe Windows")
@pytest.mark.parametrize("ending", ["revenire-in-proces", "cadere-si-recuperare"])
def test_a_forced_revert_puts_back_a_read_only_file_with_its_attribute(tmp_path, monkeypatch, ending):
    """P3: aplicarea pică la ultima mutare (după ce README.md „doar citire” a fost înlocuit) sau procesul cade acolo: după revenire
    (în proces, sau la pornirea următoare) rădăcina e identică, octet cu octet, iar README.md are din nou atributul „doar citire”."""
    real = os.replace
    counter = tmp_path / "numarare"
    _read_only_program(counter)
    spy = _ReplaceSpy(real)
    monkeypatch.setattr(os, "replace", spy)
    apply_update(release(tmp_path / "n", _read_only_release_files()), counter, NEW)
    monkeypatch.setattr(os, "replace", real)
    root = tmp_path / "program"
    _read_only_program(root)
    before = fingerprint(root)
    archive = release(tmp_path / "a", _read_only_release_files())
    if ending == "revenire-in-proces":
        monkeypatch.setattr(os, "replace", _ReplaceSpy(real, spy.calls, OSError(errno.EIO, "eroare inventată de disc")))
        with pytest.raises(UpdateError, match="am revenit la versiunea 1.4.2"):
            apply_update(archive, root, NEW)
        monkeypatch.setattr(os, "replace", real)
    else:
        _crash_at(monkeypatch, spy.calls, lambda: apply_update(archive, root, NEW))
        assert "am revenit la versiunea 1.4.2" in recover_interrupted(root)
    assert fingerprint(root) == before, "după revenire rădăcina nu e ca înainte"
    assert _has_read_only_attribute(root / READ_ONLY), "revenirea a pus la loc README.md fără atributul „doar citire”"
    assert_work_dir_clean(root)


def test_a_read_only_file_gets_a_full_copy_as_backup_never_a_hard_link(program, monkeypatch):
    """P3: atributul „doar citire” e al fișierului, comun cu o legătură tare: copia de siguranță a unui astfel de fișier e întotdeauna
    o copie întreagă (shutil.copy2 păstrează atributul), altfel înlocuirea l-ar scoate și de pe copie, iar revenirea l-ar pierde."""
    linked = []
    monkeypatch.setattr(os, "link", lambda source, target: linked.append(source))
    monkeypatch.setattr(update_apply, "is_read_only", lambda path: True)
    update_apply._backup(program, "ruleaza.py")
    assert linked == [], "un fișier „doar citire” nu primește o legătură tare drept copie de siguranță"
    copy = program / update_apply.WORK_DIR_NAME / update_apply.OLD_DIR_NAME / "ruleaza.py"
    assert copy.read_bytes() == (program / "ruleaza.py").read_bytes() and not os.path.samefile(copy, program / "ruleaza.py")


def test_a_revert_that_cannot_finish_leaves_the_journal_for_the_next_start(program, tmp_path, monkeypatch):
    """Dacă nici revenirea nu se termină, jurnalul rămâne și pornirea următoare o termină."""
    real, state = os.replace, {"calls": 0}

    def broken(source, target):
        """Eșec la al 6-lea os.replace, apoi orice mutare din .actualizare/vechi pică (revenire imposibilă)."""
        state["calls"] += 1
        if state["calls"] == 6:
            raise OSError(errno.EIO, "eroare inventată")
        if state["calls"] > 6 and update_apply.OLD_DIR_NAME in str(source):
            raise OSError(errno.EIO, "disc blocat la revenire")
        return real(source, target)

    before = fingerprint(program)
    monkeypatch.setattr(os, "replace", broken)
    with pytest.raises(UpdateError, match="revenirea la versiunea 1.4.2 nu s-a terminat"):
        apply_update(release(tmp_path), program, NEW)
    monkeypatch.setattr(os, "replace", real)
    assert (program / update_apply.WORK_DIR_NAME / update_apply.JOURNAL_NAME).is_file()
    assert "am revenit la versiunea 1.4.2" in recover_interrupted(program)
    assert fingerprint(program) == before
    assert_work_dir_clean(program)


# ---------- recuperarea după o cădere (D11) ----------

class _Crash(BaseException):
    """Procesul „moare”: nici revenirea, nici curățenia nu mai apucă să ruleze."""


def _crash_at(monkeypatch, k, action):
    """Rulează `action` cu o „cădere” la al k-lea os.replace, fără revenirea din proces (ca un proces omorât); apoi readuce totul."""
    real = os.replace
    monkeypatch.setattr(os, "replace", _ReplaceSpy(real, k, _Crash()))
    monkeypatch.setattr(update_recovery, "revert", lambda *args: (_ for _ in ()).throw(_Crash()))
    with pytest.raises(_Crash):
        action()
    monkeypatch.undo()
    _no_pauses(monkeypatch)


def test_after_a_crash_at_any_point_the_next_start_reverts(tmp_path, monkeypatch):
    """Cădere (proces mort) la oricare os.replace → pornirea următoare revine la versiunea veche (D11).

    Mesajul de revenire apare doar dacă revenirea a schimbat ceva (N3): la căderea nr. 1 nici jurnalul n-a apucat să fie scris,
    iar la nr. 2 (prima punere la loc) nimic din rădăcină nu fusese încă înlocuit.
    """
    total = _count_replaces(tmp_path, monkeypatch)
    for k in range(1, total + 1):
        root = tmp_path / f"program_{k}"
        install_program(root, OLD)
        add_user_data(root)
        before = fingerprint(root)
        archive = release(tmp_path / f"a{k}")
        _crash_at(monkeypatch, k, lambda: apply_update(archive, root, NEW))
        message = recover_interrupted(root)
        expected = None if k <= 2 else update_apply.MESSAGE_RECOVERED.format(to_version=NEW, from_version=OLD)
        assert message == expected, f"la căderea nr. {k}: {message!r}"
        assert fingerprint(root) == before, f"după căderea la os.replace nr. {k}, recuperarea n-a refăcut versiunea veche"
        if k == 1:  # fără jurnal recuperarea nu atinge nimic; extragerea rămasă o șterge aplicarea următoare (test mai jos)
            continue
        assert_work_dir_clean(root)
        assert recover_interrupted(root) is None, "a doua pornire nu mai are nimic de făcut"


def _journal(work, **fields):
    """Scrie de mână un jurnal OLD → NEW (format 1) cu listele date."""
    write_journal_by_hand(work, OLD, NEW, **fields)


def test_recovery_from_a_hand_built_half_applied_state(tmp_path):
    """Recuperare dintr-o stare pe jumătate aplicată construită de mână, cu toate cazurile de fișier."""
    root = tmp_path / "program"
    install_program(root, OLD)
    before = fingerprint(root)
    work = root / update_apply.WORK_DIR_NAME
    new, old = work / update_apply.NEW_DIR_NAME, work / update_apply.OLD_DIR_NAME
    # ruleaza.py: vechiul în „vechi”, noul deja în rădăcină; porneste.bat: copia veche făcută, noul încă în „nou” (cădere între copie și
    # punerea la loc); docs/nou/pagina.md: fișier doar nou, deja mutat; docs/ghid.md: de șters, deja mutat în „vechi”; modul.py: neatins.
    (old / "docs").mkdir(parents=True)
    (new / "docs").mkdir(parents=True)
    os.replace(root / "ruleaza.py", old / "ruleaza.py")
    (root / "ruleaza.py").write_text("print('nou')\n", encoding="utf-8")
    os.link(root / "porneste.bat", old / "porneste.bat")
    (new / "porneste.bat").write_text("@echo nou\r\n", encoding="utf-8")
    (root / "docs" / "nou").mkdir()
    (root / "docs" / "nou" / "pagina.md").write_text("nou\n", encoding="utf-8")
    os.replace(root / "docs" / "ghid.md", old / "docs" / "ghid.md")
    (new / "emag_spend").mkdir()
    (new / "emag_spend" / "modul.py").write_text("# nou\n", encoding="utf-8")
    _journal(work, scrise=["docs/nou/pagina.md", "emag_spend/modul.py", "porneste.bat", "ruleaza.py"],
             existau=["emag_spend/modul.py", "porneste.bat", "ruleaza.py"], sterse=["docs/ghid.md"], foldere_noi=["docs/nou"])
    assert "am revenit la versiunea 1.4.2" in recover_interrupted(root)
    assert fingerprint(root) == before
    assert_work_dir_clean(root)


def test_an_interruption_before_any_file_was_replaced_reverts_silently(tmp_path):
    """N3: jurnal „aplicare”, dar nimic din rădăcină înlocuit încă (doar copia veche făcută): fără mesaj, programul neschimbat."""
    root = tmp_path / "program"
    install_program(root, OLD)
    before = fingerprint(root)
    work = root / update_apply.WORK_DIR_NAME
    (work / update_apply.OLD_DIR_NAME).mkdir(parents=True)
    (work / update_apply.NEW_DIR_NAME).mkdir()
    os.link(root / "ruleaza.py", work / update_apply.OLD_DIR_NAME / "ruleaza.py")  # copia de siguranță (N1), făcută înainte de mutare
    (work / update_apply.NEW_DIR_NAME / "ruleaza.py").write_text("print('nou')\n", encoding="utf-8")
    _journal(work, scrise=["ruleaza.py"], existau=["ruleaza.py"])
    assert recover_interrupted(root) is None, "nimic nu fusese schimbat: mesajul „a fost întreruptă; am revenit” ar fi fals"
    assert fingerprint(root) == before
    assert_work_dir_clean(root)


def test_after_a_revert_a_cleanup_that_fails_is_not_reported_again(tmp_path, monkeypatch):
    """N3, R2: revenirea reușește, dar .actualizare/nou nu se poate șterge (ținut deschis): jurnalul e șters primul, deci
    pornirea următoare nu mai spune „a fost întreruptă” (fără buclă de reporniri)."""
    root = tmp_path / "program"
    install_program(root, OLD)
    before = fingerprint(root)
    work = root / update_apply.WORK_DIR_NAME
    (work / update_apply.OLD_DIR_NAME).mkdir(parents=True)
    (work / update_apply.NEW_DIR_NAME).mkdir()
    os.replace(root / "ruleaza.py", work / update_apply.OLD_DIR_NAME / "ruleaza.py")
    (root / "ruleaza.py").write_text("print('nou')\n", encoding="utf-8")
    (work / update_apply.NEW_DIR_NAME / "tinut_deschis.txt").write_text("x", encoding="utf-8")
    _journal(work, scrise=["ruleaza.py"], existau=["ruleaza.py"])
    real_rmdir = os.rmdir

    def stuck(path, *args, **kwargs):
        """os.rmdir care nu poate scoate .actualizare/nou (un antivirus îl ține ocupat)."""
        if os.path.basename(os.fspath(path)) == update_apply.NEW_DIR_NAME:
            raise PermissionError(errno.EACCES, "folder ocupat (eroare inventată)")
        return real_rmdir(path, *args, **kwargs)

    monkeypatch.setattr(os, "rmdir", stuck)
    assert "am revenit la versiunea 1.4.2" in recover_interrupted(root)
    assert fingerprint(root) == before
    assert not (work / update_apply.JOURNAL_NAME).exists(), "jurnalul trebuia șters ÎNAINTEA folderelor de lucru (N3)"
    assert recover_interrupted(root) is None, "a doua pornire a spus din nou că actualizarea a fost întreruptă"
    monkeypatch.setattr(os, "rmdir", real_rmdir)
    assert fingerprint(root) == before
    apply_update(release(tmp_path), root, NEW)  # resturile rămase sunt inofensive: aplicarea următoare le șterge
    assert_work_dir_clean(root)


def test_a_journal_in_state_done_only_cleans_up(tmp_path):
    """Jurnal „gata” → doar curățenie, fără mesaj și fără să schimbe programul."""
    root = tmp_path / "program"
    install_program(root, NEW)
    work = root / update_apply.WORK_DIR_NAME
    (work / update_apply.OLD_DIR_NAME).mkdir(parents=True)
    (work / update_apply.OLD_DIR_NAME / "ruleaza.py").write_text("vechi", encoding="utf-8")
    _journal(work, stare="gata", scrise=["ruleaza.py"], existau=["ruleaza.py"])
    before = fingerprint(root)
    assert recover_interrupted(root) is None
    assert fingerprint(root) == before
    assert_work_dir_clean(root)


def _without_lock(found):
    """Amprenta fără fișierul-lacăt: recuperarea îl creează (gol, permanent) când ia lacătul, chiar dacă refuză apoi jurnalul."""
    return {name: value for name, value in found.items() if name not in (LOCK_FILE, os.path.dirname(LOCK_FILE))}


@pytest.mark.parametrize("content", ["{nu e json", json.dumps({"format": 2}), json.dumps({"format": 1, "stare": "aplicare"}),
                                     "JOURNAL_WITH_ESCAPE"], ids=["json-stricat", "alt-format", "fara-liste", "cale-in-afara"])
def test_a_damaged_journal_is_reported_and_nothing_is_touched(tmp_path, content):
    """Un jurnal deteriorat sau cu căi nepermise oprește recuperarea fără să atingă nimic."""
    root = tmp_path / "program"
    install_program(root, OLD)
    work = root / update_apply.WORK_DIR_NAME
    if content == "JOURNAL_WITH_ESCAPE":
        _journal(work, scrise=["../../evadat.txt"])
    else:
        work.mkdir()
        (work / update_apply.JOURNAL_NAME).write_text(content, encoding="utf-8")
    before = _without_lock(fingerprint(root, skip=()))
    with pytest.raises(UpdateError, match="Jurnalul actualizării"):
        recover_interrupted(root)
    assert _without_lock(fingerprint(root, skip=())) == before


@pytest.mark.parametrize("protected", ["iesiri/2026-10-05_12-00-00/raport.html", "config/categorii.personal.json", "logs/sesiune.log",
                                       ".venv/pyvenv.cfg"])
@pytest.mark.parametrize("journal_list", ["scrise", "sterse"])
def test_a_journal_that_lists_a_protected_path_is_damaged_and_the_user_file_stays(tmp_path, protected, journal_list):
    """N8c: un jurnal „aplicare” care listează o cale protejată (D7) e deteriorat: recuperarea nu mută și nu înlocuiește fișierul."""
    root = tmp_path / "program"
    install_program(root, OLD)
    user = add_user_data(root)
    work = root / update_apply.WORK_DIR_NAME
    stale = work / update_apply.OLD_DIR_NAME / protected  # o „copie veche” care ar înlocui fișierul utilizatorului
    stale.parent.mkdir(parents=True)
    stale.write_text("altceva\n", encoding="utf-8")
    _journal(work, **{journal_list: [protected]})
    with pytest.raises(UpdateError, match="Jurnalul actualizării"):
        recover_interrupted(root)
    assert (root / protected).read_bytes() == user[protected], f"recuperarea a atins {protected}, o cale protejată"


def test_without_a_journal_recovery_does_nothing_and_writes_nothing(tmp_path):
    """Fără jurnal, recuperarea nu face nimic și nu creează nimic."""
    root = tmp_path / "program"
    install_program(root, OLD)
    before = fingerprint(root, skip=())
    assert recover_interrupted(root) is None
    assert fingerprint(root, skip=()) == before


def test_an_apply_first_finishes_a_previous_interrupted_one(tmp_path, monkeypatch):
    """O aplicare nouă termină întâi aplicarea întreruptă, apoi instalează."""
    root = tmp_path / "program"
    install_program(root, OLD)
    archive = release(tmp_path)
    _crash_at(monkeypatch, 4, lambda: apply_update(archive, root, NEW))
    result = apply_update(archive, root, NEW)
    assert result.from_version == OLD and (root / "ruleaza.py").read_bytes() == new_release_files()["ruleaza.py"]
    assert not (root / DELETED_IN_NEW).exists()
    assert_work_dir_clean(root)


# ---------- lacătul ----------

def test_a_second_apply_while_one_holds_the_lock_is_refused(program, tmp_path):
    """Cât lacătul e ținut, altă aplicare sau recuperare e refuzată."""
    before = fingerprint(program)
    with update_lock.UpdateLock(program / update_apply.WORK_DIR_NAME / update_apply.LOCK_NAME):
        _refused(program, release(tmp_path), "altă actualizare e în curs")
        with pytest.raises(UpdateError, match="altă actualizare e în curs"):
            _journal(program / update_apply.WORK_DIR_NAME)
            recover_interrupted(program)
        (program / update_apply.WORK_DIR_NAME / update_apply.JOURNAL_NAME).unlink()
    assert fingerprint(program) == before


def test_a_lock_file_left_on_disk_does_not_block_the_next_apply(program, tmp_path):
    """Fișierul-lacăt rămas pe disc (permanent, N5) nu blochează: doar lacătul de sistem ținut de un proces viu blochează."""
    work = program / update_apply.WORK_DIR_NAME
    work.mkdir()
    (work / update_apply.LOCK_NAME).write_bytes(b"")
    apply_update(release(tmp_path), program, NEW)
    assert_work_dir_clean(program)


MIDDLE = "1.4.9"  # între OLD și NEW: mai nouă decât cea instalată la început, mai veche decât NEW
CHILD_ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", "EMAG_UPDATE_CHECK": "0"}
CHILD_TIMEOUT_SECONDS = 120
# Cât mai ține primul lacătul după ce al doilea a pornit: destul cât al doilea să ajungă la lacăt (și, pe codul vechi, să fi citit
# versiunea), puțin față de așteptarea lui de 2 s (update_lock.LOCK_WAIT_SECONDS), ca al doilea să ia apoi lacătul, nu „ocupat”.
HOLD_AFTER_SECOND_STARTED_SECONDS = 0.3
# Două aplicări în două procese reale (două ferestre ale aplicației): „primul” ține lacătul (în finish_pending, primul pas de sub
# lacăt) până pornește „al_doilea”, apoi încă puțin; al doilea anunță că pornește și cheamă apply_update. Semnalele sunt fișiere.
RACE_CHILD = r"""
import sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from emag_spend import update_apply, update_recovery
from emag_spend.update_errors import UpdateError
root, archive, version, role, signals, hold = Path(sys.argv[2]), Path(sys.argv[3]), sys.argv[4], sys.argv[5], Path(sys.argv[6]), float(sys.argv[7])
if role == "primul":
    real = update_recovery.finish_pending
    def holding(where):
        (signals / "primul_tine_lacatul").touch()
        deadline = time.monotonic() + 60
        while not (signals / "al_doilea_porneste").exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        time.sleep(hold)
        return real(where)
    update_recovery.finish_pending = holding
else:
    (signals / "al_doilea_porneste").touch()
try:
    print("APLICAT", update_apply.apply_update(archive, root, version), flush=True)
except UpdateError as error:
    print("REFUZAT", error, flush=True)
"""


def test_two_simultaneous_applies_never_install_an_older_version_over_a_newer_one(program, tmp_path):
    """P2: două procese reale aplică peste OLD, primul NEW, al doilea MIDDLE (mai veche, de exemplu dintr-o verificare veche), pornit
    cât primul ține lacătul. Versiunea instalată se citește sub lacăt: al doilea vede NEW și refuză cu MESSAGE_NOT_NEWER."""
    signals = tmp_path / "semnale"
    signals.mkdir()
    newest = release(tmp_path / "nou")
    older = write_archive(tmp_path / "mijloc" / f"cheltuieli-emag-v{MIDDLE}.zip", MIDDLE, program_files(MIDDLE))

    def start(archive, version, role):
        """Pornește copilul care aplică `archive` în rolul dat."""
        return subprocess.Popen([sys.executable, "-c", RACE_CHILD, str(settings.PROJECT_ROOT), str(program), str(archive), version, role,
                                 str(signals), str(HOLD_AFTER_SECOND_STARTED_SECONDS)],
                                stdout=subprocess.PIPE, stderr=subprocess.STDOUT, env=CHILD_ENV)

    first, second = start(newest, NEW, "primul"), None
    try:
        deadline = time.monotonic() + CHILD_TIMEOUT_SECONDS
        while not (signals / "primul_tine_lacatul").exists() and first.poll() is None and time.monotonic() < deadline:
            time.sleep(0.01)
        assert (signals / "primul_tine_lacatul").exists(), "primul proces n-a ajuns să țină lacătul"
        second = start(older, MIDDLE, "al_doilea")
        outputs = [process.communicate(timeout=CHILD_TIMEOUT_SECONDS)[0].decode("utf-8", errors="replace") for process in (first, second)]
    finally:
        for process in (first, second):
            if process is not None:
                process.kill()
    assert outputs[0].startswith("APLICAT") and f"to_version='{NEW}'" in outputs[0], outputs[0]
    expected = update_apply.MESSAGE_NOT_NEWER.format(version=MIDDLE, current=NEW)
    assert outputs[1].strip() == f"REFUZAT {expected}", f"al doilea a instalat o versiune mai veche peste {NEW}:\n{outputs[1]}"
    assert update_apply._installed_version(program) == NEW
    assert_work_dir_clean(program)


def test_the_version_in_the_journal_and_the_result_is_the_one_read_under_the_lock(program, tmp_path, monkeypatch):
    """P2: `current` citit sub lacăt (după ce o rulare oprită e terminată) e cel din jurnal și din ApplyResult: altă aplicare a
    instalat MIDDLE cât aceasta aștepta lacătul, deci jurnalul spune de_la=MIDDLE, nu versiunea de la începutul apelului."""
    seen = {}
    real_finish, real_write = update_recovery.finish_pending, update_recovery.write_journal

    def another_window_installs_first(root):
        """Cât apelul acesta aștepta lacătul, altă fereastră a instalat MIDDLE (aici: version.py rescris înaintea pasului de sub lacăt)."""
        (root / "emag_spend" / "version.py").write_text(f'VERSION = "{MIDDLE}"\n', encoding="utf-8")
        return real_finish(root)

    def note(work, journal):
        """Notează primul jurnal scris, apoi îl scrie de-adevăratelea."""
        seen.setdefault("de_la", journal["de_la"])
        return real_write(work, journal)

    monkeypatch.setattr(update_recovery, "finish_pending", another_window_installs_first)
    monkeypatch.setattr(update_recovery, "write_journal", note)
    result = apply_update(release(tmp_path), program, NEW)
    assert result.from_version == MIDDLE and seen["de_la"] == MIDDLE, (result, seen)


def test_the_lock_is_released_after_success_and_after_failure(program, tmp_path):
    """Lacătul se eliberează și după refuz, și după succes."""
    with pytest.raises(UpdateError):
        apply_update(release(tmp_path, new_release_files(extra={"iesiri/x": b"x"})), program, NEW)
    lock = update_lock.UpdateLock(program / update_apply.WORK_DIR_NAME / update_apply.LOCK_NAME)
    with lock:
        pass
    apply_update(release(tmp_path), program, NEW)
    with lock:
        pass


# ---------- legătura cu setările și cu restul programului ----------

def test_the_protected_names_match_the_settings():
    """Numele protejate sunt cele din settings.py (iesiri, logs, profil, .actualizare, reguli personale)."""
    assert update_apply.WORK_DIR_NAME == settings.UPDATE_WORK_DIR.name
    assert settings.UPDATE_DOWNLOAD_DIR.parent == settings.UPDATE_WORK_DIR, "descărcările stau în folderul de lucru al actualizării (N9)"
    for name in (settings.OUTPUTS_DIR.name, settings.LOGS_DIR.name, settings.DEFAULT_PROFILE_DIR_NAME, settings.UPDATE_WORK_DIR.name):
        assert name in update_archive.PROTECTED_DIRS, f"{name} din settings.py nu e protejat la actualizare"
    personal = f"{settings.CATEGORY_RULES_FILE.parent.name}/{settings.PERSONAL_CATEGORY_RULES_FILE_NAME}"
    assert personal in update_archive.PROTECTED_FILES


def test_this_program_has_a_version_file_the_updater_can_read():
    """Versiunea instalată se citește de pe disc (AST); version.py real trebuie să rămână citibil așa."""
    assert update_apply._installed_version(settings.PROJECT_ROOT) == VERSION

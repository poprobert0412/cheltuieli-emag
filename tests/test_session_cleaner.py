"""Teste pentru ștergerea sesiunii salvate (emag_spend/session_cleaner.py): doar foldere temporare, fără browser.

Fiecare caz periculos verifică două lucruri: rezultatul REFUSED și că nimic nu s-a șters.
Cum `confirm` din cazurile de refuz ridică eroare dacă e chemat, nici un bug nu poate ajunge la ștergere.
Toate numele și căile sunt inventate; „acasă” și „proiect” sunt foldere false, date explicit funcției.
"""

import ast
import errno
import os
import stat
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from emag_spend import session_cleaner
from emag_spend.session_cleaner import SessionDeleteStatus as Status

SENTINEL = "important.txt"


def _make_profile(folder: Path) -> Path:
    """Profil Chromium inventat: «Local State», «Default/Preferences» și «Default/Network/Cookies» (3 fișiere, 3 foldere)."""
    (folder / "Default" / "Network").mkdir(parents=True)
    (folder / "Local State").write_text("{}", encoding="utf-8")
    (folder / "Default" / "Preferences").write_text("{}", encoding="utf-8")
    (folder / "Default" / "Network" / "Cookies").write_bytes(b"cookie-inventat")
    return folder


def _never(path):
    raise AssertionError(f"confirm nu avea voie să fie chemat pentru {path}")


@pytest.fixture
def world(tmp_path):
    """Un «acasă» și un «proiect» false, plus un profil valid în afara lor."""
    home = tmp_path / "acasa"
    project = tmp_path / "proiect"
    home.mkdir()
    project.mkdir()
    return SimpleNamespace(root=tmp_path, home=home, project=project, profile=_make_profile(tmp_path / "profil"))


def _delete(world, profile, confirm=lambda path: True):
    return session_cleaner.delete_session(profile, confirm, project_root=world.project, home_dir=world.home)


# ---------- ștergerea obișnuită și confirmarea ----------

def test_confirmed_deletion_removes_only_the_profile_folder(world):
    neighbour = world.root / "alt_folder"
    neighbour.mkdir()
    (neighbour / SENTINEL).write_text("x", encoding="utf-8")
    asked = []
    result = _delete(world, world.profile, confirm=lambda path: asked.append(path) or True)
    assert result.status is Status.DELETED and result.succeeded
    assert (result.deleted_files, result.deleted_folders, result.failed_entries) == (3, 3, 0)
    assert not world.profile.exists()
    assert (neighbour / SENTINEL).read_text(encoding="utf-8") == "x"
    assert asked == [world.profile.resolve()]  # confirmarea primește calea completă, rezolvată


def test_declined_confirmation_deletes_nothing(world):
    result = _delete(world, world.profile, confirm=lambda path: False)
    assert result.status is Status.CANCELLED and result.succeeded
    assert (world.profile / "Default" / "Network" / "Cookies").is_file()


def test_confirmation_must_be_exactly_true_not_just_truthy(world):
    result = _delete(world, world.profile, confirm=lambda path: "DA")
    assert result.status is Status.CANCELLED
    assert world.profile.is_dir()


def test_relative_profile_path_is_resolved_before_asking(world, monkeypatch):
    monkeypatch.chdir(world.root)
    asked = []
    _delete(world, Path("profil"), confirm=lambda path: asked.append(path) or False)
    assert asked == [world.profile.resolve()] and asked[0].is_absolute()


@pytest.mark.parametrize("answer, expected", [
    ("DA", True), ("  DA  ", True), ("DA\r", True),
    ("da", False), ("Da", False), ("", False), ("nu", False), ("DAA", False), ("D", False), ("DA DA", False), ("y", False),
])
def test_terminal_confirmation_needs_exactly_da(answer, expected):
    assert session_cleaner.confirm_on_terminal(Path("x"), ask=lambda prompt: answer, say=lambda text: None) is expected


@pytest.mark.parametrize("error", [EOFError(), KeyboardInterrupt(), OSError("stdin închis"), RuntimeError("lost sys.stdin")])
def test_terminal_confirmation_without_an_answer_is_a_no(error):
    def broken(prompt):
        raise error
    assert session_cleaner.confirm_on_terminal(Path("x"), ask=broken, say=lambda text: None) is False


def test_terminal_confirmation_shows_the_full_path_and_the_exact_word(capsys, monkeypatch):
    monkeypatch.setattr("builtins.input", lambda prompt="": print(prompt, end="") or "nu")  # input real, înlocuit la apel
    full = Path("C:/exemplu/foarte lung/profil_inventat").resolve()
    assert session_cleaner.confirm_on_terminal(full) is False
    shown = capsys.readouterr().out
    assert str(full) in shown and "exact DA" in shown and "DEFINITIV" in shown


# ---------- căi periculoase: nimic nu se șterge ----------

def _dangerous_cases(world):
    """(nume, cale, folder de creat înainte). Fiecare are și semnătura Chromium: semnătura singură nu apără."""
    edge = world.home / "AppData" / "Local" / "Microsoft" / "Edge"
    chrome_mac = world.home / "Library" / "Application Support" / "Google" / "Chrome"
    return {
        "folderul personal": world.home,
        "parintele folderului personal": world.root,  # acasă și proiect sunt amândouă în `root`
        "folderul programului": world.project,
        "parintele folderului programului": world.project.parent,
        "profilul real Edge": edge / "User Data",
        "un profil din interiorul celui real Edge": edge / "User Data" / "Profile 1",
        "parintele profilului real Edge": edge,
        "profilul real Chrome pe Mac": chrome_mac,
    }


@pytest.mark.parametrize("case", [
    "folderul personal", "parintele folderului personal", "folderul programului", "parintele folderului programului",
    "profilul real Edge", "un profil din interiorul celui real Edge", "parintele profilului real Edge", "profilul real Chrome pe Mac",
])
def test_dangerous_paths_are_refused_even_with_a_chromium_signature(world, case):
    target = _dangerous_cases(world)[case]
    target.mkdir(parents=True, exist_ok=True)
    (target / "Local State").write_text("{}", encoding="utf-8")
    (target / "Default").mkdir(exist_ok=True)
    (target / SENTINEL).write_text("x", encoding="utf-8")
    result = _delete(world, target, confirm=_never)
    assert result.status is Status.REFUSED and not result.succeeded
    assert (target / SENTINEL).is_file() and (target / "Local State").is_file()
    assert result.reason and result.deleted_files == 0


def test_a_drive_root_is_refused(world):
    root = Path(world.root.anchor)
    result = _delete(world, root, confirm=_never)
    assert result.status is Status.REFUSED
    assert "rădăcina unui disc" in result.reason


def test_default_profile_inside_the_project_is_allowed(world):
    inside = _make_profile(world.project / ".profil_browser")
    result = _delete(world, inside)
    assert result.status is Status.DELETED and world.project.is_dir() and not inside.exists()


def test_folder_without_a_chromium_signature_is_refused(world):
    documents = world.root / "documente"
    documents.mkdir()
    (documents / "raport.txt").write_text("x", encoding="utf-8")
    result = _delete(world, documents, confirm=_never)
    assert result.status is Status.REFUSED
    assert "nu seamănă cu un profil de browser" in result.reason and "Local State" in result.reason and "Default" in result.reason
    assert (documents / "raport.txt").is_file()


@pytest.mark.parametrize("marker, is_folder", [("Local State", False), ("Default", True)])
def test_either_chromium_marker_is_enough(world, marker, is_folder):
    profile = world.root / "profil_minimal"
    profile.mkdir()
    if is_folder:
        (profile / marker).mkdir()
    else:
        (profile / marker).write_text("{}", encoding="utf-8")
    assert _delete(world, profile).status is Status.DELETED


def test_path_that_is_a_file_is_refused(world):
    file = world.root / "fisier.txt"
    file.write_text("x", encoding="utf-8")
    result = _delete(world, file, confirm=_never)
    assert result.status is Status.REFUSED and "nu e un folder" in result.reason and file.is_file()


def test_unknown_home_folder_refuses_instead_of_guessing(world, monkeypatch):
    def no_home():
        raise RuntimeError("Could not determine home directory.")
    monkeypatch.setattr(Path, "home", staticmethod(no_home))
    result = session_cleaner.delete_session(world.profile, _never, project_root=world.project)
    assert result.status is Status.REFUSED and "Nu pot verifica calea" in result.reason
    assert world.profile.is_dir()


# ---------- nimic de șters ----------

def test_missing_folder_is_not_an_error(world):
    result = _delete(world, world.root / "nu_exista", confirm=_never)
    assert result.status is Status.NOTHING_TO_DELETE and result.succeeded


def test_empty_folder_means_no_saved_session_and_is_left_alone(world):
    empty = world.root / "gol"
    empty.mkdir()
    result = _delete(world, empty, confirm=_never)
    assert result.status is Status.NOTHING_TO_DELETE and empty.is_dir()


# ---------- legături simbolice și joncțiuni ----------

@pytest.fixture(params=["symlink", "junction"])
def make_folder_link(request):
    """Fabrică de legături de folder; sare testul, cu motivul scris, dacă sistemul nu permite felul cerut."""
    def make(link: Path, target: Path) -> None:
        if request.param == "symlink":
            try:
                os.symlink(target, link, target_is_directory=True)
            except (OSError, NotImplementedError) as error:
                pytest.skip(f"nu pot crea legături simbolice pe acest sistem ({error}); pe Windows cer mod dezvoltator sau drepturi")
            return
        if sys.platform != "win32":
            pytest.skip("joncțiunile (mklink /J) există doar pe Windows; legăturile simbolice sunt testate separat")
        done = subprocess.run(["cmd", "/c", "mklink", "/J", str(link), str(target)], capture_output=True, text=True)
        if done.returncode != 0:
            pytest.skip(f"mklink /J a eșuat: {done.stdout.strip()} {done.stderr.strip()}")
    return make


def test_links_inside_the_profile_are_removed_without_touching_their_targets(world, make_folder_link):
    outside = world.root / "in_afara_profilului"
    (outside / "adanc").mkdir(parents=True)
    (outside / SENTINEL).write_text("x", encoding="utf-8")
    (outside / "adanc" / "altul.txt").write_text("y", encoding="utf-8")
    make_folder_link(world.profile / "Default" / "legatura", outside)
    result = _delete(world, world.profile)
    assert result.status is Status.DELETED
    assert not world.profile.exists()
    assert (outside / SENTINEL).read_text(encoding="utf-8") == "x"
    assert (outside / "adanc" / "altul.txt").read_text(encoding="utf-8") == "y"


def test_a_profile_path_that_is_itself_a_link_is_refused(world, make_folder_link):
    link = world.root / "profil_legatura"
    make_folder_link(link, world.profile)
    result = _delete(world, link, confirm=_never)
    assert result.status is Status.REFUSED and "legătură" in result.reason
    assert (world.profile / "Local State").is_file()


# ---------- fișiere blocate și alte erori ----------

def test_locked_files_give_a_partial_result_with_the_romanian_hint(world, monkeypatch):
    real_delete = session_cleaner._delete_file

    def locked_cookies(path):
        if Path(path).name == "Cookies":
            raise PermissionError(errno.EACCES, "folosit de alt program")
        real_delete(path)

    monkeypatch.setattr(session_cleaner, "_delete_file", locked_cookies)
    result = _delete(world, world.profile)
    assert result.status is Status.INCOMPLETE and not result.succeeded
    assert result.blocked_by_other_program and result.failed_entries == 1
    assert result.deleted_files == 2 and result.deleted_folders == 0  # folderele cu fișierul blocat rămân (nu numărăm eșecuri în lanț)
    assert (world.profile / "Default" / "Network" / "Cookies").is_file()
    assert not (world.profile / "Local State").exists() and not (world.profile / "Default" / "Preferences").exists()
    text = session_cleaner.describe_result(result)
    assert "Închide fereastra Edge deschisă de program și rulează din nou" in text
    assert "Rămase: 1" in text and "fișiere: 2" in text and "Traceback" not in text


def test_other_file_errors_are_reported_with_their_text(world, monkeypatch):
    def broken(path):
        raise OSError(errno.EIO, "Eroare de intrare-ieșire")

    monkeypatch.setattr(session_cleaner, "_delete_file", broken)
    result = _delete(world, world.profile)
    assert result.status is Status.INCOMPLETE and not result.blocked_by_other_program
    assert result.failed_entries == 3 and "Eroare de intrare-ieșire" in result.error_text
    text = session_cleaner.describe_result(result)
    assert "Eroare de intrare-ieșire" in text and "Închide fereastra" not in text


def test_a_locked_file_does_not_stop_the_rest_from_being_deleted(world, monkeypatch):
    real_delete = session_cleaner._delete_file

    def locked_state_file(path):
        if Path(path).name == "Local State":
            raise PermissionError(errno.EACCES, "folosit de alt program")
        real_delete(path)

    monkeypatch.setattr(session_cleaner, "_delete_file", locked_state_file)
    result = _delete(world, world.profile)
    assert result.failed_entries == 1
    assert not (world.profile / "Default").exists()  # tot restul s-a șters
    assert (world.profile / "Local State").is_file()


def test_read_only_files_are_deleted_too(world):
    cookies = world.profile / "Default" / "Network" / "Cookies"
    os.chmod(cookies, stat.S_IREAD)
    result = _delete(world, world.profile)
    assert result.status is Status.DELETED and not world.profile.exists()


# ---------- mesajele ----------

def test_deleted_message_says_what_was_deleted_and_advises_a_password_change(world):
    result = _delete(world, world.profile)
    text = session_cleaner.describe_result(result)
    assert str(world.profile.resolve()) in text and "fișiere: 3" in text and "foldere: 3" in text
    assert "Pentru a invalida orice sesiune veche poți schimba parola eMAG" in text


def test_refused_message_names_the_folder_the_reason_and_the_variable(world):
    documents = world.root / "documente"
    documents.mkdir()
    (documents / "x.txt").write_text("x", encoding="utf-8")
    text = session_cleaner.describe_result(_delete(world, documents, confirm=_never))
    assert text.startswith("EROARE: nu am șters nimic.") and str(documents.resolve()) in text and "EMAG_PROFILE_DIR" in text


@pytest.mark.parametrize("status, fragment", [
    (Status.NOTHING_TO_DELETE, "Nu există nicio sesiune salvată"),
    (Status.CANCELLED, "Anulat: nu am șters nimic"),
])
def test_neutral_messages(status, fragment):
    assert fragment in session_cleaner.describe_result(session_cleaner.SessionDeleteResult(status, Path("x")))


# ---------- contractul modulului ----------

def test_session_cleaner_never_imports_playwright():
    tree = ast.parse(Path(session_cleaner.__file__).read_text(encoding="utf-8"))
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module}
    assert "playwright" not in imported

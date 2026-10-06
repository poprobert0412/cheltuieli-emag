"""Garda de scriere: pe disc apar doar iesiri/, logs/ și .profil_browser/, nimic în Registry, AppData sau folderul personal.

Primește: sursele programului și fluxurile lui rulate pe date inventate (--demo, --din-cache, --sterge-sesiunea, --actualizeaza).
Verifică: (1) static (AST): fără Path.home(), expanduser, variabile de mediu cu foldere personale, tempfile, winreg,
nici apeluri care află numele contului sau al calculatorului; (2) la execuție: un audit hook notează fiecare scriere,
ștergere sau creare făcută de program și un blocaj le oprește pe cele din afara folderelor permise (rapoarte, jurnal,
demo-data.js, profil); în plus, programul nu citește locuri cu parole (profilul real de browser, chei).
Actualizarea (decis 5 oct. 2026) e singura excepție: scrie doar în .actualizare/ și în fișierele din manifestul validat
(static: doar funcțiile din UPDATE_WRITE_EXCEPTIONS scriu; la execuție: --actualizeaza pe o copie inventată a programului), iar
recuperarea pornită de lansatoare (python -m emag_spend.update_recovery, P1) doar în .actualizare/, în căile din jurnal și în logs/.
Două excepții înguste ale ei (decis 6 oct. 2026): `tempfile` doar ca `tempfile.mkdtemp(dir=...)` (folderul unic de descărcare din
settings.UPDATE_DOWNLOAD_DIR, N9) și `os.link` doar în update_apply.py (copia de siguranță din .actualizare/vechi, N1).
Fiecare detector e probat pe cod-capcană. Ce NU face: nu verifică ce scrie Windows sau browserul (Edge, Playwright).
"""

import ast
import os
import re
import sys
import textwrap
from pathlib import Path

import pytest

from emag_spend import settings
from tests.garda_audit import FLOWS, AuditRecorder, block_writes_outside, is_inside, isolated_program, prepare_flow, run_flow
from tests.garda_support import PROGRAM_DIR, dotted_name, parent_map, parse_source, program_sources, relative, string_constants

# ---------- (1) static ----------

# Module care duc în Registry, în foldere temporare ale sistemului sau la identitatea utilizatorului.
FORBIDDEN_IMPORTS = {
    "tempfile": "folderul temporar al sistemului (în afara proiectului)", "winreg": "Registry-ul Windows", "_winreg": "Registry-ul Windows",
    "getpass": "numele utilizatorului", "pwd": "datele conturilor de sistem", "grp": "datele grupurilor de sistem",
}
# Apeluri care duc în folderul personal sau află cine e utilizatorul (nume de cont, calculator, adresă de rețea).
FORBIDDEN_ATTRIBUTES = {
    "expanduser": "rezolvă ~ în folderul personal", "expandvars": "rezolvă %VARIABILE% din mediu (AppData, Temp...)",
    "getlogin": "numele contului", "getuser": "numele contului", "gethostname": "numele calculatorului", "getnode": "adresa MAC",
    "symlink": "legături în afara folderului", "link": "legături în afara folderului", "mkfifo": "fișiere speciale",
}
FORBIDDEN_DOTTED_CALLS = {"Path.home": "folderul personal", "pathlib.Path.home": "folderul personal", "os.path.expanduser": "folderul personal"}
# Variabile de mediu care duc în afara folderului programului. Citirea oricărei alte variabile în afară de EMAG_* o
# oprește oricum test_garda_parole; aici se spune DE CE sunt rele tocmai acestea: ar muta scrierile în AppData, Temp sau folderul personal.
PERCENT_VARIABLE = re.compile(r"(?i)%(?:appdata|localappdata|userprofile|temp|tmp|homepath|programdata|allusersprofile)%")
PERSONAL_FOLDER_VARIABLES = frozenset({
    "appdata", "localappdata", "home", "userprofile", "temp", "tmp", "homepath", "homedrive", "programdata", "allusersprofile",
    "public", "xdg_config_home", "xdg_cache_home", "xdg_data_home",
})
# Excepții justificate: (fișier, ce e permis) -> motivul. Fiecare trebuie să fie încă necesară (test mai jos).
STATIC_EXCEPTIONS = {
    ("session_cleaner.py", "Path.home"):
        "doar CITEȘTE calea folderului personal ca să REFUZE ștergerea lui, a părinților lui și a profilului real Edge/Chrome; nu scrie nimic acolo",
    ("update_apply.py", "link"):
        "os.link face doar copia de siguranță a unui fișier al programului în .actualizare/vechi (legătură tare în același folder, "
        "decis 6 oct. 2026, N1), ca fișierul din rădăcină să nu lipsească nicio clipă; nu leagă nimic în afara programului",
}
MIN_REASON_LENGTH = 30
# Singura folosire permisă a lui tempfile (decis 6 oct. 2026, N9): `import tempfile` simplu și doar apeluri
# `tempfile.mkdtemp(dir=<folder>)`, cu dir dat explicit: un folder unic DOAR în folderul primit (settings.UPDATE_DOWNLOAD_DIR),
# niciodată în folderul temporar al sistemului. Orice altă formă (gettempdir, NamedTemporaryFile, mkdtemp() fără dir, alias,
# `from tempfile import`) rămâne interzisă.
TEMPFILE_ALLOWED_CALL = "mkdtemp"
TEMPFILE_FOLDER_ARGUMENT = "dir"
TEMPFILE_EXCEPTION_REASON = ("folderul unic al fiecărei descărcări, creat doar în settings.UPDATE_DOWNLOAD_DIR "
                             "(tempfile.mkdtemp cu dir= explicit), ca două descărcări să nu-și calce arhivele")


def tempfile_only_in_a_given_folder(tree: ast.Module) -> bool:
    """True dacă fișierul folosește tempfile DOAR ca `import tempfile` + `tempfile.mkdtemp(dir=<ceva care nu e None>)`.

    Un import nefolosit, un alias, `from tempfile import ...` sau orice alt apel → False (rămâne încălcare).
    """
    imports = [node for node in ast.walk(tree) if isinstance(node, (ast.Import, ast.ImportFrom))
               and ((node.module or "").split(".")[0] == "tempfile" if isinstance(node, ast.ImportFrom)
                    else any(alias.name.split(".")[0] == "tempfile" for alias in node.names))]
    if any(isinstance(node, ast.ImportFrom) or any(alias.asname for alias in node.names) for node in imports):
        return False
    parents = parent_map(tree)
    uses = [node for node in ast.walk(tree) if isinstance(node, ast.Name) and node.id == "tempfile"]
    for use in uses:
        attribute = parents.get(use)
        call = parents.get(attribute)
        folder = next((keyword.value for keyword in getattr(call, "keywords", []) if keyword.arg == TEMPFILE_FOLDER_ARGUMENT), None)
        if not (isinstance(attribute, ast.Attribute) and attribute.attr == TEMPFILE_ALLOWED_CALL and isinstance(call, ast.Call)
                and call.func is attribute and folder is not None and not (isinstance(folder, ast.Constant) and folder.value is None)):
            return False
    return bool(uses)


def _environment_key(node: ast.AST) -> str | None:
    """Cheia literală citită din mediu de `os.environ[...]`, `os.environ.get(...)`, `os.getenv(...)` sau `"X" in os.environ`; altfel None."""
    def literal(value: ast.AST | None) -> str | None:
        """Valoarea text a unui literal, sau None dacă nodul nu e un literal text."""
        return value.value if isinstance(value, ast.Constant) and isinstance(value.value, str) else None

    if isinstance(node, ast.Subscript) and dotted_name(node.value) == "os.environ":
        return literal(node.slice)
    if isinstance(node, ast.Call) and dotted_name(node.func) in {"os.getenv", "os.environ.get"} and node.args:
        return literal(node.args[0])
    if isinstance(node, ast.Compare) and any(dotted_name(c) == "os.environ" for c in node.comparators):
        return literal(node.left)
    return None


def python_write_violations(tree: ast.Module, filename: str) -> list[tuple[str, str]]:
    """(ce s-a găsit, mesaj) pentru fiecare încălcare statică a regulii de scriere dintr-un fișier Python."""
    problems: list[tuple[str, str]] = []

    def add(node: ast.AST, what: str, why: str) -> None:
        """Adaugă (ce, mesaj) cu fișierul și linia nodului."""
        problems.append((what, f"{filename}:{node.lineno}: {why}"))

    tempfile_allowed = tempfile_only_in_a_given_folder(tree)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)) and not (isinstance(node, ast.ImportFrom) and node.level):
            for name in ([a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]):
                root = name.split(".")[0]
                if root == "tempfile" and tempfile_allowed:
                    continue  # doar tempfile.mkdtemp(dir=...): vezi TEMPFILE_EXCEPTION_REASON
                if root in FORBIDDEN_IMPORTS:
                    add(node, root, f"importă «{root}» ({FORBIDDEN_IMPORTS[root]}): programul scrie doar în folderul lui")
        if isinstance(node, ast.Attribute) and node.attr in FORBIDDEN_ATTRIBUTES:
            add(node, node.attr, f".{node.attr}: {FORBIDDEN_ATTRIBUTES[node.attr]}; programul nu are voie să iasă din folderul lui sau să afle cine ești")
        if isinstance(node, ast.Attribute):
            dotted = dotted_name(node)
            if dotted in FORBIDDEN_DOTTED_CALLS:
                add(node, dotted, f"{dotted}: {FORBIDDEN_DOTTED_CALLS[dotted]}; programul scrie doar în folderul lui (iesiri/, logs/, .profil_browser/)")
    for node in ast.walk(tree):
        key = _environment_key(node)
        if key and key.lower() in PERSONAL_FOLDER_VARIABLES:
            add(node, key, f"citește variabila de mediu «{key}», care duce în afara folderului programului (AppData, Temp, folderul personal)")
    for line, text, is_docstring in string_constants(tree):
        if not is_docstring and PERCENT_VARIABLE.search(text):
            problems.append((text, f"{filename}:{line}: textul conține o variabilă %NUME% de Windows care duce în afara folderului programului"))
    return problems


def _allowed(filename: str, what: str) -> bool:
    """True dacă încălcarea e o excepție justificată din STATIC_EXCEPTIONS."""
    return (Path(filename).name, what) in STATIC_EXCEPTIONS


@pytest.mark.parametrize("path", program_sources(), ids=relative)
def test_program_source_never_points_outside_its_own_folder(path):
    """Nicio sursă a programului nu duce în afara folderului lui (home, AppData, Temp, Registry), în afară de excepțiile justificate."""
    found = [message for what, message in python_write_violations(parse_source(path), relative(path)) if not _allowed(str(path), what)]
    assert not found, "\n".join(found)


def test_static_exceptions_are_justified_and_still_needed():
    """Fiecare excepție statică are motiv scris, fișierul există și codul încă face lucrul permis."""
    for (file, what), reason in STATIC_EXCEPTIONS.items():
        assert len(reason.strip()) >= MIN_REASON_LENGTH, f"excepția {file}/{what} nu are motiv scris"
        source = PROGRAM_DIR / file
        assert source.is_file(), f"excepția {file}/{what}: fișierul nu mai există; scoate excepția"
        used = {w for w, _ in python_write_violations(parse_source(source), file)}
        assert what in used, f"excepția {file}/{what} nu mai e necesară (codul nu mai face asta): scoate-o"


@pytest.mark.parametrize("source, expected", [
    ("import tempfile", "tempfile"), ("import winreg", "winreg"), ("from winreg import OpenKey", "winreg"), ("import getpass", "getpass"),
    ("from pathlib import Path\np = Path.home()", "Path.home"), ("import pathlib\np = pathlib.Path.home()", "pathlib.Path.home"),
    ("import os\np = os.path.expanduser('~')", "expanduser"), ("import os\np = os.path.expandvars('%APPDATA%')", "expandvars"),
    ("import os\nx = os.environ['APPDATA']", "APPDATA"), ("import os\nx = os.getenv('LOCALAPPDATA')", "LOCALAPPDATA"),
    ("import os\nx = os.environ.get('userprofile')", "userprofile"), ("import os\nx = os.environ['TEMP']", "TEMP"),
    ("import os\nx = os.getlogin()", "getlogin"), ("import socket\nx = socket.gethostname()", "gethostname"),
    ("import os\nos.symlink('a', 'b')", "symlink"), ("import os\nos.link('a', 'b')", "link"),
    ("import tempfile\nx = tempfile.mkdtemp()", "tempfile"), ("import tempfile\nx = tempfile.gettempdir()", "tempfile"),
    ("import tempfile\nx = tempfile.mkdtemp(dir=None)", "tempfile"), ("from tempfile import mkdtemp\nx = mkdtemp(dir='f')", "tempfile"),
    ("import tempfile as t\nx = t.mkdtemp(dir='f')", "tempfile"),
    ("import tempfile\nx = tempfile.mkdtemp(dir='f')\ny = tempfile.NamedTemporaryFile()", "tempfile"),
])
def test_write_detector_catches_trap_code(source, expected):
    """Capcană: Path.home, expanduser, variabile AppData/Temp, tempfile (orice altceva decât mkdtemp(dir=...)), winreg, getuser, link."""
    found = {what for what, _ in python_write_violations(ast.parse(source), "emag_spend/capcana.py")}
    assert expected in found, f"nu a fost prins «{expected}» în:\n{source}\n(prins: {sorted(found)})"


def test_tempfile_is_allowed_only_to_make_a_folder_inside_a_given_folder():
    """Fals pozitiv: `tempfile.mkdtemp(dir=folder)` (folder unic în folderul dat) nu e o încălcare."""
    allowed = "import tempfile\nfrom pathlib import Path\ndef f(folder):\n    return Path(tempfile.mkdtemp(prefix='x', dir=folder))\n"
    assert python_write_violations(ast.parse(allowed), "emag_spend/curat.py") == []


def test_the_tempfile_exception_is_justified_and_still_needed():
    """Excepția pentru tempfile are motiv scris și măcar o sursă a programului chiar folosește tempfile.mkdtemp(dir=...)."""
    assert len(TEMPFILE_EXCEPTION_REASON.strip()) >= MIN_REASON_LENGTH
    users = [relative(path) for path in program_sources() if "tempfile" in path.read_text(encoding="utf-8")
             and tempfile_only_in_a_given_folder(parse_source(path))]
    assert users, "nicio sursă nu mai folosește tempfile.mkdtemp(dir=...): scoate excepția"


def test_write_detector_ignores_docstrings_and_ordinary_paths():
    """Fals pozitiv: cuvinte din docstring-uri și căi obișnuite din folderul proiectului nu sunt încălcări."""
    clean = textwrap.dedent('''
        """Documentație care povestește despre Path.home() și variabila TEMP."""
        from pathlib import Path
        ROOT = Path(__file__).resolve().parent
        OUT = ROOT / "iesiri"
        def f():
            """Scrie în folderul TEMP al proiectului (doar text)."""
            return OUT / "x.txt"
    ''')
    assert python_write_violations(ast.parse(clean), "emag_spend/curat.py") == []


# ---------- (2) la execuție ----------

# Evenimente de audit care schimbă ceva pe disc sau ating Registry-ul și folderele temporare ale sistemului.
WRITE_AUDIT_EVENTS = (
    "open", "os.remove", "os.rename", "os.mkdir", "os.rmdir", "os.truncate", "os.chmod", "os.link", "os.symlink",
    "shutil.*", "tempfile.*", "winreg.*", "os.utime",
)
# Evenimente care nu au voie deloc: Registry și foldere temporare ale sistemului.
FORBIDDEN_AUDIT_EVENTS = ("tempfile.", "winreg.")
# Singurul eveniment tempfile permis: mkdtemp cu dir= explicit (TEMPFILE_EXCEPTION_REASON); calea lui se verifică apoi ca orice
# scriere (trebuie să fie în folderele permise), deci un mkdtemp în folderul Temp al sistemului tot pică.
ALLOWED_TEMPFILE_EVENTS = frozenset({"tempfile.mkdtemp"})
# Fragmente de cale (cu litere mici) ale unor locuri cu parole sau chei: programul nu are niciun motiv să le deschidă.
SENSITIVE_READ_MARKERS = (
    "/user data/", "login data", "/cookies", ".ssh", ".aws", ".gnupg", "ntuser.dat", "id_rsa", "id_ed25519", "/credentials", "keychain",
)
# Singurele intrări care pot apărea în folderul temporar al testului după un flux (ce a creat programul sau testul).
EXPECTED_TOP_LEVEL = frozenset({"iesiri", "logs", "site", "cache", "profil"})


def _describe(events) -> str:
    """Evenimentele de audit într-un singur text: nume, căi și locul din cod."""
    return "; ".join(f"{event.name} {event.paths()} la {event.where}" for event in events)


def _forbidden(events) -> list:
    """Evenimentele care ating Registry sau folderele temporare ale sistemului (fără mkdtemp cu dir=, verificat apoi pe cale)."""
    return [event for event in events if event.name.startswith(FORBIDDEN_AUDIT_EVENTS) and event.name not in ALLOWED_TEMPFILE_EVENTS]


@pytest.mark.parametrize("flow", FLOWS)
def test_program_flows_write_only_in_their_own_folders(flow, tmp_path, monkeypatch):
    """La execuție: fluxurile scriu și șterg doar în iesiri, logs, demo-data.js și profil; nimic în Temp, Registry sau altundeva."""
    monkeypatch.setattr(sys, "dont_write_bytecode", True)  # fără __pycache__ nou: nu e scrierea programului, ci a importurilor
    with isolated_program(monkeypatch, tmp_path) as layout:
        arguments = prepare_flow(flow, layout)  # înainte de blocaj: pregătirea datelor inventate folosește run_store și scrie în afara folderelor permise
        violations = block_writes_outside(monkeypatch, layout.writable_roots)
        with AuditRecorder(WRITE_AUDIT_EVENTS) as audit:
            code = run_flow(arguments)
    assert code == 0, f"fluxul {flow} nu s-a terminat cu succes, deci testul n-ar fi dovedit nimic"
    assert not violations, "scrieri sau ștergeri ale programului în afara folderelor permise (blocate de test):\n  " + "\n  ".join(violations)

    writes = [e for e in audit.events if e.name != "open" or e.is_write_open()]
    assert not _forbidden(writes), f"programul a atins Registry sau folderul Temp al sistemului: {_describe(writes)}"
    outside = [e for e in writes if not all(is_inside(path, layout.writable_roots) for path in e.paths())]
    assert not outside, f"scrieri în afara folderelor permise {[str(r) for r in layout.writable_roots]}: {_describe(outside)}"

    def wrote_under(root: Path) -> bool:
        """True dacă auditul a văzut o scriere sub folderul dat."""
        return any(is_inside(path, (root,)) for e in writes for path in e.paths())

    assert wrote_under(layout.logs), "auditul n-a văzut scrierea jurnalului: hook-ul nu prinde nimic și testul n-ar dovedi nimic"
    if flow == "sterge_sesiunea":
        assert not layout.profile.exists(), "profilul fals trebuia șters"
        assert any(e.name in {"os.remove", "os.rmdir"} for e in writes), "auditul n-a văzut ștergerea profilului"
    else:
        assert wrote_under(layout.out) and any(layout.out.rglob("raport.html")), "auditul n-a văzut scrierea raportului"

    unexpected = sorted(set(os.listdir(tmp_path)) - EXPECTED_TOP_LEVEL)
    assert not unexpected, f"au apărut fișiere sau foldere neașteptate lângă rezultate: {unexpected}"
    sensitive = [e for e in audit.events if e.name == "open" and any(marker in path.lower().replace("\\", "/") for path in e.paths() for marker in SENSITIVE_READ_MARKERS)]
    assert not sensitive, f"programul a deschis locuri cu parole sau chei: {_describe(sensitive)}"


def test_demo_flow_writes_demo_data_js_only_where_the_settings_say(tmp_path, monkeypatch):
    """demo-data.js e singurul fișier din proiect pe care --demo îl rescrie: trebuie să meargă în calea din setări."""
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    with isolated_program(monkeypatch, tmp_path) as layout:
        violations = block_writes_outside(monkeypatch, layout.writable_roots)
        assert run_flow(prepare_flow("demo", layout)) == 0
    assert not violations and layout.site_file.is_file() and layout.site_file.stat().st_size > 0


def test_deleting_the_session_never_touches_a_sibling_folder(tmp_path, monkeypatch):
    """--sterge-sesiunea șterge doar profilul ales, nu și un folder vecin cu semnătură de profil."""
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    sibling = tmp_path / "alt_profil"
    sibling.mkdir()
    (sibling / "Local State").write_text("{}", encoding="utf-8")
    with isolated_program(monkeypatch, tmp_path) as layout:
        arguments = prepare_flow("sterge_sesiunea", layout)
        violations = block_writes_outside(monkeypatch, layout.writable_roots)
        assert run_flow(arguments) == 0
    assert not violations and not layout.profile.exists()
    assert (sibling / "Local State").is_file(), "--sterge-sesiunea a șters și un folder vecin cu profilul: ar putea șterge sesiunea altcuiva"


# ---------- mecanismele de gardă văzute funcționând ----------

def _run_as_program(source: str, name: str = "capcana.py"):
    """Rulează cod ca și cum ar fi fișierul `emag_spend/<name>` (numele din co_filename ajunge în stivă)."""
    namespace: dict = {}
    exec(compile(textwrap.dedent(source), str(PROGRAM_DIR / name), "exec"), namespace)  # noqa: S102 - cod fix, scris în test
    return namespace


def test_audit_recorder_attributes_writes_to_the_program_and_ignores_other_code(tmp_path):
    """Mecanismul de audit notează scrierile făcute din codul programului și le ignoră pe cele făcute de test."""
    target = tmp_path / "x.txt"
    program = _run_as_program(f"def scrie():\n    open({str(target)!r}, 'w').close()\n")
    with AuditRecorder(("open",)) as audit:
        program["scrie"]()
        open(tmp_path / "alt.txt", "w").close()  # scris de testul însuși: nu e al programului
    assert [e.paths() for e in audit.events if e.is_write_open()] == [[str(target)]]
    assert audit.events[0].where.startswith("emag_spend/capcana.py:")


def test_write_guard_blocks_and_records_a_program_write_outside_the_allowed_folders(tmp_path, monkeypatch):
    """Blocajul de scriere oprește și notează scrieri, ștergeri și rmtree din program în afara folderelor permise."""
    allowed, outside = tmp_path / "permis", tmp_path / "interzis"
    allowed.mkdir()
    outside.mkdir()
    violations = block_writes_outside(monkeypatch, (allowed,))
    program = _run_as_program(
        "import os, shutil\n"
        "def scrie(path):\n    open(path, 'w').close()\n"
        "def sterge(path):\n    os.unlink(path)\n"
        "def curata(path):\n    shutil.rmtree(path)\n")
    program["scrie"](str(allowed / "ok.txt"))
    assert (allowed / "ok.txt").exists()
    for operation, argument in (("scrie", outside / "rau.txt"), ("curata", outside)):
        with pytest.raises(PermissionError, match="blocat de test"):
            program[operation](str(argument))
    keep = outside / "pastrat.txt"
    keep.write_text("x", encoding="utf-8")  # scris de test, nu de program: trece
    with pytest.raises(PermissionError):
        program["sterge"](str(keep))
    assert keep.exists() and outside.exists() and not (outside / "rau.txt").exists()
    assert len(violations) == 3 and all("la emag_spend/capcana.py" in v for v in violations)


# ---------- aplicația locală: aceleași reguli de scriere ----------

def test_the_local_application_writes_only_in_its_own_folders(tmp_path, monkeypatch):
    """Cu serverul REAL: o rulare demo și ștergerea sesiunii prin API scriu și șterg doar în iesiri/ și în profil; nimic în Temp, Registry, folderul personal sau în interfata/ (demo-data.js rămâne neatins)."""
    from emag_spend.app_runner import AppRunner
    from tests.app_support import running_app, wait_for, write_interface
    from tests.garda_audit import seed_profile

    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    with isolated_program(monkeypatch, tmp_path) as layout:
        interface = write_interface(tmp_path / "interfata_inventata")  # creată înainte de blocaj: pregătirea nu e scrierea programului
        seed_profile(layout.profile)
        violations = block_writes_outside(monkeypatch, layout.writable_roots)
        runner = AppRunner(outputs_dir=layout.out, profile_dir=layout.profile)
        with AuditRecorder(WRITE_AUDIT_EVENTS) as audit:
            with running_app(tmp_path, runner=runner, outputs_dir=layout.out, profile_dir=layout.profile, interface_dir=interface) as app:
                assert app.call("GET", "/api/state").json()["session_saved"] is True
                assert app.call("POST", "/api/runs", body={"mode": "demo"}).status == 202
                wait_for(lambda: app.call("GET", "/api/state").json()["state"] in ("done", "error"), "sfârșitul rulării demo")
                assert app.call("GET", "/api/state").json()["state"] == "done"
                deleted = app.call("POST", "/api/session/delete", body={"confirm": "DA"})
                assert deleted.status == 200, deleted.body
                assert app.call("POST", "/api/shutdown", body={}).status == 200
    assert not violations, "scrieri sau ștergeri ale aplicației în afara folderelor permise (blocate de test):\n  " + "\n  ".join(violations)

    writes = [e for e in audit.events if e.name != "open" or e.is_write_open()]
    assert not _forbidden(writes), f"aplicația a atins Registry sau folderul Temp al sistemului: {_describe(writes)}"
    outside = [e for e in writes if not all(is_inside(path, layout.writable_roots) for path in e.paths())]
    assert not outside, f"scrieri ale aplicației în afara folderelor permise {[str(r) for r in layout.writable_roots]}: {_describe(outside)}"
    assert any(is_inside(path, (layout.out,)) for e in writes for path in e.paths()) and any(layout.out.rglob("raport.html")), "auditul n-a văzut scrierea raportului: hook-ul nu prinde nimic și testul n-ar dovedi nimic"
    assert not layout.profile.exists(), "sesiunea nu s-a șters prin API"
    assert not layout.site_file.exists(), "o rulare din aplicație a rescris demo-data.js al site-ului"
    sensitive = [e for e in audit.events if e.name == "open" and any(marker in path.lower().replace("\\", "/") for path in e.paths() for marker in SENSITIVE_READ_MARKERS)]
    assert not sensitive, f"aplicația a deschis locuri cu parole sau chei: {_describe(sensitive)}"
    unexpected = sorted(set(os.listdir(tmp_path)) - EXPECTED_TOP_LEVEL - {"interfata_inventata"})
    assert not unexpected, f"au apărut fișiere sau foldere neașteptate lângă rezultate: {unexpected}"


def _is_text_replace(node: ast.Call) -> bool:
    """True pentru `text.replace(vechi, nou)` (înlocuire de text, 2-3 argumente), nu pentru mutarea unui fișier.

    Mutările de fișiere sunt `Path.replace(țintă)` (un singur argument) și `os.replace(sursă, țintă)` (chemat pe modulul os):
    pe acelea garda le prinde în continuare.
    """
    receiver = node.func.value if isinstance(node.func, ast.Attribute) else None
    on_os_module = isinstance(receiver, ast.Name) and receiver.id == "os"
    return node.func.attr == "replace" and not on_os_module and len(node.args) in (2, 3)


def test_text_replace_is_not_mistaken_for_a_file_move():
    """Garda deosebește `text.replace("\\n", "")` (text) de `Path(...).replace(țintă)` și `os.replace(a, b)` (fișiere)."""
    calls = [node for node in ast.walk(ast.parse('t.replace("a", "b")\np.replace(t2)\nos.replace(a, b)')) if isinstance(node, ast.Call)]
    assert [_is_text_replace(call) for call in calls] == [True, False, False]


def test_the_application_code_never_deletes_or_writes_anything_by_itself():
    """Static: în afară de pipeline (apelat din app_runner) și de ștergerea sesiunii (session_cleaner), modulele aplicației nu scriu și nu șterg nimic pe disc."""
    forbidden_calls = {"write_text", "write_bytes", "mkdir", "unlink", "rmdir", "rename", "replace", "rmtree", "remove", "touch", "truncate", "copyfile", "copy", "move"}
    for name in ("app_server.py", "app_security.py", "app_runs.py", "app_static.py", "app_errors.py", "app_opener.py", "run_ids.py", "progress.py"):
        tree = parse_source(PROGRAM_DIR / name)
        found = [f"{name}:{node.lineno}: .{node.func.attr}()" for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in forbidden_calls
                 and not _is_text_replace(node)]
        opened_for_write = [f"{name}:{node.lineno}: open(..., {ast.unparse(node.args[1])})" for node in ast.walk(tree)
                            if isinstance(node, ast.Call) and dotted_name(node.func) == "open" and len(node.args) > 1
                            and isinstance(node.args[1], ast.Constant) and any(letter in str(node.args[1].value) for letter in "wax+")]
        assert not found and not opened_for_write, f"{name} scrie sau șterge pe disc, dar el doar citește: {found + opened_for_write}"


# ---------- actualizarea: singurul cod care scrie în folderul programului (decis 5 oct. 2026) ----------

# Apeluri care scriu, mută, șterg sau schimbă drepturi pe disc (pe lângă open/os.open în mod de scriere).
DISK_WRITE_CALLS = frozenset({
    "write_text", "write_bytes", "mkdir", "makedirs", "unlink", "rmdir", "rename", "replace", "rmtree", "remove", "touch",
    "truncate", "copyfile", "copy", "move", "chmod", "utime",
})
WRITE_MODE_LETTERS = "wax+"
# Modulele actualizării care au voie să scrie și unde: (fișier, funcție sau "*" pentru tot fișierul) -> motivul.
# Orice altă funcție din update_*.py și version.py nu scrie și nu șterge nimic; fiecare excepție trebuie să fie încă necesară.
UPDATE_WRITE_EXCEPTIONS = {
    ("update_http.py", "download_to"):
        "scrie arhiva descărcată doar în ținta primită (<țintă>.part, apoi os.replace); update_download.py o pune în settings.UPDATE_WORK_DIR",
    ("update_http.py", "_remove_quietly"):
        "șterge doar fișierul .part al unei descărcări eșuate, lângă ținta din settings.UPDATE_WORK_DIR",
    ("update_download.py", "download_release"):
        "creează doar folderul de descărcare primit, din settings.UPDATE_WORK_DIR",
    ("update_download.py", "_remove_quietly"):
        "șterge doar arhiva greșită și SHA256SUMS.txt din folderul de descărcare (settings.UPDATE_WORK_DIR)",
    ("update_download.py", "_new_download_folder"):
        "creează doar settings.UPDATE_DOWNLOAD_DIR și, în el, folderul unic al unei descărcări (tempfile.mkdtemp(dir=...), N9)",
    ("update_download.py", "_remove_download_folder"):
        "șterge doar fișierele din folderul unic al descărcării, folderul însuși și settings.UPDATE_DOWNLOAD_DIR rămas gol (N9)",
    ("update_lock.py", "*"):
        "creează (o singură dată) doar fișierul-lacăt gol .actualizare/lacat și folderul lui; nu-l șterge niciodată (N5)",
    ("update_apply.py", "*"):
        "scrie în rădăcina programului doar căile din manifestul validat (și folderele lor) și în .actualizare/; dovedit la execuție "
        "de test_update_flow_writes_only_in_the_work_dir_and_manifest_paths",
    ("update_recovery.py", "*"):
        "mută înapoi doar căile din jurnalul validat (fără căi protejate), curăță doar .actualizare/ (jurnal, nou/, vechi/, copie/ și "
        "descărcările oprite din descarcari/) și, pornit de lansatoare, scrie jurnalul pornirii în logs/; dovedit la execuție de "
        "test_update_flow_writes_only_in_the_work_dir_and_manifest_paths (aplicarea îl folosește) și de "
        "test_the_launcher_recovery_writes_only_in_its_work_dir_the_journal_paths_and_logs",
}
# Modulele în care tot fișierul are voie să scrie: doar cele ale căror scrieri le verifică la execuție fluxul --actualizeaza.
WHOLE_FILE_WRITERS_PROVEN_AT_RUNTIME = frozenset({"update_apply.py", "update_lock.py", "update_recovery.py"})


def _update_sources() -> list:
    """Modulele actualizării verificate static: emag_spend/update_*.py și version.py."""
    return sorted([*PROGRAM_DIR.glob("update_*.py"), PROGRAM_DIR / "version.py"])


def _opens_for_writing(node: ast.Call) -> bool:
    """True pentru open(..., "w"/"a"/"x"/"+") sau cale.open("wb") cu mod literal, și pentru orice os.open (creare la nivel jos)."""
    name = dotted_name(node.func)
    if name == "os.open":
        return True
    is_open = name == "open" or (isinstance(node.func, ast.Attribute) and node.func.attr == "open")
    if not is_open:
        return False
    position = 1 if name == "open" else 0
    modes = [node.args[position]] if len(node.args) > position else []
    modes += [keyword.value for keyword in node.keywords if keyword.arg == "mode"]
    return any(isinstance(mode, ast.Constant) and any(letter in str(mode.value) for letter in WRITE_MODE_LETTERS) for mode in modes)


def disk_write_calls(tree: ast.Module) -> list[tuple[str, int, str]]:
    """(funcția care o conține, linia, apelul) pentru fiecare apel care scrie pe disc; funcțiile din clase apar ca „Clasă.metodă”."""
    parents = parent_map(tree)
    found = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        attribute_write = isinstance(node.func, ast.Attribute) and node.func.attr in DISK_WRITE_CALLS and not _is_text_replace(node)
        if not (attribute_write or _opens_for_writing(node)):
            continue
        names, current = [], parents.get(node)
        while current is not None:
            if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                names.append(current.name)
            current = parents.get(current)
        found.append((".".join(reversed(names)) or "<modul>", node.lineno, ast.unparse(node.func)))
    return found


def _allowed_update_write(file: str, function: str) -> bool:
    """True dacă funcția are voie să scrie după UPDATE_WRITE_EXCEPTIONS (exact, sau tot fișierul cu "*")."""
    return (file, function) in UPDATE_WRITE_EXCEPTIONS or (file, "*") in UPDATE_WRITE_EXCEPTIONS


@pytest.mark.parametrize("path", _update_sources(), ids=lambda path: path.name)
def test_update_modules_write_only_where_an_exception_says_why(path):
    """Static: în modulele actualizării scriu doar funcțiile din UPDATE_WRITE_EXCEPTIONS (verificarea, versiunea, regulile arhivei nu scriu)."""
    found = [f"{path.name}:{line}: {call}() în {function}" for function, line, call in disk_write_calls(parse_source(path))
             if not _allowed_update_write(path.name, function)]
    assert not found, "scrieri pe disc fără excepție justificată în UPDATE_WRITE_EXCEPTIONS:\n  " + "\n  ".join(found)


def test_update_write_exceptions_are_justified_and_still_needed():
    """Fiecare excepție de scriere a actualizării are motiv scris, fișierul există și funcția (sau fișierul) chiar scrie.

    O excepție pe tot fișierul ("*") e permisă doar pentru modulele dovedite la execuție de fluxul --actualizeaza de mai jos.
    """
    for (file, function), reason in UPDATE_WRITE_EXCEPTIONS.items():
        assert len(reason.strip()) >= MIN_REASON_LENGTH, f"excepția {file}/{function} nu are motiv scris"
        assert function != "*" or file in WHOLE_FILE_WRITERS_PROVEN_AT_RUNTIME, f"excepția {file}/* e prea largă: numește funcția care scrie"
        source = PROGRAM_DIR / file
        assert source.is_file(), f"excepția {file}/{function}: fișierul nu mai există; scoate excepția"
        writers = {name for name, _, _ in disk_write_calls(parse_source(source))}
        assert writers if function == "*" else function in writers, f"excepția {file}/{function} nu mai e necesară (nu mai scrie): scoate-o"


def test_the_write_call_detector_catches_trap_code_and_names_the_function():
    """Capcană: os.replace, os.open, open("wb"), cale.open("a"), write_bytes, chmod, rmdir sunt prinse, cu funcția care le conține."""
    source = textwrap.dedent('''
        import os
        def muta(a, b):
            os.replace(a, b)
        class Lacat:
            def ia(self, p):
                return os.open(p, os.O_CREAT)
        def scrie(p):
            with open(p, "wb") as f:
                f.write(b"x")
            p.open(mode="a").close()
            p.write_bytes(b"")
            os.chmod(p, 0o755)
            os.rmdir(p.parent)
        def citeste(p, text):
            return open(p, "rb").read(), p.open().read(), text.replace("a", "b")
    ''')
    found = {(function, call) for function, _, call in disk_write_calls(ast.parse(source))}
    assert found == {("muta", "os.replace"), ("Lacat.ia", "os.open"), ("scrie", "open"), ("scrie", "p.open"), ("scrie", "p.write_bytes"),
                     ("scrie", "os.chmod"), ("scrie", "os.rmdir")}


def test_update_flow_writes_only_in_the_work_dir_and_manifest_paths(tmp_path, monkeypatch):
    """La execuție: `--actualizeaza --fara-confirmare` cu un GitHub fals, pe o copie inventată a programului, scrie doar în
    .actualizare/, în jurnal și în fișierele din manifeste (vechi și nou) și în folderele lor; datele utilizatorului rămân."""
    from emag_spend.update_archive import ancestors
    from emag_spend.version import VERSION
    from tests.update_archive_support import MANIFEST, FakeGitHub, add_user_data, archive_bytes, install_program, newer_than, program_files

    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    root = tmp_path / "program"
    old_files = program_files(VERSION, extra={"docs/vechi/de_sters.md": b"doar in versiunea veche\n"})
    install_program(root, VERSION, old_files)
    user = add_user_data(root)
    new = newer_than(VERSION)
    new_files = program_files(new, extra={"docs/nou/pagina.md": "pagină nouă, inventată\n".encode("utf-8")})
    manifest_paths = {*old_files, *new_files, MANIFEST}
    manifest_folders = {folder for path in manifest_paths for folder in ancestors(path)}
    work = root / ".actualizare"
    monkeypatch.setattr(settings, "PROJECT_ROOT", root)
    monkeypatch.setattr(settings, "UPDATE_WORK_DIR", work)
    monkeypatch.setattr(settings, "UPDATE_DOWNLOAD_DIR", work / "descarcari")
    with isolated_program(monkeypatch, tmp_path) as layout:
        FakeGitHub(new, archive_bytes(new, new_files)).install(monkeypatch)
        violations = block_writes_outside(monkeypatch, (root, layout.logs))  # plasă de siguranță: nimic în afara copiei și a jurnalului
        with AuditRecorder(WRITE_AUDIT_EVENTS) as audit:
            code = run_flow(["--actualizeaza", "--fara-confirmare"])
    assert code == 0, "actualizarea n-a reușit, deci testul n-ar dovedi nimic"
    assert not violations, "scrieri ale actualizării în afara copiei programului:\n  " + "\n  ".join(violations)

    real_root = Path(os.path.realpath(root))

    def allowed(path: str) -> bool:
        """În .actualizare/ sau în jurnal; altfel exact un fișier din manifeste sau un folder al lor."""
        if is_inside(path, (work, layout.logs)):
            return True
        try:
            relative = Path(os.path.realpath(path)).relative_to(real_root).as_posix()
        except ValueError:
            return False
        return relative in manifest_paths or relative in manifest_folders

    writes = [e for e in audit.events if e.name != "open" or e.is_write_open()]
    assert not _forbidden(writes), f"actualizarea a atins Registry sau Temp: {_describe(writes)}"
    outside = [e for e in writes if not all(allowed(path) for path in e.paths())]
    assert not outside, f"actualizarea a scris în afara lui .actualizare/ și a fișierelor din manifest: {_describe(outside)}"
    version_file = os.path.realpath(root / "emag_spend" / "version.py")
    assert any(version_file in [os.path.realpath(p) for p in e.paths()] for e in writes), \
        "auditul n-a văzut mutarea fișierelor în rădăcină: hook-ul nu prinde nimic și testul n-ar dovedi nimic"
    assert all((root / name).read_bytes() == data for name, data in user.items()), "actualizarea a schimbat datele utilizatorului"
    assert (root / "emag_spend" / "version.py").read_bytes() == new_files["emag_spend/version.py"]
    assert not (root / "docs" / "vechi").exists()
    assert sorted(os.listdir(work)) == ["lacat"], "după actualizare, în .actualizare rămâne doar lacătul gol (N5, N9)"
    assert any(e.name == "tempfile.mkdtemp" and is_inside(e.paths()[0], (work / "descarcari",)) for e in writes), \
        "descărcarea trebuia să meargă într-un folder unic din settings.UPDATE_DOWNLOAD_DIR (N9)"
    unexpected = sorted(set(os.listdir(tmp_path)) - {"program", "logs"})
    assert not unexpected, f"au apărut fișiere sau foldere neașteptate lângă copia programului: {unexpected}"


def test_the_launcher_recovery_writes_only_in_its_work_dir_the_journal_paths_and_logs(tmp_path, monkeypatch):
    """La execuție (P1): punctul de intrare al lansatoarelor (update_recovery.main, ce rulează `python -m emag_spend.update_recovery`) pe
    o copie inventată pe jumătate actualizată scrie doar în .actualizare/, în căile din jurnal și în logs/ ale copiei; nimic altundeva."""
    from emag_spend import update_recovery
    from emag_spend.version import VERSION
    from tests.update_archive_support import install_program, newer_than, write_journal_by_hand

    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    root = tmp_path / "program"
    install_program(root, VERSION)
    work, logs = root / update_recovery.WORK_DIR_NAME, root / update_recovery.LOGS_DIR_NAME
    (work / update_recovery.OLD_DIR_NAME).mkdir(parents=True)
    os.replace(root / "ruleaza.py", work / update_recovery.OLD_DIR_NAME / "ruleaza.py")
    (root / "ruleaza.py").write_text("print('versiunea nouă, pe jumătate instalată')\n", encoding="utf-8")
    journal_paths = {"ruleaza.py"}
    write_journal_by_hand(work, VERSION, newer_than(VERSION), scrise=sorted(journal_paths), existau=sorted(journal_paths))
    violations = block_writes_outside(monkeypatch, (root,))
    with AuditRecorder(WRITE_AUDIT_EVENTS) as audit:
        code = update_recovery.main([], root)
    assert code == update_recovery.EXIT_RECOVERY_OK, "recuperarea n-a reușit, deci testul n-ar dovedi nimic"
    assert not violations, "scrieri ale recuperării în afara copiei programului:\n  " + "\n  ".join(violations)
    real_root = Path(os.path.realpath(root))

    def allowed(path: str) -> bool:
        """În .actualizare/ sau în logs/ ale copiei; altfel exact o cale din jurnal."""
        if is_inside(path, (work, logs)):
            return True
        try:
            return Path(os.path.realpath(path)).relative_to(real_root).as_posix() in journal_paths
        except ValueError:
            return False

    writes = [e for e in audit.events if e.name != "open" or e.is_write_open()]
    assert not _forbidden(writes), f"recuperarea a atins Registry sau Temp: {_describe(writes)}"
    outside = [e for e in writes if not all(allowed(path) for path in e.paths())]
    assert not outside, f"recuperarea a scris în afara lui .actualizare/, logs/ și a căilor din jurnal: {_describe(outside)}"
    assert any(is_inside(path, (logs,)) for e in writes for path in e.paths()), "auditul n-a văzut jurnalul pornirii: testul n-ar dovedi nimic"
    assert sorted(os.listdir(tmp_path)) == ["program"], "au apărut fișiere sau foldere lângă copia programului"

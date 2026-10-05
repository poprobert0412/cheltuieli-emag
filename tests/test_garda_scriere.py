"""Garda de scriere: pe disc apar doar iesiri/, logs/ și .profil_browser/, nimic în Registry, AppData sau folderul personal.

Primește: sursele programului și fluxurile lui rulate pe date inventate (--demo, --din-cache, --sterge-sesiunea).
Verifică: (1) static (AST): fără Path.home(), expanduser, variabile de mediu cu foldere personale, tempfile, winreg,
nici apeluri care află numele contului sau al calculatorului; (2) la execuție: un audit hook notează fiecare scriere,
ștergere sau creare făcută de program și un blocaj le oprește pe cele din afara folderelor permise (rapoarte, jurnal,
demo-data.js, profil); în plus, programul nu citește locuri cu parole (profilul real de browser, chei).
Fiecare detector e probat pe cod-capcană. Ce NU face: nu verifică ce scrie Windows sau browserul (Edge, Playwright).
"""

import ast
import os
import re
import sys
import textwrap
from pathlib import Path

import pytest

from tests.garda_audit import FLOWS, AuditRecorder, block_writes_outside, is_inside, isolated_program, prepare_flow, run_flow
from tests.garda_support import PROGRAM_DIR, dotted_name, parse_source, program_sources, relative, string_constants

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
}
MIN_REASON_LENGTH = 30


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

    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)) and not (isinstance(node, ast.ImportFrom) and node.level):
            for name in ([a.name for a in node.names] if isinstance(node, ast.Import) else [node.module or ""]):
                root = name.split(".")[0]
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
    ("import os\nos.symlink('a', 'b')", "symlink"),
])
def test_write_detector_catches_trap_code(source, expected):
    """Capcană: Path.home, expanduser, variabile AppData/Temp, tempfile, winreg, getuser și symlink trebuie prinse."""
    found = {what for what, _ in python_write_violations(ast.parse(source), "emag_spend/capcana.py")}
    assert expected in found, f"nu a fost prins «{expected}» în:\n{source}\n(prins: {sorted(found)})"


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
# Fragmente de cale (cu litere mici) ale unor locuri cu parole sau chei: programul nu are niciun motiv să le deschidă.
SENSITIVE_READ_MARKERS = (
    "/user data/", "login data", "/cookies", ".ssh", ".aws", ".gnupg", "ntuser.dat", "id_rsa", "id_ed25519", "/credentials", "keychain",
)
# Singurele intrări care pot apărea în folderul temporar al testului după un flux (ce a creat programul sau testul).
EXPECTED_TOP_LEVEL = frozenset({"iesiri", "logs", "site", "cache", "profil"})


def _describe(events) -> str:
    """Evenimentele de audit într-un singur text: nume, căi și locul din cod."""
    return "; ".join(f"{event.name} {event.paths()} la {event.where}" for event in events)


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
    assert not [e for e in writes if e.name.startswith(FORBIDDEN_AUDIT_EVENTS)], f"programul a atins Registry sau folderul Temp al sistemului: {_describe(writes)}"
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
    assert not [e for e in writes if e.name.startswith(FORBIDDEN_AUDIT_EVENTS)], f"aplicația a atins Registry sau folderul Temp al sistemului: {_describe(writes)}"
    outside = [e for e in writes if not all(is_inside(path, layout.writable_roots) for path in e.paths())]
    assert not outside, f"scrieri ale aplicației în afara folderelor permise {[str(r) for r in layout.writable_roots]}: {_describe(outside)}"
    assert any(is_inside(path, (layout.out,)) for e in writes for path in e.paths()) and any(layout.out.rglob("raport.html")), "auditul n-a văzut scrierea raportului: hook-ul nu prinde nimic și testul n-ar dovedi nimic"
    assert not layout.profile.exists(), "sesiunea nu s-a șters prin API"
    assert not layout.site_file.exists(), "o rulare din aplicație a rescris demo-data.js al site-ului"
    sensitive = [e for e in audit.events if e.name == "open" and any(marker in path.lower().replace("\\", "/") for path in e.paths() for marker in SENSITIVE_READ_MARKERS)]
    assert not sensitive, f"aplicația a deschis locuri cu parole sau chei: {_describe(sensitive)}"
    unexpected = sorted(set(os.listdir(tmp_path)) - EXPECTED_TOP_LEVEL - {"interfata_inventata"})
    assert not unexpected, f"au apărut fișiere sau foldere neașteptate lângă rezultate: {unexpected}"


def test_the_application_code_never_deletes_or_writes_anything_by_itself():
    """Static: în afară de pipeline (apelat din app_runner) și de ștergerea sesiunii (session_cleaner), modulele aplicației nu scriu și nu șterg nimic pe disc."""
    forbidden_calls = {"write_text", "write_bytes", "mkdir", "unlink", "rmdir", "rename", "replace", "rmtree", "remove", "touch", "truncate", "copyfile", "copy", "move"}
    for name in ("app_server.py", "app_security.py", "app_runs.py", "app_static.py", "app_errors.py", "app_opener.py", "run_ids.py", "progress.py"):
        tree = parse_source(PROGRAM_DIR / name)
        found = [f"{name}:{node.lineno}: .{node.func.attr}()" for node in ast.walk(tree)
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr in forbidden_calls]
        opened_for_write = [f"{name}:{node.lineno}: open(..., {ast.unparse(node.args[1])})" for node in ast.walk(tree)
                            if isinstance(node, ast.Call) and dotted_name(node.func) == "open" and len(node.args) > 1
                            and isinstance(node.args[1], ast.Constant) and any(letter in str(node.args[1].value) for letter in "wax+")]
        assert not found and not opened_for_write, f"{name} scrie sau șterge pe disc, dar el doar citește: {found + opened_for_write}"

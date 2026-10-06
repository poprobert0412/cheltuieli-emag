"""Teste pentru recuperarea la pornire după o actualizare întreruptă (update_recovery.py, update_lock.py, începutul lui ruleaza.py).

Ce verifică: (1) static: recuperarea și lacătul folosesc doar biblioteca standard, emag_spend/__init__.py nu importă nimic, iar
ruleaza.py cheamă recuperarea înaintea oricărui alt import din emag_spend (N2); (2) recover_before_start nu ridică niciodată și
întoarce și ce a notat în jurnal (P6); (3) ștergerea folderelor de lucru nu urmează legături sau joncțiuni (N4), iar revenirea nu
scrie și nu mută nimic printr-o legătură pusă după întrerupere (P5, J7, J8); (4) lacătul de sistem între două procese REALE (N5);
(5) procesul care aplică o actualizare e OMORÂT de-adevăratelea (TerminateProcess / SIGKILL) în mai multe puncte, pe o copie a
programului real cu o versiune nouă inventată (cu un modul nou importat de unul existent), apoi `ruleaza.py --versiune` din copie
trebuie să revină singur și să meargă mai departe (N8); (6) punctul de intrare al lansatoarelor, `python -m emag_spend.update_recovery`
(P1): codurile 0/1/2, ce afișează, jurnalul din logs/, și pe copia programului real după un proces omorât; (7) curățenia de sub
lacăt șterge descărcările lăsate de un proces omorât, nu și una vie (P7), iar un descarcari/ legătură e refuzat (P8).
Totul în foldere temporare, fără rețea, fără scrieri în proiect.
"""

import ast
import errno
import logging
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

from emag_spend import settings, update_apply, update_recovery
from emag_spend.version import VERSION
from tests.update_archive_support import (
    LOCK_FILE, MANIFEST, age_tree, fingerprint, install_program, make_link, newer_than, program_files, remove_link, work_dir_leftovers,
    write_archive, write_journal_by_hand,
)

PROGRAM = Path(settings.PROJECT_ROOT)
NEW = newer_than(VERSION)
OUTSIDE_FILES = {"important.txt": "al altcuiva, în afara programului\n", "sub/alt.txt": "tot în afara programului\n"}
# Un proces copil nu are voie să atârne testele la nesfârșit (o pornire normală ține sub o secundă).
SUBPROCESS_TIMEOUT_SECONDS = 120
CHILD_ENV = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1", "PYTHONUTF8": "1", "EMAG_UPDATE_CHECK": "0"}


def outside_folder(tmp_path):
    """Un folder din afara programului, cu fișiere care nu au voie să fie atinse; întoarce (calea, amprenta lui)."""
    outside = tmp_path / "in_afara"
    for name, text in OUTSIDE_FILES.items():
        (outside / name).parent.mkdir(parents=True, exist_ok=True)
        (outside / name).write_text(text, encoding="utf-8")
    return outside, fingerprint(outside, skip=())


def _journal(work, **fields):
    """Scrie de mână un jurnal „aplicare” VERSION → NEW (format 1) cu listele date."""
    write_journal_by_hand(work, VERSION, NEW, **fields)


def _half_applied(root):
    """Stare lăsată de o cădere: ruleaza.py nou în rădăcină, cel vechi în .actualizare/vechi, jurnalul în „aplicare”."""
    work = root / update_apply.WORK_DIR_NAME
    (work / update_apply.OLD_DIR_NAME).mkdir(parents=True)
    os.replace(root / "ruleaza.py", work / update_apply.OLD_DIR_NAME / "ruleaza.py")
    (root / "ruleaza.py").write_text("print('versiunea nouă, pe jumătate instalată')\n", encoding="utf-8")
    _journal(work, scrise=["ruleaza.py"], existau=["ruleaza.py"])


# ---------- (1) static: ce importă recuperarea și când rulează ----------

def _imported_modules(path: Path) -> list[str]:
    """Modulele importate oriunde într-un fișier; `from emag_spend import x` apare ca „emag_spend.x”, un import relativ ca „.”."""
    found = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                found.append(".")
            elif node.module == "emag_spend":
                found.extend(f"emag_spend.{alias.name}" for alias in node.names)
            else:
                found.append(node.module or "")
    return found


@pytest.mark.parametrize("name, allowed", [("update_lock.py", set()), ("update_recovery.py", {"emag_spend.update_lock"})])
def test_recovery_and_lock_use_only_the_standard_library(name, allowed):
    """N2: recuperarea rulează pe un arbore poate amestecat (vechi + nou): importă doar biblioteca standard (și lacătul, la fel de simplu)."""
    imported = _imported_modules(PROGRAM / "emag_spend" / name)
    foreign = [module for module in imported if module not in allowed and module.split(".")[0] not in sys.stdlib_module_names]
    assert imported, "nu am găsit niciun import: testul n-ar dovedi nimic"
    assert not foreign, f"{name} importă și {foreign}: un modul amestecat sau lipsă ar opri recuperarea înainte să înceapă"


def test_the_import_rule_catches_program_and_package_imports(tmp_path):
    """Capcană: detectorul vede `from emag_spend import x`, `from emag_spend.x import y`, importuri relative, ascunse în funcții și pachete."""
    trap = tmp_path / "capcana.py"
    trap.write_text("import os\nfrom emag_spend import settings\nfrom emag_spend.update_archive import x\nfrom . import y\n"
                    "def f():\n    import playwright\n", encoding="utf-8")
    assert _imported_modules(trap) == ["os", "emag_spend.settings", "emag_spend.update_archive", ".", "playwright"]


def test_the_package_init_imports_nothing():
    """N2: emag_spend/__init__.py rămâne fără importuri și fără cod: altfel orice import din emag_spend l-ar trage după el."""
    tree = ast.parse((PROGRAM / "emag_spend" / "__init__.py").read_text(encoding="utf-8"))
    code = [node for node in tree.body if not (isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant))]
    assert not code, f"emag_spend/__init__.py are cod sau importuri: {[ast.unparse(node) for node in code]}"


def _is_foreign_import(node: ast.stmt) -> bool:
    """True pentru un import la nivel de modul care nu e din biblioteca standard (emag_spend, playwright)."""
    if isinstance(node, ast.Import):
        return any(alias.name.split(".")[0] not in sys.stdlib_module_names for alias in node.names)
    return isinstance(node, ast.ImportFrom) and (node.level > 0 or (node.module or "").split(".")[0] not in sys.stdlib_module_names)


def test_ruleaza_recovers_before_importing_anything_else_from_the_program():
    """N2: în ruleaza.py, primul import din afara bibliotecii standard e recuperarea, iar recuperarea rulează înaintea celorlalte."""
    body = ast.parse((PROGRAM / "ruleaza.py").read_text(encoding="utf-8")).body
    foreign = [index for index, node in enumerate(body) if _is_foreign_import(node)]
    first = body[foreign[0]]
    assert isinstance(first, ast.ImportFrom) and first.module == "emag_spend.update_recovery", \
        f"primul import din afara bibliotecii standard e «{ast.unparse(first)}», nu recuperarea"
    calls = [index for index, node in enumerate(body)
             if any(isinstance(sub, ast.Call) and getattr(sub.func, "id", None) == "recover_before_start" for sub in ast.walk(node))]
    assert calls, "ruleaza.py nu cheamă recover_before_start la nivel de modul"
    assert calls[0] < foreign[1], "recuperarea trebuie să ruleze înaintea oricărui alt import din emag_spend sau din pachete"


# ---------- (2) recover_before_start nu ridică niciodată ----------

def test_with_nothing_to_recover_nothing_is_reported_or_written(tmp_path):
    """Fără jurnal: niciun mesaj, nicio eroare și nimic scris (nici .actualizare)."""
    from emag_spend.update_recovery import RecoveryOutcome, recover_before_start

    root = tmp_path / "program"
    install_program(root, VERSION)
    before = fingerprint(root, skip=())
    assert recover_before_start(root) == RecoveryOutcome(None, None)
    assert fingerprint(root, skip=()) == before


def test_an_interrupted_update_is_reverted_and_reported_once(tmp_path):
    """O aplicare întreruptă se anulează, cu mesaj; a doua pornire nu mai are nimic de spus."""
    from emag_spend.update_recovery import RecoveryOutcome, recover_before_start

    root = tmp_path / "program"
    install_program(root, VERSION)
    before = fingerprint(root)
    _half_applied(root)
    outcome = recover_before_start(root)
    assert outcome.error is None and f"am revenit la versiunea {VERSION}" in outcome.message
    assert fingerprint(root) == before and work_dir_leftovers(root) == []
    assert recover_before_start(root) == RecoveryOutcome(None, None)


def test_recovery_problems_come_back_as_errors_never_as_exceptions(tmp_path, monkeypatch):
    """Jurnal deteriorat, lacăt ocupat, o eroare neprevăzută sau Ctrl+C în timpul revenirii: eroare în rezultat, nicio excepție."""
    from emag_spend import update_lock, update_recovery

    root = tmp_path / "program"
    install_program(root, VERSION)
    work = root / update_apply.WORK_DIR_NAME
    work.mkdir()
    (work / update_apply.JOURNAL_NAME).write_text("{nu e json", encoding="utf-8")
    assert "Jurnalul actualizării" in update_recovery.recover_before_start(root).error
    (work / update_apply.JOURNAL_NAME).unlink()
    _journal(work, scrise=["ruleaza.py"], existau=["ruleaza.py"])
    with update_lock.UpdateLock(work / update_apply.LOCK_NAME):
        assert update_recovery.recover_before_start(root).error == update_lock.MESSAGE_BUSY
    for failure in (RuntimeError("eroare neprevăzută, inventată"), KeyboardInterrupt()):
        monkeypatch.setattr(update_recovery, "revert", lambda *args, failure=failure: (_ for _ in ()).throw(failure))
        outcome = update_recovery.recover_before_start(root)
        assert outcome.message is None and outcome.error, f"{failure!r} trebuia întoarsă ca eroare"
    assert (work / update_apply.JOURNAL_NAME).is_file(), "după o recuperare nereușită jurnalul rămâne, pentru pornirea următoare"


def test_recovery_refuses_work_folders_that_are_links_and_touches_nothing(tmp_path):
    """N4: .actualizare/vechi legătură spre alt loc → eroare; ținta legăturii și programul rămân neatinse."""
    from emag_spend.update_recovery import recover_before_start

    root = tmp_path / "program"
    install_program(root, VERSION)
    outside, outside_before = outside_folder(tmp_path)
    work = root / update_apply.WORK_DIR_NAME
    _journal(work, sterse=["important.txt"])
    make_link(outside, work / update_apply.OLD_DIR_NAME)
    before = fingerprint(root)
    try:
        outcome = recover_before_start(root)
        assert outcome.message is None and "legătură" in outcome.error
        assert fingerprint(root) == before and fingerprint(outside, skip=()) == outside_before
    finally:
        remove_link(work / update_apply.OLD_DIR_NAME)


# ---------- (3) ștergerea folderelor de lucru: legăturile se scot, nu se urmează (N4, S1) ----------

def test_removing_a_tree_removes_a_link_inside_but_never_what_it_points_to(tmp_path):
    """O joncțiune (Windows) sau legătură simbolică din folderul șters se scoate doar ea; folderul spre care arată rămâne întreg."""
    from emag_spend.update_recovery import remove_tree

    outside, outside_before = outside_folder(tmp_path)
    tree = tmp_path / "de_sters"
    (tree / "sub" / "adanc").mkdir(parents=True)
    (tree / "fisier.txt").write_text("x", encoding="utf-8")
    (tree / "sub" / "adanc" / "y.txt").write_text("y", encoding="utf-8")
    make_link(outside, tree / "sub" / "legatura")
    remove_tree(tree)
    assert not os.path.lexists(tree), "folderul de lucru trebuia șters cu totul"
    assert fingerprint(outside, skip=()) == outside_before, "ștergerea a coborât în legătură și a golit un folder din afară"


def test_removing_a_tree_refuses_a_top_folder_that_is_a_link(tmp_path):
    """Vârful care e legătură se refuză: nici legătura, nici ținta nu se ating."""
    from emag_spend.update_recovery import remove_tree

    outside, outside_before = outside_folder(tmp_path)
    link = tmp_path / "varf"
    make_link(outside, link)
    try:
        with pytest.raises(OSError, match="legătură"):
            remove_tree(link)
        assert os.path.lexists(link) and fingerprint(outside, skip=()) == outside_before
    finally:
        remove_link(link)


def test_removing_a_tree_removes_a_file_symlink_without_touching_its_target(tmp_path):
    """O legătură simbolică de fișier se scoate; fișierul spre care arată rămâne (unde sistemul permite legături de fișier)."""
    from emag_spend.update_recovery import remove_tree

    target = tmp_path / "tinta.txt"
    target.write_text("al altcuiva\n", encoding="utf-8")
    tree = tmp_path / "de_sters"
    tree.mkdir()
    try:
        os.symlink(target, tree / "legatura.txt")
    except OSError as error:  # Windows fără Developer Mode sau drepturi de administrator
        pytest.skip(f"legăturile simbolice de fișier nu se pot crea aici: {error}")
    remove_tree(tree)
    assert not os.path.lexists(tree) and target.read_text(encoding="utf-8") == "al altcuiva\n"


# ---------- (4) lacătul de sistem între două procese reale (N5, S2) ----------

# După cât timp își eliberează lacătul procesul din testul de așteptare: destul cât încercarea să înceapă cu lacătul ocupat,
# puțin față de așteptarea din update_lock.py (2 s). Fix în test, nu calculat din constanta verificată.
RELEASE_AFTER_SECONDS = 0.5

LOCK_HOLDER = r"""
import sys
from pathlib import Path
sys.path.insert(0, sys.argv[2])
from emag_spend.update_lock import UpdateLock
with UpdateLock(Path(sys.argv[1])):
    print("TIN", flush=True)
    sys.stdin.read()
"""


def test_a_second_process_gets_busy_and_the_lock_file_is_never_deleted(tmp_path):
    """N5: cât îl ține alt proces, lacătul e „ocupat” și fișierul lui nu e șters sau înlocuit; după moartea procesului e liber.

    Fișierul-lacăt rămâne pe disc, gol (sistemul eliberează lacătul la moartea procesului, deci nu există „lacăt abandonat”).
    """
    from emag_spend import update_lock

    path = tmp_path / ".actualizare" / "lacat"
    holder = subprocess.Popen([sys.executable, "-c", LOCK_HOLDER, str(path), str(PROGRAM)], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, env=CHILD_ENV)
    try:
        assert holder.stdout.readline().strip() == b"TIN", "procesul care ține lacătul n-a pornit"
        identity = os.stat(path).st_ino
        with pytest.raises(Exception, match="altă actualizare e în curs"):
            update_lock.UpdateLock(path).acquire()
        assert os.stat(path).st_ino == identity, "al doilea proces a șters sau a înlocuit lacătul celui care îl ține"
    finally:
        holder.kill()  # TerminateProcess / SIGKILL: fără eliberare din program
        holder.wait(timeout=SUBPROCESS_TIMEOUT_SECONDS)
    with update_lock.UpdateLock(path):
        pass
    assert path.is_file() and path.stat().st_size == 0, "lacătul e un fișier permanent și gol"


def test_a_lock_freed_while_waiting_is_taken_instead_of_reporting_busy(tmp_path):
    """Lacătul eliberat în fereastra de așteptare (proces care se termină, sau Windows care eliberează târziu lacătul unui proces
    omorât) se ia, fără „ocupat”: pornirea de după o cădere nu pică doar pentru că sistemul n-a apucat să elibereze lacătul."""
    import threading

    from emag_spend import update_lock

    path = tmp_path / ".actualizare" / "lacat"
    holder = subprocess.Popen([sys.executable, "-c", LOCK_HOLDER, str(path), str(PROGRAM)], stdin=subprocess.PIPE,
                              stdout=subprocess.PIPE, env=CHILD_ENV)
    assert holder.stdout.readline().strip() == b"TIN", "procesul care ține lacătul n-a pornit"
    threading.Timer(RELEASE_AFTER_SECONDS, holder.stdin.close).start()  # celălalt proces își termină treaba și iese
    started = time.monotonic()
    try:
        with update_lock.UpdateLock(path):
            waited = time.monotonic() - started
    finally:
        holder.kill()
        holder.wait(timeout=SUBPROCESS_TIMEOUT_SECONDS)
    assert waited >= RELEASE_AFTER_SECONDS / 2, "lacătul trebuia să fie încă ocupat la început: testul n-ar dovedi așteptarea"


# ---------- (5) procesul omorât de-adevăratelea în timpul aplicării (N8, R1) ----------

IMPORTER = "emag_spend/app_server.py"  # importă în versiunea nouă modulul nou, scris DUPĂ el (ordinea alfabetică a scrierilor)
NEW_MODULE = "emag_spend/zz_modul_nou.py"
DELETED = "docs/de_sters.md"  # doar în versiunea veche: se șterge la aplicare
NEW_MARK = "\n# versiune nouă, inventată de test\n".encode("utf-8")

# Copilul aplică arhiva pe copie și se omoară singur (TerminateProcess pe Windows, SIGKILL în rest) în punctul cerut:
# „dupa” = după primul os.replace care atinge calea; „nr” = după al N-lea os.replace; „jurnal” = după al N-lea jurnal scris;
# „copie” = după copia de siguranță (os.link) a căii, înainte s-o înlocuiască. Nicio revenire sau curățenie nu mai apucă să ruleze.
KILL_CHILD = r"""
import os, signal, sys
from pathlib import Path

root, archive, version, mode, value = Path(sys.argv[1]).resolve(), Path(sys.argv[2]), sys.argv[3], sys.argv[4], sys.argv[5]
sys.path.insert(0, str(root))
from emag_spend import update_apply

if Path(update_apply.__file__).resolve().parent.parent != root:
    raise SystemExit("update_apply nu e cel din copie")
watched = os.path.normcase(os.path.abspath(root / value))
state = {"replace": 0, "journal": 0}
real_replace, real_link = os.replace, getattr(os, "link", None)


def die(what):
    print("OMORAT dupa " + what, flush=True)
    os.kill(os.getpid(), getattr(signal, "SIGKILL", signal.SIGTERM))


def touches(*paths):
    return watched in {os.path.normcase(os.path.abspath(os.fspath(path))) for path in paths}


def replace(source, target, *args, **kwargs):
    real_replace(source, target, *args, **kwargs)
    state["replace"] += 1
    state["journal"] += os.path.basename(os.fspath(target)) == "jurnal.json"
    if (mode == "nr" and state["replace"] == int(value)) or (mode == "dupa" and touches(source, target)) \
            or (mode == "jurnal" and state["journal"] == int(value)):
        die(f"{mode} {value}")


def link(source, target, *args, **kwargs):
    real_link(source, target, *args, **kwargs)
    if mode == "copie" and touches(source):
        die(f"copia lui {value}")


os.replace = replace
if real_link is not None:
    os.link = link
update_apply.apply_update(archive, root, version)
print("TERMINAT fara sa fie omorat", flush=True)
"""


def _real_program_files() -> dict[str, bytes]:
    """Codul REAL al programului (ruleaza.py și emag_spend/**/*.py), plus lansatoarele și fișierele obligatorii inventate."""
    files = {name: data for name, data in program_files(VERSION).items() if not name.endswith(".py")}
    for path in sorted((PROGRAM / "emag_spend").rglob("*.py")):
        if "__pycache__" not in path.parts:
            files[path.relative_to(PROGRAM).as_posix()] = path.read_bytes()
    files["ruleaza.py"] = (PROGRAM / "ruleaza.py").read_bytes()
    return files


def _new_version_files(old: dict[str, bytes]) -> dict[str, bytes]:
    """Versiunea nouă inventată: fiecare .py schimbat (se vede orice fișier nerefăcut), VERSION nou, un modul nou importat de unul vechi."""
    new = {name: data + NEW_MARK if name.endswith(".py") else data for name, data in old.items() if name != DELETED}
    version = re.sub(rb'(?m)^VERSION = "[^"]*"', f'VERSION = "{NEW}"'.encode("utf-8"), new["emag_spend/version.py"], count=1)
    assert version != new["emag_spend/version.py"], "nu am găsit VERSION în version.py"
    new["emag_spend/version.py"] = version
    new[IMPORTER] += "from emag_spend import zz_modul_nou  # noqa: E402,F401 - legătură inventată de test\n".encode("utf-8")
    new[NEW_MODULE] = '"""Modul nou, inventat de test: există doar în versiunea nouă."""\n'.encode("utf-8")
    return new


@pytest.fixture(scope="module")
def real_update(tmp_path_factory):
    """Programul real „instalat” la VERSION (șablon), arhiva versiunii NEW inventate și amprentele așteptate ale celor două."""
    base = tmp_path_factory.mktemp("omor")
    old = {**_real_program_files(), DELETED: "rămas din versiunea veche\n".encode("utf-8")}
    new = _new_version_files(old)
    template = base / "sablon"
    install_program(template, VERSION, old)
    archive = write_archive(base / "arhiva" / f"cheltuieli-emag-v{NEW}.zip", NEW, new)
    finished = base / "terminat"
    install_program(finished, NEW, new)
    longest = max(len(str(base / "p_ocupat")) + len("/.actualizare/vechi/") + len(name) for name in new)  # cea mai lungă copie
    if os.name == "nt" and longest >= update_apply.WINDOWS_MAX_PATH:
        pytest.skip(f"folderul temporar e prea adânc pentru calea clasică Windows ({longest} caractere): rulează cu --basetemp scurt")
    return {"base": base, "template": template, "archive": archive, "old": fingerprint(template, skip=_SKIP),
            "new": fingerprint(finished, skip=_SKIP), "count": len(new)}


_SKIP = (".actualizare", "logs", "__pycache__")


def _copy(real_update, name):
    """O copie proaspătă a programului instalat, scurtă (calea contează pe Windows)."""
    root = real_update["base"] / name
    shutil.copytree(real_update["template"], root)
    return root


def _run(arguments, cwd):
    """Rulează Python-ul testelor cu argumentele date; întoarce (cod, ieșirea completă: stdout + stderr)."""
    done = subprocess.run([sys.executable, *arguments], cwd=cwd, env=CHILD_ENV, capture_output=True,
                          timeout=SUBPROCESS_TIMEOUT_SECONDS)
    return done.returncode, (done.stdout + done.stderr).decode("utf-8", errors="replace")


KILL_POINTS = {
    "dupa-jurnal": ("dupa", ".actualizare/jurnal.json", "vechi, fără mesaj"),
    "copie-primul-fisier": ("copie", "config/categorii.json", "vechi, fără mesaj"),
    "dupa-modulul-care-importa-unul-nou": ("dupa", IMPORTER, "vechi"),
    "copie-modulul-care-importa-unul-nou": ("copie", IMPORTER, "vechi"),
    "dupa-recuperare": ("dupa", "emag_spend/update_recovery.py", "vechi"),
    "dupa-version": ("dupa", "emag_spend/version.py", "vechi"),
    "dupa-ruleaza": ("dupa", "ruleaza.py", "vechi"),
    "dupa-stergere": ("dupa", DELETED, "vechi"),
    "nr-o-treime": ("nr", "1/3", "vechi"),
    "nr-doua-treimi": ("nr", "2/3", "vechi"),
    "dupa-jurnalul-gata": ("jurnal", "2", "nou"),
}


@pytest.mark.parametrize("mode, value, expected", KILL_POINTS.values(), ids=KILL_POINTS.keys())
def test_a_process_killed_while_applying_is_recovered_by_the_next_start(real_update, request, mode, value, expected):
    """N8, R1: procesul care aplică e omorât de-adevăratelea; `ruleaza.py --versiune` din copie revine singur și merge mai departe.

    După o cădere în timpul mutărilor: versiunea veche, octet cu octet, cod 0, cu mesaj doar dacă s-a refăcut ceva (N3), iar a doua
    pornire nu mai spune nimic. După jurnalul „gata”: versiunea nouă. În .actualizare rămâne doar lacătul gol.
    """
    if mode == "nr":
        numerator, denominator = (int(part) for part in value.split("/"))
        value = str(real_update["count"] * numerator // denominator)
    root = _copy(real_update, f"p_{list(KILL_POINTS).index(request.node.callspec.id):02d}")
    code, output = _run(["-c", KILL_CHILD, str(root), str(real_update["archive"]), NEW, mode, value], root)
    assert code != 0 and "OMORAT" in output, f"copilul nu a fost omorât în punctul cerut (cod {code}):\n{output[-1500:]}"
    assert (root / update_apply.WORK_DIR_NAME / update_apply.JOURNAL_NAME).is_file(), "omorât înainte de jurnal: punctul nu testează nimic"
    version = NEW if expected == "nou" else VERSION
    code, first = _run([str(root / "ruleaza.py"), "--versiune"], root)
    assert code == 0, f"prima pornire după cădere a ieșit cu {code}:\n{first[-2000:]}"
    assert f"Cheltuieli eMAG {version}" in first and "Traceback" not in first, first[-2000:]
    if expected == "vechi":
        assert f"am revenit la versiunea {VERSION}" in first, f"lipsește mesajul de revenire:\n{first[-1000:]}"
    else:
        assert "a fost întreruptă" not in first, f"mesaj de revenire fals (nu se refăcuse nimic):\n{first[-1000:]}"
    assert fingerprint(root, skip=_SKIP) == real_update["new" if expected == "nou" else "old"], "programul nu e întreg după recuperare"
    assert work_dir_leftovers(root) == [], f"în .actualizare au rămas {work_dir_leftovers(root)}"
    code, second = _run([str(root / "ruleaza.py"), "--versiune"], root)
    assert code == 0 and f"Cheltuieli eMAG {version}" in second and "a fost întreruptă" not in second, second[-1000:]


def test_a_start_while_another_process_holds_the_lock_stops_with_code_1_and_touches_nothing(real_update):
    """Pornire în timp ce alt proces aplică (ține lacătul) și jurnalul e „aplicare”: mesaj, cod 1, nimic altceva rulat sau atins în
    program; doar motivul rămâne în logs/ (P6)."""
    from emag_spend import update_lock

    root = _copy(real_update, "p_ocupat")
    work = root / update_apply.WORK_DIR_NAME
    _journal(work, scrise=["ruleaza.py"], existau=["ruleaza.py"])
    journal = (work / update_apply.JOURNAL_NAME).read_bytes()
    before = fingerprint(root, skip=_SKIP_WITH_LOGS)
    with update_lock.UpdateLock(work / update_apply.LOCK_NAME):  # pe Windows lacătul blochează și citirea octetului lui: amprenta îl ocolește
        code, output = _run([str(root / "ruleaza.py"), "--versiune"], root)
    after = fingerprint(root, skip=_SKIP_WITH_LOGS)
    assert code == 1, output[-1500:]
    assert update_lock.MESSAGE_BUSY in output and "Cheltuieli eMAG" not in output and "Traceback" not in output, output[-1500:]
    assert after == before, "pornirea a schimbat ceva deși lacătul era ținut de alt proces"
    assert update_lock.MESSAGE_BUSY in _log_text(root), "motivul opririi trebuia să rămână în logs/ (P6)"
    assert (work / update_apply.JOURNAL_NAME).read_bytes() == journal, "jurnalul trebuia lăsat neatins pentru cel care aplică"
    assert sorted(os.listdir(work)) == [update_apply.JOURNAL_NAME, update_apply.LOCK_NAME] and (root / MANIFEST).is_file()


# ---------- (6) punctul de intrare al lansatoarelor: python -m emag_spend.update_recovery (P1) ----------

_LOGS = update_recovery.LOGS_DIR_NAME
_SKIP_WITH_LOGS = (update_apply.WORK_DIR_NAME, _LOGS)


def _log_text(root) -> str:
    """Tot textul din jurnalele programului din `root` (logs/*.log), în ordinea numelor; "" dacă nu există niciunul."""
    return "".join(path.read_text(encoding="utf-8") for path in sorted((root / _LOGS).glob("*.log")))


def _recovered_message() -> str:
    """Mesajul de revenire pentru jurnalul scris de _journal (VERSION → NEW)."""
    return update_recovery.MESSAGE_RECOVERED.format(to_version=NEW, from_version=VERSION)


def test_the_exit_codes_of_the_launcher_entry_point_are_a_fixed_contract():
    """P1: lansatoarele tuturor versiunilor se bazează pe 0 (mergi mai departe), 1 (oprește-te cu mesajul) și 2 (folosire greșită)."""
    assert (update_recovery.EXIT_RECOVERY_OK, update_recovery.EXIT_RECOVERY_FAILED, update_recovery.EXIT_USAGE) == (0, 1, 2)
    assert update_recovery.PROGRAM_ROOT == Path(settings.PROJECT_ROOT).resolve(), "punctul de intrare lucrează pe folderul programului"


def test_the_names_and_the_log_of_the_recovery_match_the_rest_of_the_program(tmp_path):
    """Numele din .actualizare și jurnalul pornirii sunt cele din settings.py și run_logger.py (recuperarea nu le poate importa, N2)."""
    from emag_spend import run_logger

    assert update_recovery.WORK_DIR_NAME == settings.UPDATE_WORK_DIR.name
    assert update_recovery.DOWNLOADS_DIR_NAME == settings.UPDATE_DOWNLOAD_DIR.name and settings.UPDATE_DOWNLOAD_DIR.parent == settings.UPDATE_WORK_DIR
    assert update_recovery.LOGS_DIR_NAME == settings.LOGS_DIR.name and settings.LOGS_DIR.parent == settings.PROJECT_ROOT
    assert update_recovery.LOG_FORMAT == run_logger.LOG_FORMAT
    handlers = list(logging.getLogger().handlers)
    try:
        made_by_the_program = run_logger.setup_logging(tmp_path / "logs").name
    finally:
        for handler in list(logging.getLogger().handlers):
            logging.getLogger().removeHandler(handler)
            handler.close()
        for handler in handlers:
            logging.getLogger().addHandler(handler)
    pattern = re.escape(update_recovery.LOG_FILE_NAME_FORMAT).replace("%Y", "[0-9]{4}")
    for code in ("%m", "%d", "%H", "%M", "%S"):
        pattern = pattern.replace(code, "[0-9]{2}")
    assert re.fullmatch(pattern, made_by_the_program), f"run_logger scrie «{made_by_the_program}», recuperarea ar scrie «{pattern}»"


def test_the_launcher_entry_point_reverts_shows_the_message_once_and_leaves_a_log(tmp_path, capsys):
    """Jurnal „aplicare”: revine, afișează mesajul între rânduri goale, cod 0 și lasă urma în logs/; a doua oară nu mai are nimic."""
    root = tmp_path / "program"
    install_program(root, VERSION)
    before = fingerprint(root, skip=_SKIP_WITH_LOGS)
    _half_applied(root)
    assert update_recovery.main([], root) == update_recovery.EXIT_RECOVERY_OK
    assert capsys.readouterr().out == f"\n{_recovered_message()}\n\n"
    assert fingerprint(root, skip=_SKIP_WITH_LOGS) == before and work_dir_leftovers(root) == []
    logs = sorted((root / _LOGS).glob("*.log"))
    assert len(logs) == 1, "punctul de intrare trebuie să lase urma recuperării în logs/ (§9)"
    text = logs[0].read_text(encoding="utf-8")
    assert "[emag_spend.update_recovery] WARNING: actualizare: aplicarea întreruptă" in text, text
    assert update_recovery.LOG_STARTUP_OUTCOME % _recovered_message() in text, text
    assert update_recovery.main([], root) == update_recovery.EXIT_RECOVERY_OK
    assert capsys.readouterr().out == "" and sorted((root / _LOGS).glob("*.log")) == logs, "a doua pornire nu mai are nimic de spus sau de scris"


def test_the_launcher_entry_point_with_nothing_to_do_says_and_writes_nothing(tmp_path, capsys):
    """Fără jurnal: cod 0, nimic pe ecran și nimic pe disc (nici .actualizare, nici logs/)."""
    root = tmp_path / "program"
    install_program(root, VERSION)
    before = fingerprint(root, skip=())
    assert update_recovery.main([], root) == update_recovery.EXIT_RECOVERY_OK
    assert capsys.readouterr().out == "" and fingerprint(root, skip=()) == before


@pytest.mark.parametrize("problem", ["jurnal-deteriorat", "lacat-ocupat"])
def test_the_launcher_entry_point_stops_with_code_1_and_the_reason(tmp_path, capsys, problem):
    """Recuperare imposibilă acum: «EROARE: <motiv>», cod 1, motivul și în logs/, programul neatins și jurnalul rămas."""
    from emag_spend import update_lock

    root = tmp_path / "program"
    install_program(root, VERSION)
    work = root / update_apply.WORK_DIR_NAME
    if problem == "jurnal-deteriorat":
        work.mkdir()
        (work / update_apply.JOURNAL_NAME).write_text("{nu e json", encoding="utf-8")
        reason = "Jurnalul actualizării"
    else:
        _half_applied(root)
        reason = update_lock.MESSAGE_BUSY
    before = fingerprint(root, skip=_SKIP_WITH_LOGS)
    journal = (work / update_apply.JOURNAL_NAME).read_bytes()
    lock = update_lock.UpdateLock(work / update_apply.LOCK_NAME)
    if problem == "lacat-ocupat":
        lock.acquire()
    try:
        assert update_recovery.main([], root) == update_recovery.EXIT_RECOVERY_FAILED
    finally:
        lock.release()
    output = capsys.readouterr().out
    assert output.startswith("\nEROARE: ") and reason in output, output
    assert reason in _log_text(root), "motivul trebuia să rămână și în jurnal"
    assert fingerprint(root, skip=_SKIP_WITH_LOGS) == before and (work / update_apply.JOURNAL_NAME).read_bytes() == journal


def test_the_launcher_entry_point_refuses_arguments_and_does_nothing(tmp_path, capsys):
    """Cu argumente: cod 2, folosirea corectă pe ecran, nicio revenire și nimic scris (jurnalul rămâne pentru pornirea corectă)."""
    root = tmp_path / "program"
    install_program(root, VERSION)
    _half_applied(root)
    before = fingerprint(root, skip=())
    assert update_recovery.main(["--orice"], root) == update_recovery.EXIT_USAGE
    assert update_recovery.MESSAGE_USAGE in capsys.readouterr().out
    assert fingerprint(root, skip=()) == before


def _program_with_real_recovery(root) -> None:
    """Un program inventat, dar cu recuperarea, lacătul și pachetul emag_spend REALE (cele pe care le rulează `python -m`)."""
    files = program_files(VERSION)
    for name in ("emag_spend/__init__.py", "emag_spend/update_recovery.py", "emag_spend/update_lock.py"):
        files[name] = (PROGRAM / name).read_bytes()
    install_program(root, VERSION, files)


def test_python_dash_m_runs_the_recovery_of_the_program_it_belongs_to(tmp_path):
    """`python -m emag_spend.update_recovery` din folderul programului: revine pe ACEL program, cod 0, mesajul, jurnalul în logs/ cu
    numele real al modulului; a doua oară nimic; un jurnal deteriorat → cod 1 și «EROARE: …», fără traceback."""
    root = tmp_path / "program"
    _program_with_real_recovery(root)
    before = fingerprint(root, skip=_SKIP_WITH_LOGS)
    _half_applied(root)
    code, output = _run(["-m", "emag_spend.update_recovery"], root)
    assert code == 0 and _recovered_message() in output and "Traceback" not in output, output[-1500:]
    assert fingerprint(root, skip=_SKIP_WITH_LOGS) == before and work_dir_leftovers(root) == []
    assert "[emag_spend.update_recovery] WARNING: actualizare: aplicarea întreruptă" in _log_text(root), _log_text(root)
    code, output = _run(["-m", "emag_spend.update_recovery"], root)
    assert code == 0 and output.strip() == "", output
    (root / update_apply.WORK_DIR_NAME / update_apply.JOURNAL_NAME).write_text("{nu e json", encoding="utf-8")
    code, output = _run(["-m", "emag_spend.update_recovery"], root)
    assert code == 1 and "EROARE: Jurnalul actualizării" in output and "Traceback" not in output, output[-1500:]


LAUNCHER_KILL_POINTS = ("dupa-modulul-care-importa-unul-nou", "dupa-recuperare", "dupa-jurnalul-gata")


@pytest.mark.parametrize("name", LAUNCHER_KILL_POINTS)
def test_a_killed_apply_is_recovered_by_the_launcher_entry_point_before_anything_else(real_update, name):
    """P1: după un proces omorât, lansatorul rulează întâi `python -m emag_spend.update_recovery` (pe arborele amestecat, cu recuperarea
    poate deja nouă): cod 0, programul întreg; apoi `ruleaza.py --versiune` nu mai are nimic de refăcut."""
    mode, value, expected = KILL_POINTS[name]
    root = _copy(real_update, f"l_{LAUNCHER_KILL_POINTS.index(name):02d}")
    code, output = _run(["-c", KILL_CHILD, str(root), str(real_update["archive"]), NEW, mode, value], root)
    assert code != 0 and "OMORAT" in output, f"copilul nu a fost omorât în punctul cerut (cod {code}):\n{output[-1500:]}"
    code, first = _run(["-m", "emag_spend.update_recovery"], root)
    assert code == 0 and "Traceback" not in first, first[-2000:]
    assert ("am revenit la versiunea" in first) == (expected == "vechi"), first[-1000:]
    assert fingerprint(root, skip=_SKIP) == real_update["new" if expected == "nou" else "old"], "programul nu e întreg după recuperare"
    assert work_dir_leftovers(root) == [], f"în .actualizare au rămas {work_dir_leftovers(root)}"
    version = NEW if expected == "nou" else VERSION
    code, second = _run([str(root / "ruleaza.py"), "--versiune"], root)
    assert code == 0 and f"Cheltuieli eMAG {version}" in second and "a fost întreruptă" not in second, second[-1000:]


# ---------- (7) ce notează recuperarea ajunge în jurnal (P6) ----------

def _blocked_at_revert(monkeypatch, root, relative):
    """os.replace care nu poate pune la loc `relative` în rădăcină (ca un fișier ținut deschis), cu sursa și ținta în eroare, ca sistemul."""
    real, target = os.replace, os.path.normcase(os.path.abspath(root / relative))

    def blocked(source, destination, *args, **kwargs):
        """Refuză doar înlocuirea fișierului ales din rădăcină."""
        if os.path.normcase(os.path.abspath(destination)) == target:
            raise PermissionError(errno.EACCES, "folosit de alt program (eroare inventată)", os.fspath(source), None, os.fspath(destination))
        return real(source, destination, *args, **kwargs)

    monkeypatch.setattr(update_recovery, "REPLACE_RETRY_DELAY_SECONDS", 0)
    monkeypatch.setattr(os, "replace", blocked)


def test_what_the_startup_recovery_notes_comes_back_with_its_outcome(tmp_path, monkeypatch):
    """P6: un fișier blocat la revenire e notat (ERROR, cu calea lui) în outcome.records; colectorul se scoate apoi din logger."""
    root = tmp_path / "program"
    install_program(root, VERSION)
    _half_applied(root)
    level = update_recovery.logger.level
    _blocked_at_revert(monkeypatch, root, "ruleaza.py")
    outcome = update_recovery.recover_before_start(root)
    assert outcome.message is None and "nu s-a terminat" in outcome.error, outcome
    noted = [(record.levelname, record.getMessage()) for record in outcome.records]
    assert any(level_name == "ERROR" and "nu am putut reface ruleaza.py" in text for level_name, text in noted), noted
    assert all(record.levelno >= logging.INFO for record in outcome.records)
    assert not any(isinstance(handler, update_recovery._RecordCollector) for handler in update_recovery.logger.handlers)
    assert update_recovery.logger.level == level, "nivelul loggerului trebuia readus"
    monkeypatch.undo()
    reverted = update_recovery.recover_before_start(root)
    assert reverted.message == _recovered_message()
    assert any("a fost anulată" in record.getMessage() for record in reverted.records), [r.getMessage() for r in reverted.records]


@pytest.mark.skipif(os.name != "nt", reason="un fișier ținut deschis blochează înlocuirea lui doar pe Windows")
def test_a_file_held_open_during_the_startup_revert_is_named_in_the_log(real_update):
    """P6 la execuție: un fișier al programului ținut deschis cât rulează revenirea; `python -m emag_spend.update_recovery` și apoi
    `ruleaza.py --versiune` ies cu 1, iar logs/ numește fișierul; închis, pornirea următoare revine și programul e întreg."""
    root = _copy(real_update, "p_blocat")
    work = root / update_apply.WORK_DIR_NAME
    blocked = root / "docs" / "ghid.md"
    (work / update_apply.OLD_DIR_NAME / "docs").mkdir(parents=True)
    os.replace(blocked, work / update_apply.OLD_DIR_NAME / "docs" / "ghid.md")
    blocked.write_text("versiunea nouă, pe jumătate instalată\n", encoding="utf-8")
    _journal(work, scrise=["docs/ghid.md"], existau=["docs/ghid.md"])
    with open(blocked, "rb"):
        code_launcher, launcher = _run(["-m", "emag_spend.update_recovery"], root)
        code_start, start = _run([str(root / "ruleaza.py"), "--versiune"], root)
    assert code_launcher == 1 and "EROARE:" in launcher and "docs/ghid.md" in launcher, launcher[-1500:]
    assert code_start == 1 and "Cheltuieli eMAG" not in start, start[-1500:]
    assert _log_text(root).count("nu am putut reface docs/ghid.md") >= 2, f"logs/ nu numește fișierul blocat:\n{_log_text(root)[-2000:]}"
    code, output = _run(["-m", "emag_spend.update_recovery"], root)
    assert code == 0 and "am revenit la versiunea" in output, output[-1500:]
    assert fingerprint(root, skip=_SKIP) == real_update["old"] and work_dir_leftovers(root) == []


# ---------- (8) revenirea nu scrie prin legături (P5) ----------

# Fiecare caz: legătura pusă după întrerupere (relativă la program), jurnalul „aplicare” și ce pregătește cazul în program.
# Fără regula P5, revenirea ar muta un fișier din afară în program (J7), ar suprascrie unul din afară (J8), ar muta un fișier al
# programului în afară, ar crea sau ar scoate un folder în afară.
LINKED_REVERTS = {
    "J7-vechi": ("vechi/docs", dict(scrise=["docs/ghid.md"], existau=["docs/ghid.md"])),
    "J8-radacina": ("docs", dict(scrise=["docs/ghid.md"], existau=["docs/ghid.md"])),
    "nou": ("nou/docs", dict(scrise=["docs/pagina_noua.md"], existau=[])),
    "sters-din-vechi": ("vechi/docs", dict(sterse=["docs/ghid.md"])),
    "folder-scos": ("docs", dict(foldere_sterse=["docs/scos"])),
    "folder-nou": ("docs", dict(foldere_noi=["docs/gol"])),
    "folder-nou-devenit-legatura": ("docs", dict(foldere_noi=["docs"])),
}


@pytest.mark.parametrize("linked, journal", LINKED_REVERTS.values(), ids=LINKED_REVERTS.keys())
def test_a_revert_never_writes_through_a_link_put_there_after_the_interruption(tmp_path, linked, journal):
    """P5: o cale de revenire sub o legătură (în program sau în .actualizare/nou|vechi) se sare și intră la „nerefăcute”: recuperarea
    se oprește cu MESSAGE_REVERT_INCOMPLETE, jurnalul rămâne, iar folderul din afară și programul rămân neatinse."""
    root = tmp_path / "program"
    install_program(root, VERSION)
    outside = tmp_path / "in_afara"
    outside.mkdir()
    (outside / "ghid.md").write_text("copia utilizatorului, în afara programului\n", encoding="utf-8")
    (outside / "gol").mkdir()  # un folder gol al utilizatorului: revenirea fără P5 l-ar scoate
    work = root / update_apply.WORK_DIR_NAME
    if linked == "docs":
        shutil.rmtree(root / "docs")
        (work / update_apply.OLD_DIR_NAME / "docs").mkdir(parents=True)
        (work / update_apply.OLD_DIR_NAME / "docs" / "ghid.md").write_text("copia de siguranță a programului\n", encoding="utf-8")
        link = root / "docs"
    else:
        link = work / linked
        link.parent.mkdir(parents=True)
        if journal.get("sterse"):
            (root / "docs" / "ghid.md").unlink()  # „mutat în vechi/” înainte de întrerupere
        if journal.get("scrise") == ["docs/pagina_noua.md"]:
            (root / "docs" / "pagina_noua.md").write_text("fișier nou, deja mutat în program\n", encoding="utf-8")
    _journal(work, **journal)
    make_link(outside, link)
    outside_before, root_before = fingerprint(outside, skip=()), fingerprint(root)
    try:
        outcome = update_recovery.recover_before_start(root)
        assert outcome.message is None and outcome.error and "nu s-a terminat" in outcome.error, outcome
        assert fingerprint(outside, skip=()) == outside_before, "revenirea a scris, a mutat sau a șters prin legătură"
        assert fingerprint(root) == root_before, "revenirea a schimbat programul deși nu s-a putut termina"
        assert (work / update_apply.JOURNAL_NAME).is_file(), "jurnalul rămâne pentru pornirea de după ștergerea legăturii"
        assert any("legătură" in record.getMessage() for record in outcome.records), [r.getMessage() for r in outcome.records]
    finally:
        remove_link(link)


# ---------- (9) descărcările lăsate de un proces omorât și descarcari/ ca legătură (P7, P8) ----------

def test_the_cleanup_under_the_lock_removes_old_downloads_but_not_a_live_one(tmp_path):
    """P7: curățenia de sub lacăt (aici după un jurnal „gata”) șterge folderele descarcare-* neatinse de o oră; una proaspătă (altă
    fereastră descarcă acum) și ce nu e al programului rămân; fără cea vie, în .actualizare rămâne doar lacătul."""
    root = tmp_path / "program"
    install_program(root, NEW)
    work = root / update_apply.WORK_DIR_NAME
    downloads = work / update_recovery.DOWNLOADS_DIR_NAME
    old, live, foreign = (downloads / name for name in ("descarcare-oprita", "descarcare-vie", "al_utilizatorului"))
    for folder in (old, live, foreign):
        folder.mkdir(parents=True)
        (folder / "cheltuieli-emag-v9.9.9.zip.part").write_bytes(b"jumatate de arhiva inventata")
    age_tree(old, update_recovery.STALE_DOWNLOAD_SECONDS + 60)
    age_tree(foreign, update_recovery.STALE_DOWNLOAD_SECONDS + 60)
    _journal(work, stare="gata")
    assert update_recovery.recover_before_start(root).error is None
    assert not old.exists(), "descărcarea lăsată de un proces omorât a rămas"
    assert live.is_dir() and foreign.is_dir(), "curățenia a atins o descărcare vie sau ceva ce nu e al ei"
    shutil.rmtree(live)
    shutil.rmtree(foreign)
    (downloads / "descarcare-alta").mkdir()
    age_tree(downloads / "descarcare-alta", update_recovery.STALE_DOWNLOAD_SECONDS + 60)
    _journal(work, stare="gata")
    assert update_recovery.recover_before_start(root).error is None
    assert work_dir_leftovers(root) == [], f"în .actualizare au rămas {work_dir_leftovers(root)}"


def test_removing_old_downloads_never_goes_through_a_downloads_folder_that_is_a_link(tmp_path):
    """P7, N4: chemată direct pe un descarcari/ care e legătură, ștergerea descărcărilor vechi nu intră în ea și nu scoate legătura."""
    outside = tmp_path / "in_afara"
    (outside / "descarcare-veche").mkdir(parents=True)
    (outside / "descarcare-veche" / "arhiva.zip").write_bytes(b"a utilizatorului")
    age_tree(outside, update_recovery.STALE_DOWNLOAD_SECONDS + 60)
    before = fingerprint(outside, skip=())
    link = tmp_path / update_recovery.DOWNLOADS_DIR_NAME
    make_link(outside, link)
    try:
        update_recovery.remove_stale_downloads(link)
        assert os.path.lexists(link) and fingerprint(outside, skip=()) == before, "ștergerea a intrat în legătură"
    finally:
        remove_link(link)


def test_recovery_refuses_a_downloads_folder_that_is_a_link(tmp_path):
    """P8: .actualizare/descarcari legătură spre alt loc → eroare înainte de orice; o descărcare „veche” de acolo rămâne neatinsă."""
    root = tmp_path / "program"
    install_program(root, VERSION)
    outside = tmp_path / "in_afara"
    (outside / "descarcare-veche").mkdir(parents=True)
    (outside / "descarcare-veche" / "arhiva.zip").write_bytes(b"a utilizatorului")
    age_tree(outside, update_recovery.STALE_DOWNLOAD_SECONDS + 60)
    outside_before = fingerprint(outside, skip=())
    work = root / update_apply.WORK_DIR_NAME
    _journal(work, stare="gata")
    make_link(outside, work / update_recovery.DOWNLOADS_DIR_NAME)
    try:
        outcome = update_recovery.recover_before_start(root)
        assert outcome.error and "legătură" in outcome.error and ".actualizare/descarcari" in outcome.error, outcome
        assert fingerprint(outside, skip=()) == outside_before, "curățenia a șters prin legătură"
    finally:
        remove_link(work / update_recovery.DOWNLOADS_DIR_NAME)

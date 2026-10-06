"""Teste pentru lansare (decis 5 oct. 2026, D1, D8, D16, D17, D20): CHANGELOG, eticheta față de VERSION, corpul lansării,
manifestul și arhiva, plus forma workflow-urilor lansare.yml și actualizare.yml.

Primește: CHANGELOG.md, scripturile din .github/scripts (rulate ca în lansare.yml) și exemple inventate. Arhiva se face
local, cu `git archive --add-file`, dintr-un depozit git temporar construit din arborele curent al proiectului (fișierele
care ar urca în git, cu modurile din index), și se verifică cu zipfile: manifestul == intrările, .bat cu CRLF, .sh și
.command cu 0o755, plus regulile actualizării (update_archive.validate_archive).
Nu scrie nimic în proiect (doar în folderul temporar al testului) și nu iese pe internet.
"""

import importlib
import os
import re
import shutil
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest

from emag_spend import update_archive, update_check
from emag_spend.version import VERSION
from tests.garda_support import PROJECT_ROOT, files_to_publish

SCRIPTS = PROJECT_ROOT / ".github" / "scripts"
WORKFLOWS = PROJECT_ROOT / ".github" / "workflows"
CHANGELOG = PROJECT_ROOT / "CHANGELOG.md"
GIT_TIMEOUT_SECONDS = 120
# `git archive --add-file` a apărut în git 2.35; fără el arhiva nu poate primi manifestul.
MIN_GIT_FOR_ADD_FILE = (2, 35)
EXECUTABLE_MODE = 0o755
PERMISSION_BITS = 0o777
# Exact comanda din D16: --prefix de dinainte de --add-file pune manifestul în instalare/, cel de după pune restul arhivei.
ARCHIVE_COMMAND = ('git archive --format=zip --prefix="$NUME/instalare/" --add-file="$RUNNER_TEMP/fisiere.txt" '
                   '--prefix="$NUME/" -o "$NUME.zip" HEAD')
FULL_SHA = re.compile(r"uses:\s*[\w.-]+/[\w./-]+@[0-9a-f]{40}\s*#")
SCRIPT_ENV = {**os.environ, "PYTHONUTF8": "1", "PYTHONDONTWRITEBYTECODE": "1"}


def _load(name: str):
    """Scriptul .github/scripts/<name>.py ca modul; folderul lui intră în sys.path, ca la rularea din lansare.yml."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    return importlib.import_module(name)


def _run_script(name: str, *args: str, cwd: Path = PROJECT_ROOT) -> subprocess.CompletedProcess:
    """Rulează `python .github/scripts/<name>.py args`, ca în lansare.yml; text UTF-8."""
    return subprocess.run([sys.executable, str(SCRIPTS / f"{name}.py"), *args], cwd=cwd, env=SCRIPT_ENV, capture_output=True,
                          text=True, encoding="utf-8", timeout=GIT_TIMEOUT_SECONDS)


# ---------- CHANGELOG ----------

def test_changelog_has_a_dated_section_for_the_current_version():
    """CHANGELOG.md are secțiunea `## VERSION — AAAA-LL-ZZ` pentru versiunea din version.py, negoală (fără ea lansare.yml pică)."""
    section = _load("changelog_section").changelog_section(CHANGELOG.read_text(encoding="utf-8"), VERSION)
    assert len(section.splitlines()) >= 2, section


def test_changelog_versions_are_unique_and_newest_first():
    """Titlurile de versiune din CHANGELOG sunt unice și în ordine descrescătoare (cea mai nouă sus), cu date care nu scad."""
    found = _load("changelog_section").headings(CHANGELOG.read_text(encoding="utf-8"))
    versions = [tuple(int(part) for part in version.split(".")) for _line, version, _date in found]
    dates = [date for _line, _version, date in found]
    assert versions and len(set(versions)) == len(versions), f"versiuni repetate: {versions}"
    assert versions == sorted(versions, reverse=True) and dates == sorted(dates, reverse=True), f"ordinea trebuie să fie de la cea mai nouă: {found}"


def test_changelog_section_is_plain_text_that_fits_in_the_application():
    """Secțiunea curentă se vede în aplicație ca text simplu (textContent): fără formatare Markdown și sub limita din update_check."""
    section = _load("changelog_section").changelog_section(CHANGELOG.read_text(encoding="utf-8"), VERSION)
    assert len(section) <= update_check.MAX_NOTES_CHARS, f"{len(section)} caractere > {update_check.MAX_NOTES_CHARS}: aplicația l-ar tăia"
    assert not re.search(r"\*\*|`|^#|\]\(", section, re.M), "fără **, `, # sau linkuri Markdown: în aplicație s-ar vedea ca atare"


CHANGELOG_EXAMPLE = """# Istoric

## 2.1.0 — 2031-04-02

- Ceva inventat, nou.

### Detaliu (titlu de nivel 3, rămâne în secțiune)

- Încă un rând.

## 2.0.0 — 2031-01-15

- Versiunea veche.
"""


def test_changelog_section_takes_exactly_one_section():
    """Pe un exemplu inventat: secțiunea ține până la următorul `## `, fără titlu și fără rânduri goale la margini; merge și cu CRLF."""
    module = _load("changelog_section")
    expected = "- Ceva inventat, nou.\n\n### Detaliu (titlu de nivel 3, rămâne în secțiune)\n\n- Încă un rând."
    assert module.changelog_section(CHANGELOG_EXAMPLE, "2.1.0") == expected
    assert module.changelog_section(CHANGELOG_EXAMPLE.replace("\n", "\r\n"), "2.1.0") == expected
    assert module.changelog_section(CHANGELOG_EXAMPLE, "2.0.0") == "- Versiunea veche."


@pytest.mark.parametrize("text, version, expected", [
    (CHANGELOG_EXAMPLE, "2.2.0", "nu are secțiunea"),
    (CHANGELOG_EXAMPLE + "\n## 2.1.0 — 2031-04-03\n\n- dublură\n", "2.1.0", "de 2 ori"),
    ("## 2.1.0 - 2031-04-02\n\n- cu cratimă în loc de linie lungă\n", "2.1.0", "exact «## X.Y.Z — AAAA-LL-ZZ»"),
    ("## 2.1.0 — 2031-02-30\n\n- zi care nu există\n", "2.1.0", "nu e o zi reală"),
    ("## 2.1.0 — 2031-04-02\n\n\n## 2.0.0 — 2031-01-15\n\n- veche\n", "2.1.0", "e goală"),
])
def test_changelog_section_refuses_missing_duplicated_misspelled_or_empty_sections(text, version, expected):
    """Capcane: versiune lipsă, secțiune dublă, cratimă în loc de linie lungă, dată imposibilă, secțiune goală → ChangelogError."""
    module = _load("changelog_section")
    with pytest.raises(module.ChangelogError, match=re.escape(expected)):
        module.changelog_section(text, version)


def test_changelog_section_command_line_on_the_real_changelog():
    """Ca în lansare.yml: `changelog_section.py VERSION` scrie secțiunea și iese cu 0; o versiune fără secțiune iese cu 1."""
    good = _run_script("changelog_section", VERSION)
    assert good.returncode == 0 and good.stdout.strip() == _load("changelog_section").changelog_section(
        CHANGELOG.read_text(encoding="utf-8"), VERSION), good.stderr
    missing = _run_script("changelog_section", "999.0.0")
    assert missing.returncode == 1 and "nu are secțiunea" in missing.stderr, missing.stderr


# ---------- eticheta față de VERSION (D1) ----------

def test_release_tag_must_be_v_plus_version():
    """check_tag acceptă doar „v” + VERSION, cu VERSION de forma X.Y.Z (aceeași regulă ca version.parse_version)."""
    module = _load("release_version")
    assert module.check_tag("v4.5.6", "4.5.6") == "4.5.6"
    for tag, version in (("v4.5.7", "4.5.6"), ("4.5.6", "4.5.6"), ("v4.5.6-rc1", "4.5.6"), ("vv4.5.6", "v4.5.6"), ("v4.5", "4.5"), ("v04.5.6", "04.5.6")):
        with pytest.raises(module.ReleaseVersionError):
            module.check_tag(tag, version)


def test_release_version_command_line_on_the_real_version():
    """Ca în lansare.yml: cu eticheta v+VERSION scrie VERSION și iese cu 0; cu altă etichetă iese cu 1 și spune ce trebuie."""
    good = _run_script("release_version", f"v{VERSION}")
    assert good.returncode == 0 and good.stdout.strip() == VERSION, good.stderr
    bad = _run_script("release_version", "v999.0.0")
    assert bad.returncode == 1 and f"v{VERSION}" in bad.stderr, bad.stderr


# ---------- corpul lansării (D16, D20) ----------

def test_release_body_starts_with_whats_new_and_the_application_reads_exactly_the_changelog_section():
    """Corpul începe cu `## Ce e nou în vX`, apoi „Cum îl folosești”, apoi amprenta; update_check.release_notes scoate exact secțiunea."""
    body_module = _load("release_body")
    section = _load("changelog_section").changelog_section(CHANGELOG.read_text(encoding="utf-8"), VERSION)
    checksums = f"{'ab' * 32}  cheltuieli-emag-v{VERSION}.zip\n"
    body = body_module.release_body(VERSION, section, "proprietar-inventat/depozit", checksums)
    titles = [line for line in body.splitlines() if line.startswith("## ")]
    assert titles == [f"## Ce e nou în v{VERSION}", "## Cum îl folosești", "## Amprenta arhivei (SHA-256)"], titles
    assert body.splitlines()[0] == titles[0], "primul rând trebuie să fie titlul „Ce e nou”"
    assert update_check.release_notes(body) == section, "aplicația ar arăta alt text decât secțiunea din CHANGELOG"
    assert f"```\n{checksums}```" in body and "https://github.com/proprietar-inventat/depozit/blob/v" in body


def test_release_body_command_line_writes_the_same_body(tmp_path):
    """Ca în lansare.yml: `release_body.py --versiune ... --depozit ... --amprente SHA256SUMS.txt` dă același text ca funcția."""
    sums = tmp_path / "SHA256SUMS.txt"
    sums.write_bytes(f"{'cd' * 32}  cheltuieli-emag-v{VERSION}.zip\n".encode("ascii"))
    result = _run_script("release_body", "--versiune", VERSION, "--depozit", "proprietar-inventat/depozit", "--amprente", str(sums))
    section = _load("changelog_section").changelog_section(CHANGELOG.read_text(encoding="utf-8"), VERSION)
    expected = _load("release_body").release_body(VERSION, section, "proprietar-inventat/depozit", sums.read_text(encoding="utf-8"))
    assert result.returncode == 0 and result.stdout == expected, result.stderr


def test_release_names_match_what_the_updater_expects():
    """Numele arhivei, prefixul ei și calea manifestului sunt aceleași în scripturile lansării și în codul actualizării."""
    tag = f"v{VERSION}"
    assert _load("release_body").ARCHIVE_NAME.format(version=VERSION) + ".zip" == update_check.ZIP_NAME_TEMPLATE.format(tag=tag)
    assert _load("release_body").ARCHIVE_NAME.format(version=VERSION) + "/" == update_archive.ARCHIVE_PREFIX_TEMPLATE.format(version=VERSION)
    assert _load("release_manifest").MANIFEST_PATH == update_archive.MANIFEST_PATH


# ---------- manifestul (D8) ----------

def test_manifest_lists_the_tree_plus_itself_sorted_with_lf():
    """Pe intrări inventate: căile + manifestul, sortate, unice, câte una pe rând, LF, UTF-8."""
    module = _load("release_manifest")
    manifest = module.build_manifest([("100644", "z.txt"), ("100755", "porneste.sh"), ("100644", "docs/ă.md"), ("100644", "a/b.py")])
    assert manifest == "a/b.py\ndocs/ă.md\ninstalare/fisiere.txt\nporneste.sh\nz.txt\n".encode("utf-8")


@pytest.mark.parametrize("entries, expected", [
    ([("100644", "instalare/fisiere.txt")], "e urmărit de git"),
    ([("120000", "legatura")], "nu sunt fișiere obișnuite"),
    ([("160000", "submodul")], "nu sunt fișiere obișnuite"),
    ([("100644", "rand\nnou.txt")], "sfârșit de rând"),
])
def test_manifest_refuses_a_tracked_manifest_links_submodules_and_newlines(entries, expected):
    """Capcane: manifest urmărit de git (dublură în arhivă), legături, submodule, căi cu sfârșit de rând → ManifestError."""
    module = _load("release_manifest")
    with pytest.raises(module.ManifestError, match=re.escape(expected)):
        module.build_manifest(entries)


def test_manifest_is_ignored_by_git():
    """instalare/fisiere.txt e în .gitignore (D8): făcut doar la lansare, niciodată urmărit (altfel ar apărea de două ori în arhivă)."""
    assert re.search(r"(?m)^/?instalare/fisiere\.txt\s*$", (PROJECT_ROOT / ".gitignore").read_text(encoding="utf-8"))


# ---------- arhiva făcută local, ca în lansare.yml ----------

def _git(*args: str, cwd: Path) -> subprocess.CompletedProcess:
    """Rulează git în `cwd`, fără configurația globală de sfârșituri de rând a utilizatorului; ridică eroare dacă git pică."""
    return subprocess.run(["git", "-c", "core.autocrlf=false", "-c", "core.safecrlf=false", *args], cwd=cwd, capture_output=True,
                          check=True, timeout=GIT_TIMEOUT_SECONDS)


def _git_version() -> tuple[int, ...]:
    """Versiunea git instalată, ca tuplu (2, 54, 0); (0,) dacă git lipsește."""
    if shutil.which("git") is None:
        return (0,)
    found = re.search(r"(\d+)\.(\d+)", subprocess.run(["git", "--version"], capture_output=True, text=True).stdout)
    return tuple(int(part) for part in found.groups()) if found else (0,)


def _executables_in_index() -> list[str]:
    """Căile cu modul 100755 în indexul git al proiectului (lansatoarele de macOS și Linux)."""
    listed = _git("ls-files", "-s", "-z", cwd=PROJECT_ROOT).stdout.decode("utf-8")
    return [record.split("\t", 1)[1] for record in filter(None, listed.split("\0")) if record.startswith("100755 ")]


@pytest.fixture(scope="module")
def local_release(tmp_path_factory):
    """Lansarea făcută local: (arhiva, manifestul) din arborele curent, cu exact pașii din lansare.yml.

    Depozitul temporar primește fișierele care ar urca în git (urmărite + noi neignorate), cu modurile executabile din index;
    `git write-tree` dă arborele, apoi release_manifest.py și `git archive --add-file` ca în lansare.yml.
    """
    if _git_version() < MIN_GIT_FOR_ADD_FILE or not (PROJECT_ROOT / ".git").exists():
        pytest.skip(f"trebuie git >= {'.'.join(map(str, MIN_GIT_FOR_ADD_FILE))} și proiectul ca depozit git")
    work = tmp_path_factory.mktemp("lansare")
    repo = work / "depozit"
    for path in files_to_publish():
        if path.is_file():
            target = repo / path.relative_to(PROJECT_ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    _git("init", "-q", cwd=repo)
    _git("add", "-A", cwd=repo)
    executables = _executables_in_index()
    if executables:
        _git("update-index", "--chmod=+x", "--", *executables, cwd=repo)
    tree = _git("write-tree", cwd=repo).stdout.decode("ascii").strip()
    manifest = work / "fisiere.txt"
    made = _run_script("release_manifest", "--ref", tree, "--radacina", str(repo), str(manifest))
    assert made.returncode == 0, made.stderr
    name = f"cheltuieli-emag-v{VERSION}"
    archive = work / f"{name}.zip"
    _git("archive", "--format=zip", f"--prefix={name}/instalare/", f"--add-file={manifest}", f"--prefix={name}/", "-o", str(archive), tree, cwd=repo)
    return archive, manifest.read_bytes()


def test_local_archive_entries_are_exactly_the_manifest(local_release):
    """Manifestul din arhivă (instalare/fisiere.txt) e octet cu octet cel făcut și listează exact fișierele din arhivă."""
    archive, manifest = local_release
    prefix = f"cheltuieli-emag-v{VERSION}/"
    with zipfile.ZipFile(archive) as opened:
        names = [info.filename for info in opened.infolist() if not info.is_dir()]
        assert all(name.startswith(prefix) for name in names), [name for name in names if not name.startswith(prefix)][:5]
        assert opened.read(prefix + "instalare/fisiere.txt") == manifest
    lines = manifest.decode("utf-8").split("\n")
    assert b"\r" not in manifest and lines[-1] == "" and lines[:-1] == sorted(set(lines[:-1])), "manifestul: LF, sortat, fără dubluri"
    assert sorted(name[len(prefix):] for name in names) == lines[:-1], "intrările arhivei diferă de manifest"
    assert "instalare/fisiere.txt" in lines and "porneste.bat" in lines


def test_local_archive_launchers_keep_crlf_and_the_execute_bit(local_release):
    """În arhivă: fiecare .bat are CRLF peste tot; porneste.sh, porneste.command și instalare/pregatire.sh au 0o755 și doar LF."""
    archive, _manifest = local_release
    prefix = f"cheltuieli-emag-v{VERSION}/"
    with zipfile.ZipFile(archive) as opened:
        bats = [info for info in opened.infolist() if info.filename.endswith(".bat")]
        assert bats, "nu e niciun .bat în arhivă"
        for info in bats:
            data = opened.read(info)
            assert data.endswith(b"\r\n") and data.count(b"\n") == data.count(b"\r\n"), f"{info.filename} nu are CRLF peste tot"
        for name in ("porneste.sh", "porneste.command", "instalare/pregatire.sh"):
            info = opened.getinfo(prefix + name)
            assert (info.external_attr >> 16) & PERMISSION_BITS == EXECUTABLE_MODE, f"{name}: {oct((info.external_attr >> 16) & PERMISSION_BITS)}"
            assert b"\r" not in opened.read(info), f"{name} are CR"


def test_local_archive_passes_the_updater_rules_and_the_release_check(local_release):
    """Arhiva trece de release_archive_check.py (ca în lansare.yml): regulile actualizării (validate_archive) și ale lansatoarelor."""
    archive, _manifest = local_release
    result = _run_script("release_archive_check", str(archive), VERSION)
    assert result.returncode == 0, result.stderr


def test_release_check_refuses_an_archive_whose_manifest_is_in_the_wrong_place(local_release, tmp_path):
    """Capcană: aceeași arhivă cu manifestul la rădăcină (--prefix în ordinea greșită) e refuzată înainte de publicare."""
    archive, _manifest = local_release
    prefix = f"cheltuieli-emag-v{VERSION}/"
    wrong = tmp_path / archive.name
    with zipfile.ZipFile(archive) as source, zipfile.ZipFile(wrong, "w", zipfile.ZIP_DEFLATED) as target:
        for info in source.infolist():
            data = source.read(info)
            if info.filename == prefix + "instalare/fisiere.txt":
                info.filename = prefix + "fisiere.txt"
            target.writestr(info, data)
    result = _run_script("release_archive_check", str(wrong), VERSION)
    assert result.returncode == 1 and "actualizarea ar refuza arhiva" in result.stderr, result.stderr


def test_release_check_refuses_launchers_without_crlf_or_execute_bit(tmp_path):
    """Capcană pentru verificarea lansatoarelor: un .bat cu LF și un .sh fără bit de execuție sunt prinse."""
    module = _load("release_archive_check")
    path = tmp_path / "capcana.zip"
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("x/porneste.bat", b"@echo off\necho x\n")
        script = zipfile.ZipInfo("x/porneste.sh")
        script.external_attr = 0o644 << 16
        archive.writestr(script, b"#!/bin/sh\n")
    with zipfile.ZipFile(path) as archive:
        problems = "\n".join(module.launcher_problems(archive))
    assert "porneste.bat: nu are CRLF" in problems and "porneste.sh: are modul 0o644" in problems, problems
    assert "lipsește porneste.command" in problems, problems


def test_release_check_knows_the_same_executable_scripts_as_the_launcher_tests():
    """Scripturile care trebuie să fie executabile în arhivă sunt aceleași cu cele verificate în git (tests/test_lansatoare_unix.py)."""
    from tests.test_lansatoare_unix import EXECUTABLES
    assert set(_load("release_archive_check").EXECUTED_SCRIPTS) == set(EXECUTABLES)


# ---------- workflow-urile ----------

WORKFLOW_FILES = sorted(path.name for path in WORKFLOWS.glob("*.yml"))
# Singurele drepturi de scriere din workflow-uri (fișier, job, drept), fiecare cu motivul lui: lansarea se creează (D16) și se
# retrage dacă testul actualizării nu reușește (N13); CodeQL își încarcă rezultatele în fila Security.
ALLOWED_WRITE_PERMISSIONS = frozenset({
    ("lansare.yml", "lansare", "contents"),
    ("lansare.yml", "retrage", "contents"),
    ("codeql.yml", "analiza", "security-events"),
})
# N13 (decis 6 oct. 2026): jobul din lansare.yml → workflow-ul pe care îl cheamă înainte de publicare.
RELEASE_GATES = {"teste": "teste.yml", "pornire": "pornire.yml"}
# N14 (decis 6 oct. 2026): uneltele bash ale testului actualizării și cum le încarcă fiecare pas (din checkout-ul în depozit/).
CI_TOOLS = SCRIPTS / "actualizare_ci.sh"
CI_TOOLS_IN_WORKFLOW = ". ./depozit/.github/scripts/actualizare_ci.sh"
CI_RUN_TIMEOUT_SECONDS = 60
# Cât de sus căutăm `bin/bash.exe` pornind de la git.exe (Git\cmd\git.exe sau Git\mingw64\bin\git.exe).
GIT_FOLDER_DEPTH = 3


def _workflow(name: str) -> str:
    """Textul workflow-ului .github/workflows/<name>."""
    return (WORKFLOWS / name).read_text(encoding="utf-8")


def _without_comments(text: str) -> str:
    """Textul fără rândurile de comentariu (# la început de rând, după spații)."""
    return re.sub(r"(?m)^\s*#.*$", "", text)


def _top_level(text: str) -> str:
    """Partea workflow-ului de dinaintea lui `jobs:` (declanșatori, drepturi, concurență), fără comentarii."""
    return _without_comments(text).split("\njobs:\n", 1)[0] + "\n"


def _jobs(text: str) -> dict[str, str]:
    """Blocurile joburilor, după nume: rândurile de sub `jobs:` care încep cu exact două spații deschid un job nou."""
    parts = re.split(r"(?m)^  ([A-Za-z0-9_-]+):[ \t]*$", _without_comments(text).split("\njobs:\n", 1)[1])
    return {parts[index]: parts[index + 1] for index in range(1, len(parts), 2)}


def _needs(job: str) -> list[str]:
    """Joburile din `needs:` al unui job (un nume sau o listă [a, b]); listă goală dacă nu are."""
    found = re.search(r"(?m)^    needs:[ \t]*(.+)$", job)
    return [name.strip() for name in found.group(1).strip().strip("[]").split(",")] if found else []


def test_release_workflow_checks_first_then_builds_verifies_publishes_and_tests_the_update():
    """lansare.yml: în jobul care publică, eticheta și CHANGELOG-ul înainte de arhivă; arhiva cu manifestul (comanda din D16),
    verificată înainte de publicare; apoi testul actualizării, chemat ca workflow reutilizabil, doar cu drept de citire."""
    jobs = _jobs(_workflow("lansare.yml"))
    publish = jobs["lansare"]
    order = ["release_version.py", "changelog_section.py", "release_manifest.py", ARCHIVE_COMMAND, "release_archive_check.py",
             "release_body.py", "gh release create"]
    positions = [publish.find(item) for item in order]
    assert -1 not in positions, f"lipsește din jobul «lansare»: {[item for item, at in zip(order, positions) if at == -1]}"
    assert positions == sorted(positions), f"ordinea pașilor din lansare.yml e greșită: {order}"
    update = jobs["actualizare"]
    assert _needs(update) == ["lansare"] and "uses: ./.github/workflows/actualizare.yml" in update and "eticheta: ${{ github.ref_name }}" in update
    assert re.search(r"permissions:\s*\n\s*contents: read", update), "jobul actualizării are doar drept de citire"


@pytest.mark.parametrize("name", sorted(RELEASE_GATES.values()))
def test_the_release_gates_can_be_called_by_the_release_workflow(name):
    """teste.yml și pornire.yml (N13) rulează la push și la pull request, dar se pot chema și din lansare.yml (workflow_call)."""
    top = _top_level(_workflow(name))
    for trigger in ("push:", "pull_request:", "workflow_call:"):
        assert re.search(rf"(?m)^  {trigger}", top), f"{name}: lipsește declanșatorul {trigger}"


def test_release_is_published_only_after_the_tests_and_the_fresh_start_pass():
    """lansare.yml (N13): jobul care publică așteaptă testele și pornirea de la zero, chemate pe commit-ul etichetei cu drept de
    citire; e singurul job care publică."""
    jobs = _jobs(_workflow("lansare.yml"))
    for job, workflow in RELEASE_GATES.items():
        assert f"uses: ./.github/workflows/{workflow}" in jobs.get(job, ""), f"lansare.yml trebuie să cheme {workflow} în jobul «{job}»"
        assert re.search(r"permissions:\s*\n\s*contents: read", jobs[job]), f"jobul «{job}» are doar drept de citire"
    assert set(_needs(jobs["lansare"])) == set(RELEASE_GATES), f"jobul «lansare» trebuie să aștepte {sorted(RELEASE_GATES)}: {_needs(jobs['lansare'])}"
    publishing = [name for name, job in jobs.items() if "gh release create" in job]
    assert publishing == ["lansare"], f"doar jobul «lansare» publică, găsit {publishing}"


def test_a_release_whose_update_test_fails_is_withdrawn_from_latest():
    """lansare.yml (N13): dacă testul actualizării nu reușește după publicare, jobul «retrage» marchează lansarea ca prerelease,
    ca releases/latest (de unde aplicația află de versiunile noi) să n-o mai ofere; rulează doar dacă lansarea s-a publicat."""
    job = _jobs(_workflow("lansare.yml")).get("retrage", "")
    assert set(_needs(job)) == {"lansare", "actualizare"}, f"«retrage» trebuie să aștepte publicarea și testul: {_needs(job)}"
    condition = re.search(r"(?m)^    if:[ \t]*(.+)$", job)
    assert condition, "«retrage» trebuie să aibă o condiție"
    for part in ("always()", "needs.lansare.result == 'success'", "needs.actualizare.result != 'success'"):
        assert part in condition.group(1), f"condiția lui «retrage» trebuie să conțină {part}: {condition.group(1)}"
    assert 'gh release edit "$ETICHETA" --repo "$GITHUB_REPOSITORY" --prerelease' in job
    assert "releases/latest" in job, "după retragere se verifică că releases/latest nu mai e lansarea retrasă"


@pytest.mark.parametrize("name", WORKFLOW_FILES)
def test_workflows_are_read_only_except_the_jobs_that_must_write(name):
    """Fiecare workflow pornește cu contents: read; drepturile de scriere apar doar în joburile din ALLOWED_WRITE_PERMISSIONS,
    iar fiecare excepție de acolo încă e folosită (o excepție rămasă fără job ar ascunde o greșeală de nume)."""
    text = _workflow(name)
    top = _top_level(text)
    assert re.search(r"(?m)^permissions:\n  contents: read\n", top) and "write" not in top, f"{name}: la nivelul workflow-ului, doar contents: read"
    found = {(name, job, permission) for job, block in _jobs(text).items()
             for permission in re.findall(r"(?m)^\s+([a-z-]+):[ \t]*write[ \t]*$", block)}
    assert found <= ALLOWED_WRITE_PERMISSIONS, f"{name}: drepturi de scriere fără motiv scris: {sorted(found - ALLOWED_WRITE_PERMISSIONS)}"
    assert found == {entry for entry in ALLOWED_WRITE_PERMISSIONS if entry[0] == name}, f"{name}: excepții nefolosite în ALLOWED_WRITE_PERMISSIONS"


def test_reusable_workflows_have_their_own_concurrency_group():
    """Un workflow chemat (workflow_call) vede github.workflow al celui care îl cheamă: dacă grupul de concurență l-ar folosi,
    teste.yml și pornire.yml chemate din lansare.yml ar cădea în același grup și unul l-ar anula pe celălalt (N13)."""
    groups = {}
    for name in WORKFLOW_FILES:
        top = _top_level(_workflow(name))
        group = re.search(r"(?m)^  group:[ \t]*(.+)$", top)
        if re.search(r"(?m)^  workflow_call:", top) and group:
            assert "github.workflow" not in group.group(1), f"{name}: grupul de concurență folosește github.workflow"
            groups[name] = group.group(1).strip()
    assert len(set(groups.values())) == len(groups), f"workflow-urile chemate au același grup de concurență: {groups}"


@pytest.mark.parametrize("name", WORKFLOW_FILES)
def test_workflow_actions_are_pinned_to_a_full_commit(name):
    """Orice acțiune externă e fixată pe SHA-ul complet al commit-ului (cu versiunea în comentariu), nu pe o etichetă mutabilă."""
    for line in _workflow(name).splitlines():
        if re.match(r"\s*(-\s*)?uses:", line) and "./.github/workflows/" not in line:
            assert FULL_SHA.search(line), f"{name}: «{line.strip()}» nu e fixată pe un SHA de 40 de caractere"


def test_each_action_is_pinned_to_the_same_commit_in_every_workflow():
    """O acțiune folosită în mai multe workflow-uri e fixată peste tot pe același commit (dependabot le mută împreună)."""
    pins: dict[str, set[str]] = {}
    for name in WORKFLOW_FILES:
        for action, commit in re.findall(r"uses:\s*([\w.-]+/[\w./-]+)@([0-9a-f]{40})", _workflow(name)):
            pins.setdefault(action, set()).add(commit)
    assert pins and all(len(commits) == 1 for commits in pins.values()), {action: sorted(commits) for action, commits in pins.items() if len(commits) > 1}


def test_update_workflow_is_reusable_scheduled_read_only_and_runs_on_three_systems():
    """actualizare.yml (D17): workflow_call + workflow_dispatch + săptămânal, doar contents: read, Windows/macOS/Linux, fără secrete."""
    text = _workflow("actualizare.yml")
    for trigger in ("workflow_call:", "workflow_dispatch:", "schedule:"):
        assert re.search(rf"(?m)^  {trigger}", text), f"lipsește declanșatorul {trigger}"
    assert re.search(r"(?m)^permissions:\n  contents: read\n", text), "drepturi doar de citire, la nivelul workflow-ului"
    assert "write" not in _without_comments(text), "actualizare.yml nu are voie să ceară drepturi de scriere"
    assert "os: [windows-latest, macos-latest, ubuntu-latest]" in text
    assert "secrets." not in text, "testul actualizării nu folosește secrete (doar tokenul implicit, de citire)"


def test_update_workflow_also_updates_from_the_previous_published_release():
    """actualizare.yml (N14): caută lansarea publicată dinaintea celei testate (fără ciorne și prerelease) și, dacă există, îi
    face copii NEîmbătrânite care trec prin ambele căi (terminal și aplicație) până la ultima; altfel doar copiile îmbătrânite."""
    text = _without_comments(_workflow("actualizare.yml"))
    assert CI_TOOLS_IN_WORKFLOW in text and "path: depozit" in text, "pașii folosesc uneltele din .github/scripts/actualizare_ci.sh"
    assert re.search(r"gh_reincercat release list [^\n]*--exclude-drafts --exclude-pre-releases[^\n]*\| versiunea_anterioara \"\$VERSIUNE\"", text)
    assert 'COPII_A=copie-a anterioara-a' in text and 'COPII_B=copie-b anterioara-b' in text, "cu o lansare anterioară: câte o copie neîmbătrânită pe fiecare cale"
    assert 'COPII_A=copie-a"' in text and 'COPII_B=copie-b"' in text, "fără lansare anterioară: doar copiile îmbătrânite"
    assert 'for COPIE in $COPII_A; do actualizeaza_din_terminal "$COPIE"; done' in text
    assert 'for COPIE in $COPII_B; do actualizeaza_din_aplicatie "$COPIE"; done' in text


def test_every_gh_call_of_the_update_test_is_retried():
    """N14: în actualizare.yml și în uneltele lui, fiecare apel gh trece prin gh_reincercat (API-ul GitHub poate refuza o clipă)."""
    for name, text in (("actualizare.yml", _workflow("actualizare.yml")), (CI_TOOLS.name, CI_TOOLS.read_text(encoding="utf-8"))):
        for number, line in enumerate(_without_comments(text).splitlines(), start=1):
            assert not re.search(r"(?<![\w-])gh\s+[a-z]", line), f"{name}:{number}: «{line.strip()}» cheamă gh fără gh_reincercat"


def test_shellcheck_in_ci_also_checks_the_update_test_tools():
    """pornire.yml rulează shellcheck (pe Linux) și pe uneltele bash ale testului actualizării, ca bash."""
    assert "shellcheck --shell=bash .github/scripts/actualizare_ci.sh" in _workflow("pornire.yml")


# ---------- uneltele testului actualizării (N14), rulate local cu bash și cu un gh fals ----------

def _bash() -> str | None:
    """bash: din PATH pe macOS/Linux; pe Windows, `bin/bash.exe` din Git for Windows (lângă git.exe). None dacă lipsește."""
    if sys.platform != "win32":
        return shutil.which("bash")
    git = shutil.which("git")
    if not git:
        return None
    for folder in Path(git).resolve().parents[:GIT_FOLDER_DEPTH]:
        if (folder / "bin" / "bash.exe").is_file():
            return str(folder / "bin" / "bash.exe")
    return None


BASH = _bash()
needs_bash = pytest.mark.skipif(BASH is None, reason="nu există bash aici (pe Windows: Git for Windows)")
CI_VERSION = "9.9.9"  # versiunea inventată a „ultimei lansări” din testele uneltelor
NO_UNZIP_EXIT_CODE = 77  # codul cu care iese testul căii (a) când bash nu are unzip (convenția „sărit” din automake)
# gh fals: notează apelul în gh-apeluri.txt; pică la primele GH_ESECURI apeluri; apoi scrie gh-iesire-<N>.txt (dacă există) sau gh-iesire.txt.
FAKE_GH = """#!/bin/sh
AICI=$(cd "$(dirname "$0")" && pwd)
echo "$*" >> "$AICI/gh-apeluri.txt"
N=$(( $(wc -l < "$AICI/gh-apeluri.txt") + 0 ))
if [ "$N" -le "${GH_ESECURI:-0}" ]; then echo "gh fals: eroare la apelul $N" >&2; exit 1; fi
if [ -f "$AICI/gh-iesire-$N.txt" ]; then cat "$AICI/gh-iesire-$N.txt"; else cat "$AICI/gh-iesire.txt"; fi
"""
# Python-ul fals al copiei, rulat ca „python ruleaza.py --actualizeaza --fara-confirmare” din folderul programului: notează
# apelul; pică la primele FALS_ESECURI apeluri fără să schimbe nimic; FALS_MOD=versiune schimbă versiunea și pică; altfel
# „actualizează” ca programul real: copiază ultima lansare peste program și șterge fișierul scos din versiunea nouă.
# FALS_MOD=uita lasă fișierul vechi, FALS_MOD=date atinge datele utilizatorului (verificările de după trebuie să le prindă).
FAKE_UPDATER = """#!/bin/sh
echo "$*" >> ../apeluri.txt
N=$(( $(wc -l < ../apeluri.txt) + 0 ))
if [ "$N" -le "${FALS_ESECURI:-0}" ]; then echo "EROARE: limita de cereri (fals)"; exit 1; fi
if [ "${FALS_MOD:-}" = versiune ]; then sed 's/^VERSION = .*/VERSION = "0.5.0"/' emag_spend/version.py > ../v.tmp; mv ../v.tmp emag_spend/version.py; exit 1; fi
cp -R "../../referinta/$NUME/." .
[ "${FALS_MOD:-}" = uita ] || rm -f de_sters_la_actualizare.txt
[ "${FALS_MOD:-}" != date ] || echo "atins" >> notitele_mele.txt
echo "Actualizat (fals)."
"""


def _run_ci_tools(folder: Path, commands: str, tools: Path | None = None, **env: str) -> subprocess.CompletedProcess:
    """Rulează cu bash, în `folder`: încarcă actualizare_ci.sh, apoi `commands`; `tools` (gh fals) primul în PATH.

    Mediul e cel al unui job pe Linux, cu reîncercări fără pauză; `env` adaugă variabilele pașilor (NUME, VERSIUNE...).
    """
    environment = {**os.environ, "UNELTE_CI": CI_TOOLS.as_posix(), "RUNNER_OS": "Linux", "GITHUB_REPOSITORY": "proprietar-inventat/depozit",
                   "REINCERCARI_API": "3", "PAUZA_API_SECUNDE": "0", **env}
    convert = (lambda name: f'$(cygpath -u "${name}")') if sys.platform == "win32" else (lambda name: f'${name}')
    prefix = ""
    if tools is not None:
        environment["UNELTE_FALSE"] = tools.as_posix()
        prefix = f'PATH="{convert("UNELTE_FALSE")}:$PATH"; export PATH; '
    script = f'{prefix}. "{convert("UNELTE_CI")}"\n{commands}\n'
    return subprocess.run([BASH, "-c", script], cwd=folder, env=environment, stdin=subprocess.DEVNULL, capture_output=True,
                          timeout=CI_RUN_TIMEOUT_SECONDS)


def _text_of(result: subprocess.CompletedProcess) -> tuple[str, str]:
    """(stdout, stderr) decodate UTF-8."""
    return result.stdout.decode("utf-8", errors="replace"), result.stderr.decode("utf-8", errors="replace")


def _fake_gh(folder: Path, outputs: dict[int, str] | None = None, default: str = "") -> Path:
    """Folderul cu gh-ul fals: `outputs` = ce scrie la al N-lea apel, `default` = la celelalte."""
    tools = folder / "unelte"
    tools.mkdir()
    (tools / "gh").write_bytes(FAKE_GH.encode("utf-8"))
    (tools / "gh").chmod(0o755)
    (tools / "gh-iesire.txt").write_bytes(default.encode("utf-8"))
    for number, text in (outputs or {}).items():
        (tools / f"gh-iesire-{number}.txt").write_bytes(text.encode("utf-8"))
    return tools


def test_ci_tools_are_bash_with_lf_and_valid_syntax():
    """actualizare_ci.sh: LF, UTF-8 fără BOM, declarat bash pentru shellcheck, sintaxă bună (bash -n)."""
    raw = CI_TOOLS.read_bytes()
    assert b"\r" not in raw and not raw.startswith(b"\xef\xbb\xbf"), "doar LF, fără BOM: pe mașinile Linux și macOS un CR strică pașii"
    assert raw.decode("utf-8").splitlines()[0] == "# shellcheck shell=bash"
    if BASH is None:
        pytest.skip("nu există bash aici")
    result = subprocess.run([BASH, "-n", CI_TOOLS.as_posix()], capture_output=True, timeout=CI_RUN_TIMEOUT_SECONDS)
    assert result.returncode == 0, result.stderr.decode("utf-8", errors="replace")


@needs_bash
@pytest.mark.parametrize("tags, current, expected", [
    (["v1.0.1", "v1.0.0"], "1.0.1", "1.0.0"),
    (["v1.0.0"], "1.0.0", ""),
    ([], "1.0.0", ""),
    (["v1.10.0", "v1.9.0", "v1.2.0"], "1.10.0", "1.9.0"),
    (["v2.0.0", "v1.0.0", "v1.5.0"], "1.5.0", "1.0.0"),
    (["vv1.4.0", "v1.4.0-rc1", "v01.4.0", "1.4.0", "v1.3.0"], "1.5.0", "1.3.0"),
], ids=["doua-lansari", "doar-prima", "niciuna", "sortare-numerica", "una-mai-noua-ignorata", "doar-vX.Y.Z-exact"])
def test_ci_finds_the_release_published_before_the_tested_one(tmp_path, tags, current, expected):
    """versiunea_anterioara: cea mai mare versiune vX.Y.Z mai mică decât cea testată, comparată numeric; nimic dacă nu există."""
    (tmp_path / "etichete.txt").write_bytes("".join(f"{tag}\n" for tag in tags).encode("ascii"))
    result = _run_ci_tools(tmp_path, f'versiunea_anterioara "{current}" < etichete.txt')
    out, err = _text_of(result)
    assert result.returncode == 0 and out.strip() == expected, f"cod {result.returncode}, «{out.strip()}», așteptat «{expected}»\n{err}"


@needs_bash
@pytest.mark.parametrize("failures, succeeds", [(0, True), (2, True), (3, False)])
def test_ci_retries_gh_a_limited_number_of_times(tmp_path, failures, succeeds):
    """gh_reincercat: un gh care pică de câteva ori e reluat până reușește, de cel mult REINCERCARI_API ori (aici 3)."""
    tools = _fake_gh(tmp_path, default="v1.2.3\n")
    result = _run_ci_tools(tmp_path, "gh_reincercat release view --json tagName", tools, GH_ESECURI=str(failures))
    out, err = _text_of(result)
    calls = (tools / "gh-apeluri.txt").read_text(encoding="utf-8").splitlines()
    assert len(calls) == min(failures + 1, 3), f"apeluri: {calls}\n{err}"
    assert (result.returncode == 0 and out.strip() == "v1.2.3") if succeeds else (result.returncode != 0 and "::error::" in err), f"{out}\n{err}"


@needs_bash
@pytest.mark.parametrize("expected_tag, succeeds", [("v1.0.1", True), ("v9.9.9", False), ("", True)])
def test_ci_waits_until_the_new_release_is_the_latest(tmp_path, expected_tag, succeeds):
    """ultima_eticheta: imediat după publicare, „ultima lansare” poate fi încă cea veche; așteaptă eticheta cerută, cu limită."""
    tools = _fake_gh(tmp_path, outputs={1: "v1.0.0\n"}, default="v1.0.1\n")
    result = _run_ci_tools(tmp_path, "ASTEPTARI_ULTIMA=3; PAUZA_ULTIMA_SECUNDE=0; ultima_eticheta", tools, ASTEPTATA=expected_tag)
    out, err = _text_of(result)
    if succeeds:
        assert result.returncode == 0 and out.strip() == (expected_tag or "v1.0.0"), f"{out}\n{err}"
    else:
        assert result.returncode != 0 and "::error::" in err, f"{out}\n{err}"


def _ci_release(folder: Path, name: str) -> None:
    """lansare/<name>.zip: un program inventat cu forma unei lansări (prefix, version.py, manifest, exemplul de reguli)."""
    files = {"emag_spend/version.py": f'VERSION = "{CI_VERSION}"\n', "ruleaza.py": "# program inventat\n", "docs/ghid.md": "ghid\n",
             "config/categorii.personal.exemplu.json": "{}\n"}
    files["instalare/fisiere.txt"] = "".join(f"{path}\n" for path in sorted([*files, "instalare/fisiere.txt"]))
    (folder / "lansare").mkdir()
    with zipfile.ZipFile(folder / "lansare" / f"{name}.zip", "w") as archive:
        for path, text in files.items():
            archive.writestr(f"{name}/{path}", text)


@needs_bash
@pytest.mark.parametrize("failures, mode, succeeds, calls", [
    (0, "", True, 1), (2, "", True, 3), (3, "", False, 3), (0, "versiune", False, 1), (0, "uita", False, 1), (0, "date", False, 1),
], ids=["reuseste", "reuseste-dupa-doua-esecuri", "pica-de-fiecare-data", "pica-dupa-ce-a-schimbat", "uita-fisierul-vechi", "atinge-datele"])
@pytest.mark.parametrize("context", ["pas", "conditie"])
def test_ci_terminal_update_retries_only_while_nothing_changed_and_checks_the_result(tmp_path, failures, mode, succeeds, calls, context):
    """Calea (a) a testului actualizării, pe o copie îmbătrânită a unei lansări inventate: se reia doar cât versiunea a rămas cea
    veche; după reușită, verificările prind un fișier vechi neșters și datele utilizatorului atinse. „conditie”: chemată într-un
    `if`, unde bash oprește `set -e`, funcția trebuie să dea același rezultat (o verificare nu are voie să depindă de context)."""
    name = f"cheltuieli-emag-v{CI_VERSION}"
    _ci_release(tmp_path, name)
    (tmp_path / "python_fals").write_bytes(FAKE_UPDATER.encode("utf-8"))
    commands = (f'command -v unzip > /dev/null || exit {NO_UNZIP_EXIT_CODE}\npregateste_referinta\npregateste_copia copie-a\nmkdir -p "copie-a/{name}/.venv/bin"\n'
                f'cp python_fals "copie-a/{name}/.venv/bin/python"\nchmod +x "copie-a/{name}/.venv/bin/python"\n'
                + ('actualizeaza_din_terminal copie-a' if context == "pas" else 'if actualizeaza_din_terminal copie-a; then exit 0; else exit 1; fi'))
    result = _run_ci_tools(tmp_path, commands, NUME=name, ETICHETA=f"v{CI_VERSION}", VERSIUNE=CI_VERSION, ANTERIOARA="",
                           FALS_ESECURI=str(failures), FALS_MOD=mode)
    out, err = _text_of(result)
    if result.returncode == NO_UNZIP_EXIT_CODE:
        pytest.skip("nu există unzip aici")
    made = (tmp_path / "copie-a" / "apeluri.txt").read_text(encoding="utf-8").splitlines()
    assert len(made) == calls, f"apeluri: {made}, așteptat {calls}\n{out}\n{err}"
    assert (result.returncode == 0) == succeeds, f"cod {result.returncode}\n{out}\n{err}"

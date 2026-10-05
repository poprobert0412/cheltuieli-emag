"""Ajutoare comune pentru testele-gardă (test_garda_retea, test_garda_parole, test_garda_scriere).

Ce face: găsește fișierele de verificat (sursele programului, interfața, tot ce urmează să urce în git), le parsează
(AST) și oferă mici unelte pe arborele AST. Pentru „tot ce urmează să urce” folosește `git ls-files`, iar fără git
parcurge folderul respectând `.gitignore`. Ce NU face: nu conține teste și nu decide ce e interzis (asta e treaba
fiecărei gărzi, în fișierul ei).
"""

import ast
import fnmatch
import functools
import os
import re
import shutil
import subprocess
from collections.abc import Iterator
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
PROGRAM_DIR = PROJECT_ROOT / "emag_spend"
ENTRY_POINT = PROJECT_ROOT / "ruleaza.py"
INTERFACE_DIRS = (PROJECT_ROOT / "interfata", PROJECT_ROOT / "templates")
# Foldere care nu sunt niciodată parte din ce se urcă (mediul virtual și cache-urile se refac oricând).
ALWAYS_SKIPPED_DIRS = frozenset({".git", ".venv", "__pycache__", ".pytest_cache", ".mypy_cache", ".ruff_cache", "node_modules"})
# Un fișier mai mare decât atât nu e cod sau text scris de om; 20 MB acoperă orice sursă a proiectului cu o marjă mare.
MAX_TEXT_FILE_BYTES = 20_000_000
GIT_TIMEOUT_SECONDS = 60


def relative(path: Path) -> str:
    """Calea relativă la rădăcina proiectului, cu `/`, pentru mesajele de eroare (`emag_spend/settings.py`)."""
    try:
        return Path(path).resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return Path(path).as_posix()


def program_sources() -> list[Path]:
    """Sursele programului: `emag_spend/**/*.py` și `ruleaza.py`, sortate; fără __pycache__."""
    found = [p for p in PROGRAM_DIR.rglob("*.py") if not ALWAYS_SKIPPED_DIRS.intersection(p.parts)]
    return sorted(found) + [ENTRY_POINT]


@functools.lru_cache(maxsize=None)
def parse_source(path: Path) -> ast.Module:
    """Arborele AST al unui fișier .py (memorat: aceleași surse sunt citite de mai multe gărzi)."""
    return ast.parse(Path(path).read_text(encoding="utf-8"), filename=str(path))


def interface_files(*suffixes: str) -> list[Path]:
    """Fișierele din `interfata/` și `templates/` cu una dintre extensiile date (ex. `.js`, `.html`), sortate."""
    found = []
    for folder in INTERFACE_DIRS:
        found.extend(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in suffixes)
    return sorted(found)


def dotted_name(node: ast.AST) -> str:
    """Numele cu puncte al unui lanț `a.b.c` (Name/Attribute); `''` dacă lanțul pornește din altceva (apel, subscript)."""
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return ""


def string_constants(tree: ast.AST) -> Iterator[tuple[int, str, bool]]:
    """(linie, valoare, e_docstring) pentru fiecare literal text din arbore, inclusiv bucățile f-string-urilor.

    Docstring-urile sunt marcate: documentația poate cita adrese sau cuvinte care într-un cod activ ar fi interzise.
    """
    docstring_nodes = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)) and node.body:
            first = node.body[0]
            if isinstance(first, ast.Expr) and isinstance(first.value, ast.Constant) and isinstance(first.value.value, str):
                docstring_nodes.add(id(first.value))
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            yield node.lineno, node.value, id(node) in docstring_nodes


def parent_map(tree: ast.AST) -> dict[ast.AST, ast.AST]:
    """Dicționar copil -> părinte pentru tot arborele (ast nu ține referința la părinte)."""
    return {child: parent for parent in ast.walk(tree) for child in ast.iter_child_nodes(parent)}


# ---------- tot ce urmează să urce în git ----------

def _glob_to_regex(pattern: str) -> re.Pattern:
    """Traduce un tipar de .gitignore (`*`, `**`, `?`, `[...]`) într-o expresie regulată pe căi cu `/`."""
    out, i = [], 0
    while i < len(pattern):
        ch = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("/**", i) and i + 3 == len(pattern):
            out.append("/.*")
            i += 3
        elif ch == "*":
            out.append("[^/]*")
            i += 1
        elif ch == "?":
            out.append("[^/]")
            i += 1
        elif ch == "[" and "]" in pattern[i + 2:]:
            end = pattern.index("]", i + 2)
            body = pattern[i + 1:end].replace("\\", "\\\\")
            out.append("[" + ("^" + body[1:] if body[0] in "!^" else body) + "]")  # [!a] din gitignore = [^a] în regex
            i = end + 1
        else:
            out.append(re.escape(ch))
            i += 1
    return re.compile("".join(out) + r"\Z")


class GitIgnore:
    """Interpretare minimală a `.gitignore` din rădăcină: tipare cu `*`/`**`/`?`, `/` la început sau la sfârșit, `!`.

    Folosită doar când nu există git (proiect descărcat ca ZIP). Nu cunoaște `.gitignore`-uri din subfoldere
    și nici `core.excludesFile`; pentru proiectul acesta (un singur `.gitignore`, în rădăcină) ajunge, iar
    cu git prezent se folosește `git ls-files`, care e sursa de adevăr.
    """

    def __init__(self, text: str):
        """Citește regulile din textul unui .gitignore (comentariile și rândurile goale se sar)."""
        self._rules: list[tuple[re.Pattern, bool, bool, bool]] = []  # (regex, doar_folder, ancorat, negat)
        for raw in text.splitlines():
            line = raw.rstrip("\r\n")
            if not line.strip() or line.lstrip().startswith("#"):
                continue
            negated = line.startswith("!")
            line = line[1:] if negated else line
            directory_only = line.endswith("/")
            line = line.rstrip("/")
            anchored = "/" in line
            line = line.lstrip("/")
            self._rules.append((_glob_to_regex(line), directory_only, anchored, negated))

    def is_ignored(self, relative_path: str, is_dir: bool) -> bool:
        """True dacă `relative_path` (cu `/`) e ignorat, direct sau printr-un folder părinte ignorat."""
        parts = relative_path.split("/")
        for depth in range(1, len(parts) + 1):
            candidate = "/".join(parts[:depth])
            candidate_is_dir = is_dir if depth == len(parts) else True
            if self._matches(candidate, candidate_is_dir):
                return True
        return False

    def _matches(self, candidate: str, is_dir: bool) -> bool:
        """Ultima regulă care se potrivește decide (ca în git): ignorat sau, la `!`, readmis."""
        verdict = False
        for regex, directory_only, anchored, negated in self._rules:
            if directory_only and not is_dir:
                continue
            target = candidate if anchored else candidate.rsplit("/", 1)[-1]
            if regex.match(target):
                verdict = not negated
        return verdict


def walk_respecting_gitignore(root: Path) -> list[Path]:
    """Toate fișierele de sub `root`, fără ALWAYS_SKIPPED_DIRS și fără ce ignoră `root/.gitignore`; sortate."""
    ignore_file = root / ".gitignore"
    ignore = GitIgnore(ignore_file.read_text(encoding="utf-8") if ignore_file.is_file() else "")
    found = []
    for folder, dirs, files in os.walk(root):
        base = Path(folder)
        dirs[:] = sorted(d for d in dirs if d not in ALWAYS_SKIPPED_DIRS
                         and not ignore.is_ignored((base / d).relative_to(root).as_posix(), True))
        found.extend(base / f for f in files if not ignore.is_ignored((base / f).relative_to(root).as_posix(), False))
    return sorted(found)


def _git_listing(root: Path) -> list[Path] | None:
    """Fișierele urmărite sau noi (neignorate) după `git ls-files`; None dacă nu e depozit git sau git eșuează."""
    git = shutil.which("git")
    if not git or not (root / ".git").exists():
        return None
    try:
        done = subprocess.run([git, "-C", str(root), "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                              capture_output=True, timeout=GIT_TIMEOUT_SECONDS, check=True)
    except (subprocess.SubprocessError, OSError):
        return None
    names = [n for n in done.stdout.decode("utf-8", errors="surrogateescape").split("\0") if n]
    return sorted(p for p in (root / n for n in names) if p.is_file())


def files_to_publish(root: Path = PROJECT_ROOT) -> list[Path]:
    """Tot ce ar ajunge în repo: `git ls-files` (urmărite + noi neignorate) sau, fără git, parcurgere cu .gitignore."""
    listing = _git_listing(root)
    return listing if listing is not None else walk_respecting_gitignore(root)


def read_text_or_none(path: Path) -> str | None:
    """Conținutul unui fișier text (UTF-8, cu înlocuire la octeți invalizi); None pentru binare sau fișiere uriașe."""
    try:
        if path.stat().st_size > MAX_TEXT_FILE_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        return None
    if b"\x00" in data[:8192]:
        return None
    return data.decode("utf-8", errors="replace")


def matches_any(name: str, patterns: tuple[str, ...]) -> bool:
    """True dacă `name` (fără cale) se potrivește cu vreun tipar glob din `patterns`, fără să conteze literele mari."""
    return any(fnmatch.fnmatch(name.lower(), pattern.lower()) for pattern in patterns)

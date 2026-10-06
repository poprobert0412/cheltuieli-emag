"""Face manifestul unei lansări, instalare/fisiere.txt (decis 5 oct. 2026, D8 și D16), pentru lansare.yml.

Primește: o referință git (eticheta, de obicei HEAD) și fișierul în care scrie. Lista vine din `git ls-tree -r` pe acea
referință, adică exact fișierele pe care `git archive` le pune în arhivă, plus manifestul însuși (adăugat cu --add-file).
Dă înapoi: fișierul scris: câte o cale POSIX relativă pe rând, sortată, UTF-8, LF, fără rânduri goale; codul 0. Codul 1 și
motivul dacă manifestul e deja urmărit de git (ar apărea de două ori în arhivă) sau arborele are legături ori submodule.
Ce NU face: nu face arhiva (git archive din lansare.yml) și nu aplică regulile actualizării (release_archive_check.py).
"""

import argparse
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
MANIFEST_PATH = "instalare/fisiere.txt"  # aceeași cale ca update_archive.MANIFEST_PATH (verificat de tests/test_lansare.py)
# Singurele intrări pe care le acceptă manifestul: fișiere obișnuite și executabile. O legătură (120000) sau un submodul
# (160000) n-ar ajunge în arhivă ca fișier, iar actualizarea refuză legăturile.
REGULAR_FILE_MODES = frozenset({"100644", "100755"})
GIT_TIMEOUT_SECONDS = 60


class ManifestError(Exception):
    """Arborele etichetei nu poate da un manifest bun; mesajul e deja text în română."""


def tree_entries(root: Path, ref: str) -> list[tuple[str, str]]:
    """(mod, cale) pentru fiecare intrare din arborele `ref`, recursiv, din `git ls-tree -r -z` (căile exact, fără ghilimele)."""
    output = subprocess.run(["git", "ls-tree", "-r", "-z", ref], cwd=root, capture_output=True, check=True,
                            timeout=GIT_TIMEOUT_SECONDS).stdout.decode("utf-8")
    entries = []
    for record in filter(None, output.split("\0")):
        header, path = record.split("\t", 1)
        entries.append((header.split(" ")[0], path))
    return entries


def build_manifest(entries: list[tuple[str, str]]) -> bytes:
    """Manifestul din intrările arborelui: căile plus el însuși, sortate, câte una pe rând, LF; ridică ManifestError."""
    problems = [f"{path} (mod {mode})" for mode, path in entries if mode not in REGULAR_FILE_MODES]
    if problems:
        raise ManifestError(f"arborele are intrări care nu sunt fișiere obișnuite: {', '.join(problems)}")
    paths = [path for _mode, path in entries]
    if MANIFEST_PATH in paths:
        raise ManifestError(f"{MANIFEST_PATH} e urmărit de git: ar apărea de două ori în arhivă; scoate-l cu git rm --cached")
    broken = [path for path in paths if "\n" in path or "\r" in path]
    if broken:
        raise ManifestError(f"căi cu sfârșit de rând în nume, care ar strica manifestul: {broken!r}")
    return ("\n".join(sorted([*paths, MANIFEST_PATH])) + "\n").encode("utf-8")


def main(argv: list[str] | None = None) -> int:
    """Linia de comandă: `release_manifest.py [--ref HEAD] IESIRE`; scrie manifestul și întoarce 0, altfel motivul și 1."""
    parser = argparse.ArgumentParser(description="Face instalare/fisiere.txt pentru arhiva lansării.")
    parser.add_argument("iesire", type=Path, help="unde se scrie manifestul (în afara depozitului, de exemplu $RUNNER_TEMP/fisiere.txt)")
    parser.add_argument("--ref", default="HEAD", help="referința git a lansării (implicit HEAD, eticheta descărcată)")
    parser.add_argument("--radacina", type=Path, default=PROJECT_ROOT, help="depozitul git (implicit cel al acestui script)")
    args = parser.parse_args(argv)
    try:
        manifest = build_manifest(tree_entries(args.radacina, args.ref))
    except (ManifestError, subprocess.SubprocessError, OSError, UnicodeDecodeError) as error:
        print(f"EROARE: manifestul nu se poate face: {error}", file=sys.stderr)
        return 1
    args.iesire.write_bytes(manifest)
    count = manifest.count(b"\n")
    print(f"{args.iesire}: {count} fișiere")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

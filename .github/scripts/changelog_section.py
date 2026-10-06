"""Scoate din CHANGELOG.md secțiunea unei versiuni (decis 5 oct. 2026, D16), pentru lansare.yml și release_body.py.

Primește: textul CHANGELOG-ului și versiunea X.Y.Z. Secțiunea începe la titlul exact `## X.Y.Z — AAAA-LL-ZZ` (linie lungă,
dată reală din calendar) și ține până la următorul titlu `## ` sau până la final.
Dă înapoi: textul secțiunii, fără titlu și fără rândurile goale de la margini; ChangelogError dacă lipsește, e goală, apare
de două ori sau are titlul scris greșit. Din linia de comandă: secțiunea pe ieșirea standard, cod 0; altfel motivul, cod 1.
Ce NU face: nu verifică eticheta (release_version.py) și nu compune corpul lansării (release_body.py).
"""

import argparse
import datetime
import re
import sys
from pathlib import Path

CHANGELOG = Path(__file__).resolve().parents[2] / "CHANGELOG.md"
SECTION_START = "## "  # orice titlu de nivelul 2 încheie secțiunea precedentă
HEADING = re.compile(r"## (?P<version>[0-9]+\.[0-9]+\.[0-9]+) — (?P<date>[0-9]{4}-[0-9]{2}-[0-9]{2})")


class ChangelogError(Exception):
    """CHANGELOG-ul nu are o secțiune bună pentru versiunea cerută; mesajul e deja text în română."""


def headings(text: str) -> list[tuple[int, str, str]]:
    """(rândul, versiunea, data) pentru fiecare titlu `## X.Y.Z — AAAA-LL-ZZ` valid; ChangelogError la un titlu de versiune greșit."""
    found = []
    for number, line in enumerate(text.replace("\r\n", "\n").split("\n")):
        if not line.startswith(SECTION_START):
            continue
        match = HEADING.fullmatch(line.rstrip())
        if not match:
            if re.match(r"## v?[0-9]", line):
                raise ChangelogError(f"Titlul «{line}» din CHANGELOG.md trebuie să fie exact «## X.Y.Z — AAAA-LL-ZZ» (cu linie lungă —).")
            continue
        try:
            datetime.date.fromisoformat(match["date"])
        except ValueError:
            raise ChangelogError(f"Data din titlul «{line}» nu e o zi reală (forma e AAAA-LL-ZZ).") from None
        found.append((number, match["version"], match["date"]))
    return found


def changelog_section(text: str, version: str) -> str:
    """Textul secțiunii versiunii `version`, fără titlu și fără rândurile goale de la margini; ridică ChangelogError."""
    lines = text.replace("\r\n", "\n").split("\n")
    starts = [number for number, found, _date in headings(text) if found == version]
    if not starts:
        raise ChangelogError(f"CHANGELOG.md nu are secțiunea «## {version} — AAAA-LL-ZZ»: scrie acolo ce e nou în versiunea {version}, apoi lansează.")
    if len(starts) > 1:
        raise ChangelogError(f"CHANGELOG.md are de {len(starts)} ori secțiunea versiunii {version}; păstrează una singură.")
    end = next((number for number in range(starts[0] + 1, len(lines)) if lines[number].startswith(SECTION_START)), len(lines))
    body = "\n".join(line.rstrip() for line in lines[starts[0] + 1:end]).strip("\n")
    if not body.strip():
        raise ChangelogError(f"Secțiunea versiunii {version} din CHANGELOG.md e goală: scrie ce e nou în ea.")
    return body


def main(argv: list[str] | None = None) -> int:
    """Linia de comandă: `changelog_section.py VERSIUNE [--fisier CHANGELOG.md]`; scrie secțiunea și întoarce 0, altfel 1."""
    parser = argparse.ArgumentParser(description="Scoate secțiunea unei versiuni din CHANGELOG.md.")
    parser.add_argument("versiune", help="versiunea X.Y.Z, fără „v”")
    parser.add_argument("--fisier", type=Path, default=CHANGELOG, help="CHANGELOG-ul de citit (implicit cel din proiect)")
    args = parser.parse_args(argv)
    try:
        section = changelog_section(args.fisier.read_text(encoding="utf-8"), args.versiune)
    except (ChangelogError, OSError) as error:
        print(f"EROARE: {error}", file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    print(section)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

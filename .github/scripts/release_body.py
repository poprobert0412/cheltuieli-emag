"""Compune textul paginii unei lansări de pe GitHub (decis 5 oct. 2026, D16 și D20), pentru lansare.yml.

Primește: versiunea X.Y.Z, depozitul (proprietar/nume), CHANGELOG.md și SHA256SUMS.txt al arhivei.
Dă înapoi: Markdown în ordinea fixă: `## Ce e nou în vX.Y.Z` (secțiunea din CHANGELOG, primul titlu, de unde aplicația ia
textul „Ce e nou” până la următorul `## `), apoi `## Cum îl folosești`, apoi `## Amprenta arhivei (SHA-256)`.
Ce NU face: nu verifică eticheta, nu face arhiva și nu publică nimic (gh release create din lansare.yml).
"""

import argparse
import sys
from pathlib import Path

from changelog_section import CHANGELOG, ChangelogError, changelog_section

ARCHIVE_NAME = "cheltuieli-emag-v{version}"  # același nume ca în lansare.yml și în update_archive.ARCHIVE_PREFIX_TEMPLATE
WHATS_NEW_TITLE = "## Ce e nou în v{version}"
HOW_TO_TITLE = "## Cum îl folosești"
CHECKSUMS_TITLE = "## Amprenta arhivei (SHA-256)"


def release_body(version: str, notes: str, repository: str, checksums: str) -> str:
    """Corpul lansării: „Ce e nou” (`notes`, din CHANGELOG), pașii de folosire și de actualizare, apoi amprentele (`checksums`)."""
    archive = ARCHIVE_NAME.format(version=version)
    tag = f"v{version}"
    lines = [
        WHATS_NEW_TITLE.format(version=version),
        "",
        notes.strip("\n"),
        "",
        HOW_TO_TITLE,
        "",
        f"1. Descarcă **{archive}.zip** de mai jos și extrage-l (clic dreapta → Extrage tot / Extract All).",
        "2. Pornește-l: Windows → dublu-clic pe `porneste.bat`; macOS → dublu-clic pe `porneste.command` (prima dată: "
        "Setări de sistem → Confidențialitate și securitate → „Deschide oricum”); Linux → `./porneste.sh` din Terminal.",
        "3. În pagina care se deschide apasă **„Pornește analiza”** și loghează-te tu în eMAG în fereastra de browser.",
        "",
        "Nu trebuie instalat Python: la prima pornire programul descarcă singur, în folderul lui, uv (verificat cu amprentă "
        "SHA-256), Python și pachetele fixate. Pașii detaliați: "
        f"[docs/INSTALARE.md](https://github.com/{repository}/blob/{tag}/docs/INSTALARE.md).",
        "",
        # Ce rămâne: fraza decisă pe 6 oct. 2026 (N15); config/categorii.json e al programului și se înlocuiește la actualizare.
        "Ai deja o versiune mai veche? Pornește-o ca de obicei: aplicația îți arată versiunea nouă și o instalează când apeși "
        "**„Actualizează acum”**. Rapoartele din `iesiri` și sesiunea eMAG rămân neatinse, iar regulile din "
        "`config/categorii.personal.json` rămân; modificările făcute direct în `config/categorii.json` se pierd la actualizare. "
        "Dacă ai luat programul cu git, actualizează cu `git pull`.",
        "",
        CHECKSUMS_TITLE,
        "",
        "```",
        checksums.strip("\n"),
        "```",
    ]
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Linia de comandă: scrie corpul lansării pe ieșirea standard și întoarce 0; fără secțiune în CHANGELOG scrie motivul și întoarce 1."""
    parser = argparse.ArgumentParser(description="Compune textul paginii unei lansări.")
    parser.add_argument("--versiune", required=True, help="versiunea X.Y.Z, fără „v”")
    parser.add_argument("--depozit", required=True, help="depozitul GitHub, proprietar/nume")
    parser.add_argument("--amprente", required=True, type=Path, help="SHA256SUMS.txt al arhivei")
    parser.add_argument("--changelog", type=Path, default=CHANGELOG, help="CHANGELOG-ul de citit (implicit cel din proiect)")
    args = parser.parse_args(argv)
    try:
        notes = changelog_section(args.changelog.read_text(encoding="utf-8"), args.versiune)
        checksums = args.amprente.read_text(encoding="utf-8")
    except (ChangelogError, OSError) as error:
        print(f"EROARE: {error}", file=sys.stderr)
        return 1
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stdout.write(release_body(args.versiune, notes, args.depozit, checksums))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

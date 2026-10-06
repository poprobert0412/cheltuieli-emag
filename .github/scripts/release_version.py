"""Verifică eticheta unei lansări față de versiunea programului (decis 5 oct. 2026, D1 și D16), pentru lansare.yml.

Primește: eticheta git (ex. v1.0.0). Citește VERSION din emag_spend/version.py, sursa unică a versiunii, și o verifică cu
version.parse_version: aceeași formă X.Y.Z pe care o acceptă și aplicația când caută o versiune nouă.
Dă înapoi: versiunea (fără „v”) pe ieșirea standard și codul 0; altfel mesajul pe ieșirea de erori și codul 1.
Ce NU face: nu citește CHANGELOG-ul (changelog_section.py), nu face arhiva și nu creează lansarea.
"""

import argparse
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT))

from emag_spend.version import VERSION, parse_version  # noqa: E402  (după sys.path: scriptul rulează din .github/scripts)


class ReleaseVersionError(Exception):
    """Eticheta sau versiunea nu se potrivesc; mesajul e deja text pentru cine face lansarea, în română."""


def check_tag(tag: str, version: str) -> str:
    """Întoarce `version` dacă are forma X.Y.Z și `tag` e exact "v" + version; altfel ridică ReleaseVersionError."""
    if version.startswith("v") or parse_version(version) is None:
        raise ReleaseVersionError(f"VERSION = «{version}» din emag_spend/version.py nu are forma X.Y.Z (de exemplu 1.2.3).")
    if tag != f"v{version}":
        raise ReleaseVersionError(
            f"Eticheta «{tag}» nu se potrivește cu VERSION = «{version}» din emag_spend/version.py: eticheta trebuie să fie "
            f"v{version}. Schimbă întâi VERSION (și CHANGELOG.md), apoi pune eticheta.")
    return version


def main(argv: list[str] | None = None) -> int:
    """Linia de comandă: `release_version.py ETICHETA`; scrie versiunea și întoarce 0, sau scrie motivul și întoarce 1."""
    parser = argparse.ArgumentParser(description="Verifică eticheta lansării față de VERSION din emag_spend/version.py.")
    parser.add_argument("eticheta", help="eticheta git a lansării, de exemplu v1.0.0")
    args = parser.parse_args(argv)
    try:
        print(check_tag(args.eticheta, VERSION))
    except ReleaseVersionError as error:
        print(f"EROARE: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

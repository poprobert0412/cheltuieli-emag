#!/bin/sh
# Pregătirea la pornire pe macOS și Linux (o cheamă porneste.command și porneste.sh; la a doua pornire durează o secundă).
# Primește: nimic; lucrează în folderul programului (părintele acestui fișier). Dă înapoi: cod 0 când totul e gata.
# Ce face: 1) descarcă uv în versiunea din instalare/versiuni.txt și îl folosește doar dacă amprenta SHA-256 se potrivește
# (o arhivă rămasă cu altă amprentă se descarcă o dată din nou; după dezarhivare se șterg arhivele uv din .uv/descarcari);
# 2) creează .venv cu Python-ul fixat și instalează requirements.txt (din nou doar când se schimbă cerințele);
# 3) dacă nu găsește Edge sau Chrome, descarcă o singură dată Chromium-ul lui Playwright.
# Tot ce descarcă stă în .uv/ și .venv/, în acest folder. Ce NU face: nu cere sudo, nu scrie în altă parte, nu pornește aplicația.
set -eu

ROOT=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT"
# shellcheck source=instalare/mediu.sh
. "$ROOT/instalare/mediu.sh"

valoare() {
  # Valoarea cheii $1 din instalare/versiuni.txt (rândurile au forma CHEIE=valoare).
  sed -n "s/^$1=//p" "$ROOT/instalare/versiuni.txt" | tr -d '\r' | head -n 1
}
amprenta() {
  # Amprenta SHA-256 a fișierului $1, cu unealta pe care o are sistemul.
  if command -v sha256sum >/dev/null 2>&1; then sha256sum "$1" | cut -d ' ' -f 1
  else shasum -a 256 "$1" | cut -d ' ' -f 1
  fi
}
descarca() {
  # Descarcă adresa $1 în fișierul $2, doar prin HTTPS.
  if command -v curl >/dev/null 2>&1; then curl --proto '=https' --tlsv1.2 -fsSL --retry 3 -o "$2" "$1"
  elif command -v wget >/dev/null 2>&1; then wget -q --https-only -O "$2" "$1"
  else
    echo "EROARE: lipsește curl (sau wget). Instalează-l din managerul de pachete al sistemului, apoi pornește din nou."
    return 1
  fi
}

UV_VERSION=$(valoare UV_VERSION)
PYTHON_VERSION=$(valoare PYTHON_VERSION)
case "$(uname -s)" in
  Darwin) SISTEM=MACOS; TINTA_OS=apple-darwin ;;
  Linux) SISTEM=LINUX; TINTA_OS=unknown-linux-gnu ;;
  *) echo "EROARE: sistem necunoscut ($(uname -s)). Pe Windows folosește porneste.bat."; exit 1 ;;
esac
case "$(uname -m)" in
  x86_64 | amd64) ARH=X64; TINTA_ARH=x86_64 ;;
  arm64 | aarch64) ARH=ARM64; TINTA_ARH=aarch64 ;;
  *) echo "EROARE: procesor nesuportat ($(uname -m)). Programul merge pe x86_64 și arm64."; exit 1 ;;
esac
ARHIVA="uv-$TINTA_ARH-$TINTA_OS.tar.gz"
# Arhiva păstrată în .uv/descarcari are și versiunea lui uv în nume: una rămasă de la alt UV_VERSION, de exemplu după o
# actualizare a programului, nu e luată drept cea nouă și nu dă o alarmă falsă de amprentă (decis 6 oct. 2026, N12).
ARHIVA_PASTRATA="uv-$UV_VERSION-$TINTA_ARH-$TINTA_OS.tar.gz"
AMPRENTA_ASTEPTATA=$(valoare "SHA256_${SISTEM}_${ARH}")
UV="$ROOT/.uv/bin/uv"
PY="$ROOT/.venv/bin/python"

# 1) uv, exact în versiunea fixată (se reface doar dacă lipsește sau are altă versiune)
if [ ! -x "$UV" ] || [ "$("$UV" --version 2>/dev/null | cut -d ' ' -f 2)" != "$UV_VERSION" ]; then
  echo "Prima pornire: descarc uv $UV_VERSION (instalatorul de Python), o singură dată..."
  mkdir -p "$ROOT/.uv/descarcari" "$ROOT/.uv/bin"
  FISIER="$ROOT/.uv/descarcari/$ARHIVA_PASTRATA"
  # O arhivă rămasă de la o pornire anterioară (de exemplu o descărcare întreruptă) cu altă amprentă se șterge și se descarcă
  # o singură dată din nou; abia o arhivă proaspăt descărcată cu altă amprentă oprește pregătirea (N12).
  if [ -f "$FISIER" ] && [ "$(amprenta "$FISIER")" != "$AMPRENTA_ASTEPTATA" ]; then
    rm -f "$FISIER"
  fi
  [ -f "$FISIER" ] || descarca "https://github.com/astral-sh/uv/releases/download/$UV_VERSION/$ARHIVA" "$FISIER"
  if [ "$(amprenta "$FISIER")" != "$AMPRENTA_ASTEPTATA" ]; then
    rm -f "$FISIER"
    echo "EROARE: arhiva uv descărcată nu are amprenta SHA-256 așteptată; am șters-o și NU o folosesc."
    echo "Încearcă din nou mai târziu. Dacă se repetă, deschide o problemă pe GitHub (fără date personale)."
    exit 1
  fi
  DEZARHIVAT="$ROOT/.uv/descarcari/dezarhivat"
  rm -rf "$DEZARHIVAT"
  mkdir -p "$DEZARHIVAT"
  tar -xzf "$FISIER" -C "$DEZARHIVAT"
  cp "$DEZARHIVAT"/*/uv "$UV"
  chmod +x "$UV"
  rm -rf "$DEZARHIVAT"
  # După o dezarhivare reușită (set -eu oprește scriptul mai sus la orice eșec) nu mai e nevoie de nicio arhivă uv: se șterg
  # toate uv-* din .uv/descarcari, și cea tocmai folosită, și cele rămase de la alte versiuni (decis 6 oct. 2026, P9).
  # rm -f șterge doar legătura, nu ținta; ce nu se poate șterge acum (de exemplu un folder cu acest nume) rămâne, fără să
  # oprească pregătirea, ca la del din instaleaza.bat.
  rm -f "$ROOT/.uv/descarcari"/uv-* || true
fi

# 2) .venv cu Python-ul fixat și pachetele din requirements.txt (doar pachete gata făcute: niciun cod de instalare nu rulează).
# .venv se reface dacă lipsește, e stricat sau are alt Python decât PYTHON_VERSION, comparat ca major.minor: o versiune nouă
# a programului poate trece la alt Python (decis 5 oct. 2026, D15). Versiunea fixată ajunge la Python ca argument, nu în cod.
VERIFICARE_VENV="import sys, playwright, bs4, lxml.etree; raise SystemExit('.'.join(map(str, sys.version_info[:2])) != '.'.join(sys.argv[1].split('.')[:2]))"
CERINTE=$(amprenta "$ROOT/requirements.txt")
if [ ! -x "$PY" ] || ! "$PY" -c "$VERIFICARE_VENV" "$PYTHON_VERSION" >/dev/null 2>&1; then
  echo "Pregătesc Python $PYTHON_VERSION și pachetele (prima dată durează cam un minut și are nevoie de internet)..."
  "$UV" venv --quiet --clear --python "$PYTHON_VERSION" "$ROOT/.venv"
  rm -f "$ROOT/.venv/cerinte.sha256"
fi
if [ "$(cat "$ROOT/.venv/cerinte.sha256" 2>/dev/null || true)" != "$CERINTE" ]; then
  "$UV" pip install --quiet --only-binary :all: --python "$PY" -r "$ROOT/requirements.txt"
  "$PY" -c "import playwright, bs4, lxml.etree, greenlet, pyee, soupsieve, typing_extensions"
  printf '%s\n' "$CERINTE" > "$ROOT/.venv/cerinte.sha256"
fi

# 3) un browser pe care programul îl poate controla: Edge sau Chrome, altfel Chromium descărcat o singură dată.
# Lipsa lui nu oprește pornirea: demonstrația și rapoartele vechi merg și fără; citirea contului spune atunci ce lipsește.
if [ ! -f "$ROOT/.uv/browser.ok" ]; then
  if "$PY" -m emag_spend.browser_check; then
    : > "$ROOT/.uv/browser.ok"
  else
    echo "Descarc o singură dată Chromium pentru program (aproximativ 150 MB)..."
    if "$PY" -m playwright install chromium && "$PY" -m emag_spend.browser_check; then
      : > "$ROOT/.uv/browser.ok"
    else
      echo
      echo "ATENȚIE: nu pot porni niciun browser, deci programul nu va putea citi contul eMAG (demonstrația merge)."
      echo "Ce faci, una dintre variante:"
      echo "  1. Instalează Google Chrome (https://www.google.com/chrome/) și pornește din nou."
      if [ "$SISTEM" = LINUX ]; then
        echo "  2. Instalează bibliotecile de sistem de care are nevoie Chromium (cere parola de administrator):"
        echo "     sudo \"$PY\" -m playwright install-deps chromium"
      fi
      echo
    fi
  fi
fi

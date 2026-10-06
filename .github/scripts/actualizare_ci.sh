# shellcheck shell=bash
# Uneltele pașilor din .github/workflows/actualizare.yml (decis 5 oct. 2026, D17; 6 oct. 2026, N14); fiecare pas le încarcă cu
# „. ./depozit/.github/scripts/actualizare_ci.sh”. Primește variabilele jobului (RUNNER_OS, GITHUB_REPOSITORY, REINCERCARI_API,
# PAUZA_API_SECUNDE) și, după primii pași, ETICHETA, VERSIUNE, NUME, ANTERIOARA (prin GITHUB_ENV). Dă: lansările (cu
# reîncercări), copiile vechi (ultima lansare îmbătrânită, lansarea anterioară neschimbată), cele două căi de actualizare și
# verificările de după, care întorc 1 și când sunt chemate într-un `if` (acolo bash oprește set -e). Lucrează doar în folderul
# curent. Ce NU face: nu publică și nu schimbă nicio lansare, nu folosește secrete. Testat local în tests/test_lansare.py.
set -euo pipefail

# Datele utilizatorului (inventate) care trebuie să rămână identice după actualizare.
DATE_UTILIZATOR="iesiri/x/raport.html config/categorii.personal.json notitele_mele.txt"
# Versiunea copiei „îmbătrânite” a ultimei lansări: mai mică decât orice lansare reală, deci actualizarea are ce instala.
VERSIUNE_IMBATRANITA="0.0.1"
# Fișierul „din versiunea veche” al copiei îmbătrânite: listat în manifestul ei, dar nu și în cel nou, deci trebuie șters.
FISIER_VECHI="de_sters_la_actualizare.txt"
# Imediat după publicare, „ultima lansare” poate fi încă cea veche câteva secunde: atâtea încercări, la atâtea secunde.
ASTEPTARI_ULTIMA=12
PAUZA_ULTIMA_SECUNDE=10
# Cât așteaptă calea (b), în secunde: prima pornire (cu pregătirea), verificarea versiunii noi și repornirea după instalare.
ASTEPTARE_PORNIRE=180
ASTEPTARE_VERIFICARE=120
ASTEPTARE_REPORNIRE=600
# Adresa aplicației, așa cum o scrie în jurnal la fiecare pornire (cheia e în fragmentul de după #t=).
TIPAR_ADRESA='http://127\.0\.0\.1:[0-9]*/aplicatie\.html#t=[A-Za-z0-9_-]*'

gh_reincercat() {
  # gh "$@", reluat de cel mult REINCERCARI_API ori, cu pauze de 1, 2, 3... × PAUZA_API_SECUNDE: pe mașinile GitHub API-ul poate
  # refuza o clipă (rețea, limita de cereri). Mesajele de reîncercare merg pe stderr, ca ieșirea lui gh să rămână curată.
  local incercare=1
  until gh "$@"; do
    if [ "$incercare" -ge "$REINCERCARI_API" ]; then
      echo "::error::gh ${1:-} ${2:-} a picat de $incercare ori." >&2
      return 1
    fi
    echo "gh ${1:-} ${2:-} a picat (încercarea $incercare din $REINCERCARI_API); reîncerc peste $((incercare * PAUZA_API_SECUNDE)) s." >&2
    sleep $((incercare * PAUZA_API_SECUNDE))
    incercare=$((incercare + 1))
  done
}

ultima_eticheta() {
  # Eticheta ultimei lansări publicate (releases/latest). Cu ASTEPTATA (o trimite lansare.yml) o așteaptă chiar pe aceea.
  local eticheta="" incercare
  for incercare in $(seq 1 "$ASTEPTARI_ULTIMA"); do
    eticheta=$(gh_reincercat release view --repo "$GITHUB_REPOSITORY" --json tagName --jq .tagName) || return 1
    if [ -z "${ASTEPTATA:-}" ] || [ "$eticheta" = "$ASTEPTATA" ]; then
      echo "$eticheta"
      return 0
    fi
    echo "Ultima lansare e încă $eticheta, aștept $ASTEPTATA (încercarea $incercare)..." >&2
    sleep "$PAUZA_ULTIMA_SECUNDE"
  done
  echo "::error::Ultima lansare e $eticheta, nu $ASTEPTATA." >&2
  return 1
}

versiunea_anterioara() {
  # Versiunea publicată imediat înaintea lui $1 (X.Y.Z), din etichetele de pe stdin, câte una pe rând; nimic dacă nu există.
  # Doar etichetele exact vX.Y.Z (fără zerouri în față), comparate numeric: 1.10.0 vine după 1.9.0.
  local curenta=$1
  { grep -E '^v(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)$' || true; } | sed 's/^v//' | { cat; echo "$curenta"; } \
    | LC_ALL=C sort -u -t. -k1,1n -k2,2n -k3,3n | grep -x -F -B1 "$curenta" | sed -n '1p' | { grep -v -x -F "$curenta" || true; }
}

amprente() {
  # Amprentele SHA-256 ale fișierelor date, cu unealta pe care o are sistemul.
  if command -v sha256sum > /dev/null; then sha256sum "$@"; else shasum -a 256 "$@"; fi
}

descarca_lansarea() {
  # Arhiva și SHA256SUMS.txt ale lansării cu eticheta $1, în folderul $2, cu amprenta verificată.
  gh_reincercat release download "$1" --repo "$GITHUB_REPOSITORY" --pattern "cheltuieli-emag-$1.zip" --pattern SHA256SUMS.txt \
    --dir "$2" --clobber || return 1
  if command -v sha256sum > /dev/null; then (cd "$2" && sha256sum -c SHA256SUMS.txt); else (cd "$2" && shasum -a 256 -c SHA256SUMS.txt); fi
}

lansator() {
  # Lansatorul sistemului, în folderul $1, cu argumentele rămase; stdin închis, ca pauza de la final să nu aștepte.
  local folder=$1
  shift
  case "$RUNNER_OS" in
    Windows) (cd "$folder" && cmd //c "porneste.bat $*" < /dev/null) ;;
    macOS) (cd "$folder" && ./porneste.command "$@" < /dev/null) ;;
    *) (cd "$folder" && ./porneste.sh "$@" < /dev/null) ;;
  esac
}

python_copiei() {
  # Python-ul din .venv al programului din folderul $1 (pregătit de lansator).
  if [ "$RUNNER_OS" = "Windows" ]; then echo "$1/.venv/Scripts/python.exe"; else echo "$1/.venv/bin/python"; fi
}

dosar_copiei() {
  # Folderul programului din copia $1: singurul cheltuieli-emag-v* din ea.
  local dosar
  for dosar in "$1"/cheltuieli-emag-v*; do
    echo "$dosar"
    return 0
  done
}

pregateste_referinta() {
  # Ultima lansare dezarhivată, neschimbată, în referinta/: cu ea se compară copiile după actualizare.
  mkdir referinta || return 1
  unzip -q "lansare/$NUME.zip" -d referinta
}

pregateste_copia() {
  # Copia $1: copie-* = ultima lansare îmbătrânită (VERSION 0.0.1 și FISIER_VECHI în manifest); anterioara-* = lansarea
  # anterioară, neschimbată. Pune datele utilizatorului și reține versiunea veche, manifestul vechi și amprentele datelor.
  # Se cheamă ca pas simplu: în afară de verificarea versiunii, erorile o opresc prin set -e.
  local copie=$1 arhiva veche dosar
  case "$copie" in
    anterioara-*) arhiva="anterioara/cheltuieli-emag-v$ANTERIOARA.zip"; veche=$ANTERIOARA ;;
    *) arhiva="lansare/$NUME.zip"; veche=$VERSIUNE_IMBATRANITA ;;
  esac
  mkdir "$copie"
  unzip -q "$arhiva" -d "$copie"
  dosar=$(dosar_copiei "$copie")
  if [ "$veche" = "$VERSIUNE_IMBATRANITA" ]; then
    sed "s/^VERSION = \"[^\"]*\"/VERSION = \"$VERSIUNE_IMBATRANITA\"/" "$dosar/emag_spend/version.py" > "$copie/versiune.tmp"
    mv "$copie/versiune.tmp" "$dosar/emag_spend/version.py"
    echo "rămas din versiunea veche" > "$dosar/$FISIER_VECHI"
    { cat "$dosar/instalare/fisiere.txt"; echo "$FISIER_VECHI"; } | LC_ALL=C sort > "$copie/fisiere.tmp"
    mv "$copie/fisiere.tmp" "$dosar/instalare/fisiere.txt"
  fi
  grep -qx "VERSION = \"$veche\"" "$dosar/emag_spend/version.py" || { echo "::error::$copie: versiunea veche nu e $veche"; return 1; }
  echo "$veche" > "$copie/versiune-veche.txt"
  cp "$dosar/instalare/fisiere.txt" "$copie/manifest-vechi.txt"
  # Datele utilizatorului: un raport, regulile personale (din exemplul public) și un fișier propriu, nelistat în manifest.
  mkdir -p "$dosar/iesiri/x"
  echo "<html><body>raport inventat</body></html>" > "$dosar/iesiri/x/raport.html"
  cp "$dosar/config/categorii.personal.exemplu.json" "$dosar/config/categorii.personal.json"
  echo "notițele mele" > "$dosar/notitele_mele.txt"
  # shellcheck disable=SC2086 # DATE_UTILIZATOR e o listă de căi fără spații, despărțită intenționat
  (cd "$dosar" && amprente $DATE_UTILIZATOR) > "$copie/date-inainte.txt"
}

pregateste_mediul() {
  # Prima pornire a copiei $1 cu lansatorul ei (uv, Python, pachete); trebuie să spună versiunea veche.
  lansator "$(dosar_copiei "$1")" --versiune | tee "$1/pregatire.log" || return 1
  grep -qF "Cheltuieli eMAG $(cat "$1/versiune-veche.txt")" "$1/pregatire.log"
}

identica_cu_ultima() {
  # Copia $1, după actualizare: fiecare fișier din manifestul ultimei lansări e identic cu cel din lansare, iar fișierele din
  # manifestul vechi care lipsesc din cel nou au fost șterse.
  local copie=$1 dosar cale
  dosar=$(dosar_copiei "$copie")
  while IFS= read -r cale; do
    # shellcheck disable=SC2153 # ETICHETA vine din GITHUB_ENV (pasul anterior al workflow-ului), nu e o greșeală de scriere
    cmp -s "referinta/$NUME/$cale" "$dosar/$cale" || { echo "::error::$copie: $cale diferă de lansarea $ETICHETA"; return 1; }
  done < "referinta/$NUME/instalare/fisiere.txt"
  LC_ALL=C sort "$copie/manifest-vechi.txt" > "$copie/manifest-vechi.sortat"
  LC_ALL=C sort "referinta/$NUME/instalare/fisiere.txt" > "$copie/manifest-nou.sortat"
  LC_ALL=C comm -23 "$copie/manifest-vechi.sortat" "$copie/manifest-nou.sortat" > "$copie/de-sters.txt"
  while IFS= read -r cale; do
    [ ! -e "$dosar/$cale" ] || { echo "::error::$copie: $cale trebuia șters (nu mai e în versiunea nouă)"; return 1; }
  done < "$copie/de-sters.txt"
}

verifica_dupa_actualizare() {
  # Tot ce trebuie să fie adevărat după actualizarea copiei $1: versiunea nouă, fișierele ca în lansare, datele neatinse.
  local dosar
  dosar=$(dosar_copiei "$1")
  grep -qx "VERSION = \"$VERSIUNE\"" "$dosar/emag_spend/version.py" || { echo "::error::$1: versiunea nu e $VERSIUNE"; return 1; }
  identica_cu_ultima "$1" || return 1
  # shellcheck disable=SC2086 # DATE_UTILIZATOR e o listă de căi fără spații, despărțită intenționat
  (cd "$dosar" && amprente $DATE_UTILIZATOR) | diff "$1/date-inainte.txt" - || { echo "::error::$1: datele utilizatorului s-au schimbat"; return 1; }
}

actualizeaza_din_terminal() {
  # Calea (a) pe copia $1: ruleaza.py --actualizeaza --fara-confirmare. Programul cere API-ul GitHub fără autentificare (D2):
  # dacă pică și versiunea a rămas cea veche (de exemplu limita de cereri), se reia; dacă a schimbat ceva și a picat, e eroare.
  local copie=$1 dosar veche incercare=1
  dosar=$(dosar_copiei "$copie")
  veche=$(cat "$copie/versiune-veche.txt")
  until (cd "$dosar" && "$(python_copiei .)" ruleaza.py --actualizeaza --fara-confirmare); do
    grep -qx "VERSION = \"$veche\"" "$dosar/emag_spend/version.py" || { echo "::error::$copie: actualizarea a picat după ce a schimbat versiunea"; return 1; }
    [ "$incercare" -lt "$REINCERCARI_API" ] || { echo "::error::$copie: actualizarea din terminal a picat de $incercare ori"; return 1; }
    echo "$copie: actualizarea din terminal a picat (încercarea $incercare); reîncerc peste $((incercare * PAUZA_API_SECUNDE)) s."
    sleep $((incercare * PAUZA_API_SECUNDE))
    incercare=$((incercare + 1))
  done
  verifica_dupa_actualizare "$copie" || return 1
  echo "$copie: actualizată din terminal de la $veche la $VERSIUNE; fișierele sunt ca în lansare, datele sunt identice."
}

porneste_versiunea_noua() {
  # După calea (a): lansatorul copiei $1 reface pregătirea și pornește versiunea nouă.
  lansator "$(dosar_copiei "$1")" --versiune | tee "$1/dupa.log" || return 1
  grep -qF "Cheltuieli eMAG $VERSIUNE" "$1/dupa.log"
}

adresa() {
  # A $2-a adresă a aplicației din jurnalul $1 (una la fiecare pornire), așteptată cel mult $3 secunde.
  local gasita
  for _ in $(seq 1 "$3"); do
    gasita=$(grep -o "$TIPAR_ADRESA" "$1" | sed -n "$2p" || true)
    if [ -n "$gasita" ]; then
      echo "$gasita"
      return 0
    fi
    sleep 1
  done
  return 1
}

port_din() {
  # Portul din adresa aplicației $1 (http://127.0.0.1:<port>/…), fără sed.
  local rest=${1#http://127.0.0.1:}
  echo "${rest%%/*}"
}

camp_json() {
  # Câmpul $2 (cale cu puncte, ex. check.status) din JSON-ul de pe stdin, citit cu Python-ul $1; gol dacă lipsește.
  "$1" -c "import functools, json, sys; v = functools.reduce(lambda d, k: d.get(k) if isinstance(d, dict) else None, sys.argv[1].split('.'), json.load(sys.stdin)); print('' if v is None else v)" "$2"
}

opreste_aplicatia() {
  # Oprește aplicația de pe portul $1, cu cheia $2.
  curl -sf -X POST -H "X-App-Token: $2" -H 'Content-Type: application/json' -d '{}' "http://127.0.0.1:$1/api/shutdown" > /dev/null
}

actualizeaza_din_aplicatie() {
  # Calea (b) pe copia $1: aplicația pornită prin lansator, POST /api/update/apply, repornirea făcută de lansator (a doua adresă
  # din jurnal), versiunea nouă în /api/hello, oprirea cu codul 0. Verificarea versiunii noi rulează o dată, la pornire, fără
  # autentificare (D2): dacă dă „eroare” (de exemplu limita API-ului), aplicația se oprește și pornește din nou, de cel mult
  # REINCERCARI_API ori, cu pauze tot mai lungi.
  local copie=$1 dosar py jurnal url port cheie stare cod acum pid incercare=1
  dosar=$(dosar_copiei "$copie")
  py=$(python_copiei "$dosar")
  while :; do
    jurnal="$copie/aplicatie-$incercare.log"
    lansator "$dosar" --aplicatie --fara-browser > "$jurnal" 2>&1 &
    pid=$!
    url=$(adresa "$jurnal" 1 "$ASTEPTARE_PORNIRE") || { cat "$jurnal"; return 1; }
    port=$(port_din "$url")
    cheie=${url##*#t=}
    stare=""
    for _ in $(seq 1 $((ASTEPTARE_VERIFICARE / 2))); do
      stare=$(curl -sf -H "X-App-Token: $cheie" "http://127.0.0.1:$port/api/update" | camp_json "$py" check.status 2> /dev/null || true)
      case "$stare" in noua | la-zi | eroare) break ;; esac
      sleep 2
    done
    if [ "$stare" = noua ]; then
      break
    fi
    curl -s -H "X-App-Token: $cheie" "http://127.0.0.1:$port/api/update" || true
    echo
    opreste_aplicatia "$port" "$cheie" || return 1
    wait "$pid" || return 1
    if [ "$stare" != eroare ] || [ "$incercare" -ge "$REINCERCARI_API" ]; then
      echo "::error::$copie: verificarea din aplicație a dat «$stare» (încercarea $incercare)."
      cat "$jurnal"
      return 1
    fi
    echo "$copie: verificarea din aplicație a dat «eroare» (încercarea $incercare); repornesc peste $((incercare * PAUZA_API_SECUNDE)) s."
    sleep $((incercare * PAUZA_API_SECUNDE))
    incercare=$((incercare + 1))
  done
  cod=$(curl -s -o "$copie/raspuns.json" -w '%{http_code}' -X POST -H "X-App-Token: $cheie" -H 'Content-Type: application/json' -d '{}' "http://127.0.0.1:$port/api/update/apply")
  if [ "$cod" != 202 ]; then
    echo "::error::$copie: POST /api/update/apply a răspuns $cod."
    cat "$copie/raspuns.json" "$jurnal"
    return 1
  fi
  # Aplicația descarcă, verifică, instalează și se oprește cu codul 75; lansatorul pornește varianta lui nouă.
  url=$(adresa "$jurnal" 2 "$ASTEPTARE_REPORNIRE") || { cat "$jurnal"; return 1; }
  port=$(port_din "$url")
  cheie=${url##*#t=}
  acum=$(curl -sf -H "X-App-Token: $cheie" "http://127.0.0.1:$port/api/hello" | camp_json "$py" version)
  if [ "$acum" != "$VERSIUNE" ]; then
    echo "::error::$copie: după repornire /api/hello spune $acum, nu $VERSIUNE."
    cat "$jurnal"
    return 1
  fi
  opreste_aplicatia "$port" "$cheie" || return 1
  wait "$pid" || { echo "::error::$copie: lansatorul nu s-a oprit cu codul 0"; return 1; }
  # Mesajul de repornire e al lansatorului; la copia îmbătrânită lansatorul vechi și cel nou sunt aceleași, deci textul e știut.
  case "$copie" in
    anterioara-*) ;;
    *) grep -q "Programul a fost actualizat. Pornesc versiunea nouă" "$jurnal" || { echo "::error::$copie: lansatorul nu a anunțat repornirea"; return 1; } ;;
  esac
  verifica_dupa_actualizare "$copie" || return 1
  echo "$copie: actualizată din aplicație la $VERSIUNE, repornită de lansator și oprită curat."
}

#!/bin/sh
# Pornește programul pe Linux. Din Terminal, în folderul programului: ./porneste.sh
# La prima pornire pregătește singur ce lipsește (instalare/pregatire.sh: uv, Python, pachete, browser), apoi pornește
# aplicația locală (doar pe acest calculator) și deschide pagina ei în browser.
# Argumentele, dacă le dai, merg direct la ruleaza.py (ex.: ./porneste.sh --demo, ./porneste.sh --sterge-sesiunea).
# Nu cere sudo și nu scrie în afara acestui folder.
# La codul de repornire (programul s-a actualizat din aplicație) pornește din nou lansatorul NOU, care reface pregătirea
# (decis 5 oct. 2026, D14): actualizarea înlocuiește fișierele prin redenumire, deci acest shell citește în continuare
# varianta veche, iar `exec sh` o citește pe cea nouă de la început.
# ORDINEA, contract pentru versiunile instalate (decis 6 oct. 2026, P1): 1) recuperarea unei actualizări întrerupte,
# 2) pregătirea, 3) programul. Cu .actualizare/jurnal.json și Python-ul din .venv, recuperarea rulează cu el
# (python -m emag_spend.update_recovery, doar biblioteca standard) ÎNAINTEA lui pregatire.sh, care altfel ar citi
# instalare/versiuni.txt și requirements.txt dintr-un arbore amestecat (vechi + nou) și ar putea opri pornirea, de exemplu
# fără internet, înainte ca recuperarea să apuce să ruleze. Fără .venv merge întâi pregătirea, iar recuperarea o face
# ruleaza.py. La codul 1 al recuperării lansatorul se oprește cu mesaj; la orice alt cod pornește din nou, cu `exec sh`,
# lansatorul de pe disc (recuperarea poate să-l fi refăcut), o singură dată: cel repornit primește semnul
# CHELTUIELI_EMAG_DUPA_RECUPERARE și nu mai încearcă recuperarea (o mai încearcă oricum ruleaza.py).
set -eu
ROOT=$(cd "$(dirname "$0")" && pwd)
# Calea absolută a acestui lansator, pentru repornire: după `cd "$ROOT"` un $0 relativ (ex. folder/porneste.sh) n-ar mai fi bun.
LANSATOR="$ROOT/$(basename "$0")"
# Codul cu care programul cere repornirea după o actualizare: settings.EXIT_CODE_RESTART (EX_TEMPFAIL), ales ca să nu se
# confunde cu erorile programului (0 și 1). Testele verifică să fie aceeași valoare ca în settings.py.
COD_REPORNIRE=75
# Semnul pus de recuperare pentru lansatorul repornit imediat după ea (P1); se golește aici, ca să nu ajungă la program.
DUPA_RECUPERARE=${CHELTUIELI_EMAG_DUPA_RECUPERARE:-}
unset CHELTUIELI_EMAG_DUPA_RECUPERARE
cd "$ROOT"
# shellcheck source=instalare/mediu.sh
. "$ROOT/instalare/mediu.sh"

asteapta_enter() {
  # Lasă fereastra deschisă la final când programul a fost pornit dintr-un terminal interactiv.
  if [ -t 0 ]; then
    printf '\nApasă Enter ca să închizi.'
    read -r _ || true
  fi
}

# 1) Recuperarea (P1).
if [ -z "$DUPA_RECUPERARE" ] && [ -e "$ROOT/.actualizare/jurnal.json" ] && [ -x "$ROOT/.venv/bin/python" ]; then
  COD=0
  "$ROOT/.venv/bin/python" -m emag_spend.update_recovery || COD=$?
  if [ "$COD" -eq 1 ]; then
    echo
    echo "Pornirea s-a oprit: actualizarea întreruptă nu a putut fi desfăcută. Citește mesajul de mai sus, rezolvă cauza și pornește din nou."
    asteapta_enter
    exit 1
  fi
  export CHELTUIELI_EMAG_DUPA_RECUPERARE=1
  exec sh "$LANSATOR" "$@"
fi
# 2) Pregătirea, apoi 3) programul.
if ! sh "$ROOT/instalare/pregatire.sh"; then
  echo
  echo "Pregătirea nu s-a terminat. Citește mesajul de mai sus, rezolvă cauza și pornește din nou."
  asteapta_enter
  exit 1
fi
[ "$#" -gt 0 ] || set -- --aplicatie
COD=0
"$ROOT/.venv/bin/python" "$ROOT/ruleaza.py" "$@" || COD=$?
if [ "$COD" -eq "$COD_REPORNIRE" ]; then
  echo
  echo "Programul a fost actualizat. Pornesc versiunea nouă; pregătirea poate dura puțin."
  exec sh "$LANSATOR" "$@"
fi
echo
if [ "$COD" -eq 0 ]; then
  echo "Gata. Rezultatele rămân în folderul iesiri."
else
  echo "Programul s-a oprit cu o eroare (cod $COD). Citește mesajul de mai sus; jurnalul complet e în folderul logs."
fi
asteapta_enter
exit "$COD"

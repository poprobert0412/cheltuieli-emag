# Politica de securitate

Cheltuieli eMAG lucrează cu istoricul tău de cumpărături și cu o sesiune logată în contul tău eMAG. Pagina asta spune ce face programul, ce lasă pe calculator, cum raportezi o problemă și ce **nu** garantează.

## Cum raportezi o vulnerabilitate

1. **Raport privat (preferat):** în depozitul de pe GitHub deschide fila **Security** → **Report a vulnerability**. Raportul e vizibil doar pentru autor.
2. **Dacă butonul nu apare** (funcția trebuie activată de autor, în *Settings → Security*): deschide un **Issue** public **fără detalii sensibile**: scrie doar că ai găsit o problemă de securitate și ceri un contact privat. Fără pași de exploatare, fără fragmente de cod care o arată, fără date personale. Autorul îți răspunde cerând un canal privat pentru detalii.

Ce să incluzi într-un raport privat: ce ai găsit, pașii ca să o reproduci, ce impact are și de unde ai descărcat programul (data sau commit-ul). Ce să **nu** incluzi nici măcar într-un raport privat: `comenzi.json`, `retururi.json`, `analiza.json`, conținutul `iesiri/`, `logs/` sau `.profil_browser/`, capturi cu comenzi reale. Dacă ai nevoie să arăți un caz, înlocuiește datele reale cu unele inventate.

Proiectul e întreținut de o singură persoană, fără termene garantate de răspuns. Se ocupă de versiunea din ramura `main`.

## Ce date atinge programul și unde le ține

Programul citește pagini din contul tău eMAG și calculează local. **Parola și codul 2FA nu trec prin program:** te loghezi tu, în fereastra de browser, iar codul nu tastează în paginile eMAG, nu citește cookie-urile și nu ascultă traficul browserului (o verifică `tests/test_garda_parole.py`).

| Loc | Ce conține | Date personale? |
|---|---|---|
| `.profil_browser/` | profilul ferestrei Edge a programului: sesiunea eMAG (cookie-uri), istoricul paginilor deschise acolo, memoria cache, iar dacă Edge s-a conectat singur cu un cont Microsoft, numele și e-mailul acestuia | **Da, cel mai sensibil.** Tratează-l ca pe o parolă |
| `iesiri/<data>_<ora>/` | `comenzi.json`, `retururi.json` (ce a citit), `analiza.json`, `produse.csv`, `istoric_preturi.csv`, `rezumat.txt`, `raport.html` (rezultatul), `run_info.json` | Da, în afară de `run_info.json`: istoricul tău de cumpărături, cu numere de comandă |
| `logs/<data>_<ora>.log` | jurnalul sesiunii: progres și erori | Puține: căile pot conține numele contului Windows, iar erorile pot cita numere de comandă |
| `%TEMP%` (în afara folderului) | fișiere proprii ale **Edge**, nu ale programului: două `.tmp` șterse la închidere și `cv_debug.log`, care rămâne (măsurat pe o instalare de test, cu o pagină goală) | Necunoscut: conținutul lor nu e controlat de program și nu l-am inspectat pe o sesiune reală |

Programul nu scrie în Registry, în AppData sau în folderul tău personal (verificat de `tests/test_garda_scriere.py` pe fluxurile `--demo`, `--din-cache` și `--sterge-sesiunea`; fluxul cu login real nu rulează în teste). Instalarea pachetelor (`instaleaza.bat`) scrie doar în `.venv/`, în folderul programului.

**Ce nu citește:** numele, telefonul, e-mailul și adresa din paginile eMAG. Parserul de comenzi nu caută astfel de date, iar cel de retururi se oprește înainte de secțiunea „Detalii de contact”. Paginile HTML nu se salvează: se parsează pe loc.

**Limita:** câteva câmpuri se salvează ca text liber, exact cum îl afișează eMAG: statusul unui bloc, data plasării comenzii, numele produselor și titlurile pașilor de retur. Dacă eMAG schimbă pagina, în ele ar putea ajunge și alt text din apropiere. Înainte să trimiți un fișier de rezultat cuiva, deschide-l și uită-te la el.

## Ce face programul în rețea

- **Paginile eMAG.** Programul cere pagini doar de pe `www.emag.ro`, doar cu GET, prin browserul pe care îl controlează, cu sesiunea ta. Fereastra Edge încarcă paginile ca atunci când intri tu, deci contactează și serviciile lor și pe cele ale Edge (autentificare, statistici); programul nu controlează acele cereri.
- **Fără telemetrie.** Programul nu trimite rapoarte, statistici sau erori nicăieri, nu are server al autorului și nu își face singur actualizări.
- **Linkurile din interfață.** Numerele de comandă sunt linkuri către `emag.ro`, cu `rel="noopener noreferrer"`, care se deschid doar când apeși pe ele, în browserul tău.
- **Serverul local al aplicației** (`porneste.bat` sau `ruleaza.py --aplicatie`). Pagina `aplicatie.html` vorbește cu un server pornit de program pe calculatorul tău. Ce face, după codul din `emag_spend/app_server.py` și `emag_spend/app_security.py`:
  - ascultă **doar pe `127.0.0.1`** (nu pe rețea), pe un port ales de sistem la fiecare pornire, nu pe unul fix;
  - o **cheie secretă generată la fiecare pornire** (`secrets.token_urlsafe(32)`) e pusă în fragmentul adresei deschise de program (`#t=…`, partea care nu se trimite serverului), citită de pagină și ținută doar în memorie; fiecare cerere `/api/*` o trimite în antetul `X-App-Token`, iar serverul o compară cu `hmac.compare_digest` (lipsă sau greșită: 401). Cheia nu se scrie în jurnal;
  - antetul `Host` trebuie să fie exact `127.0.0.1:<port>` sau `localhost:<port>` (altfel 403), ca o pagină de pe internet să nu poată ajunge la server prin DNS rebinding;
  - `Origin` lipsește sau e exact originea serverului (altfel 403); cererile `POST` cer `Content-Type: application/json` și un corp de cel mult 4 KiB; nu există niciun antet CORS;
  - fișierele statice se servesc **doar din `interfata/`**, după adrese exacte dintr-o listă albă făcută la pornire (fără listare de foldere, fără `..`, fără căi absolute, fără legături simbolice, fără nume speciale Windows); din `iesiri/` se pot descărca doar `raport.html`, `produse.csv`, `istoric_preturi.csv`, `rezumat.txt` și `analiza.json`, pentru rulări cu nume valid;
  - fiecare răspuns poartă `Content-Security-Policy` strictă (`default-src 'none'`, scripturi și stiluri doar de la același server, `connect-src 'self'`, `frame-ancestors 'none'`), `X-Content-Type-Options: nosniff`, `Referrer-Policy: no-referrer`, `Cross-Origin-Resource-Policy: same-origin`, `X-Frame-Options: DENY` și `Cache-Control: no-store`; antetul `Server` lipsește;
  - se oprește singur după **30 de minute fără nicio cerere** (valoare implicită, schimbabilă între 1 minut și 24 de ore cu `EMAG_APP_IDLE_MINUTES`; nu se oprește cât rulează o analiză), la butonul „Închide aplicația” și la `Ctrl+C`; la oprire se închide și analiza în curs, odată cu fereastra de browser a programului;
  - **nu trimite nimic spre exterior**; singura conexiune în afara calculatorului rămâne browserul controlat de program, spre `emag.ro`.

Aceste reguli sunt verificate de teste automate: `tests/test_app_security.py` (fiecare regulă, separat, fără rețea) și, pe un server real pornit pe `127.0.0.1`, `tests/test_app_routes.py` (cheie, `Host`, `Origin`, tip de conținut, mărime, metode, lipsa CORS, antetele pe toate răspunsurile), `tests/test_app_static.py` (lista albă; `..`, `%2e%2e`, `\`, nume 8.3, `::$DATA`, foldere, `/.git/`, `/config/`, `/iesiri/`), `tests/test_app_lifecycle.py` (legare doar la `127.0.0.1`, oprire, jurnal fără cheie) și `tests/test_app_integration.py` (cap-la-cap, pe date inventate). Garda de rețea îi dă lui `app_server.py` singura excepție de a asculta, doar pe `127.0.0.1`, fără conexiuni ieșite.

**Ce NU garantează serverul local.** Un program rău intenționat care rulează pe același calculator, sub același cont Windows, poate încerca să vorbească cu el dacă află portul și cheia (cheia apare în adresa deschisă în browser; cu `--fara-browser` sau dacă browserul nu se poate deschide, programul o scrie și în fereastra neagră). Serverul apără de pagini web și de alți utilizatori ai rețelei, nu de un program deja instalat pe calculatorul tău. Cheia nu se reutilizează: la următoarea pornire e alta. Dacă reîncarci pagina aplicației, ea pierde cheia (nu se păstrează nicăieri) și trebuie să pornești aplicația din nou.

## Ce să NU faci

- **Nu descărca programul din altă parte decât din acest depozit** (nu de pe un „mirror”, dintr-un mesaj, de pe un forum sau dintr-un fișier primit). Un `.bat` modificat poate face orice cu calculatorul tău.
- **Nu atașa în Issues sau în postări** `comenzi.json`, `retururi.json`, `analiza.json`, fișiere din `iesiri/`, `logs/` sau capturi cu nume, adresă sau comenzi reale.
- **Nu rula nimic ca Administrator.** Programul nu are nevoie de drepturi de administrator.
- **Nu pune folderul programului în OneDrive** sau altă sincronizare cu un cloud: rapoartele și sesiunea ar ajunge acolo.
- **Nu trimite și nu urca `.profil_browser/`** nicăieri. Nimeni care te ajută cu o problemă nu are nevoie de el.
- Atenție la partajarea ecranului: raportul arată ce ai cumpărat.

## Cum verifici ce rulezi

- Fișierele `.bat` sunt text: deschide-le în Notepad (clic dreapta → Edit) înainte să le rulezi. Comentariile (`rem`) spun ce face fiecare.
- Pe GitHub vezi istoricul fiecărui fișier (butonul **History**) și ce s-a schimbat la fiecare commit. Dacă ai clonat depozitul cu git, `git log -1` arată commit-ul pe care rulezi.
- Rulează testele (`pytest`, vezi [CONTRIBUTING.md](CONTRIBUTING.md)) pe copia ta: ele verifică, printre altele, că nu există tastare în pagini, module de rețea neașteptate și scrieri în afara folderelor permise. Nu înlocuiesc citirea codului.

## Cum ștergi urmele

1. Rulează `sterge_sesiunea.bat` (scrii `DA`): șterge `.profil_browser/`, adică sesiunea eMAG salvată.
2. Șterge folderele `iesiri/` și `logs/` din folderul programului (și golește Coșul de reciclare).
3. **Schimbă parola contului eMAG** dacă vrei să închizi o sesiune veche: ștergerea locală nu te deloghează de pe eMAG.
4. Opțional: `cv_debug.log` din `%TEMP%` aparține Edge-ului pornit de program.

Pașii completi, inclusiv ordinea la ștergerea folderului: [docs/INSTALARE.md](docs/INSTALARE.md#dezinstalare-completă).

## Lanțul de aprovizionare (dependențe și verificări automate)

Ce există în `.github/` și în fișierele de dependențe:

- **Dependențe fixate** la versiuni exacte (`requirements.txt` pentru rulare, `requirements-dev.txt` pentru teste), instalate doar ca pachete gata făcute (`--only-binary=:all:`), fără cod de instalare rulat local, și fără memorie locală (`--no-cache-dir`).
- **`pip-audit`** (`siguranta.yml`) caută vulnerabilități cunoscute în dependențele fixate, la fiecare push, pull request și săptămânal.
- **Dependabot** (`dependabot.yml`) propune săptămânal actualizări pentru pachetele Python și pentru acțiunile GitHub; fiecare vine ca pull request, trece prin teste și o aprobă autorul.
- **CodeQL** (`codeql.yml`) analizează static Python și JavaScript, cu setul `security-extended`, la push, pull request și săptămânal.
- **gitleaks** (`secrete.yml`) scanează tot istoricul git și arborele curent după parole, chei și date personale românești (IBAN, CNP), cu binar de versiune și sumă SHA-256 fixate; un al doilea pas pică dacă git urmărește fișiere cu date personale (sesiunea, rezultatele, cookie-urile).
- **Teste** (`teste.yml`) rulează toate testele, inclusiv gărzile de rețea, parole și scriere, pe Windows, cu Python 3.13 și 3.14.
- Acțiunile GitHub sunt **fixate pe SHA complet**; workflow-urile au drepturi doar de citire (CodeQL adaugă dreptul de a încărca rezultatele) și nu primesc niciun secret.

**Limita:** aceste fișiere au fost verificate local cu `actionlint` și, pe cât se putea, simulate, dar **nu s-au putut verifica local rularea lor efectivă pe GitHub, CodeQL, Dependabot și Edge pe `windows-latest`**. Insigna „Teste” din README apare abia după prima rulare. Ele nu verifică codul dependențelor terțe (Playwright, lxml ș.a.) dincolo de vulnerabilitățile cunoscute publicate.

## Riscuri pe care le preiei

- **eMAG poate limita sau bloca accesul automat** la contul tău. Programul cere paginile câte 3 odată, fără pauze între ele; nu îl rula de zeci de ori pe zi. Accesul automat poate fi contrar termenilor eMAG: folosirea e pe răspunderea ta, doar pe contul propriu.
- **Programul nu a fost auditat de un terț.** Testele-gardă caută tipare în cod și nu dovedesc absența oricărei probleme.
- **Partea cu browserul nu e validată cap-la-cap pe mai multe conturi reale.** Dacă eMAG schimbă paginile, programul poate da erori sau cifre greșite.
- **Sesiunea salvată e echivalentul unei parole.** Nu presupune că `.profil_browser/` e inutilizabil pentru altcineva.
- **Proiect independent, neafiliat cu eMAG.**

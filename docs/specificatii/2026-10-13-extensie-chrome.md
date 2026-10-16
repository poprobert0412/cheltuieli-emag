# Extensia Chrome „Cât am cheltuit pe eMAG”: specificație v1

Stare: **aprobată de Robert pe 13 oct. 2026** („DA LA tot”); numele exact **Cât am cheltuit pe eMAG** a fost aprobat pe 16 oct. 2026 (E15), fără „neoficial” în nume. Propunerea E9 este depășită; aprobarea numelui nu aprobă celelalte texte din magazin.

Actualizare operațională, 16 oct. 2026: Robert a aprobat textele (E20), a păstrat GPL-3.0 (E19), a cerut lansare publică de la început (E21) și a autorizat asistentul să publice și să trimită extensia în magazin (E22). Etapa nelistată și operarea exclusiv manuală de către Robert din planul inițial sunt depășite; ghidul curent este `docs/MAGAZIN-EXTENSIE.md`.

Scop: aceeași analiză ca programul de azi (cât ai plătit efectiv pe eMAG, pe categorii, ani, vânzători și produse), dar
instalată dintr-un clic din Chrome Web Store, fără Python, arhivă sau lansatoare. Totul rulează în Chrome-ul utilizatorului;
nimic nu pleacă spre autor sau spre terți. Doar Chrome în v1.

## 1. Decizii

Seria „E” (extensia) e nouă; rândurile decise intră în `docs/DECIZII.md` odată cu primul cod care le folosește, iar
`tests/test_decizii.py` primește seria E.

| Id | Data | Decizia | Stare |
|---|---|---|---|
| E1 | 13.10.2026 | Parsarea și calculul rulează în extensie, în JavaScript. Fără Pyodide, fără programul local. | decis de Robert |
| E2 | 13.10.2026 | Programul Python rămâne și e referința: aceleași intrări trebuie să dea același JSON, la ban, în ambele (test de paritate în CI). | decis de Robert |
| E3 | 13.10.2026 | Istoric: întâi nelistată (doar cu link), publică după confirmarea pe conturi reale; înlocuită de E21 din 16.10.2026, publică de la început. | depășit explicit de E21 |
| E4 | 13.10.2026 | Se păstrează doar ultima analiză (cifrele, comenzile și retururile citite, jurnalul; fără HTML), cu buton „Șterge datele”. | decis de Robert |
| E5 | 13.10.2026 | Cererile spre eMAG pleacă din fila eMAG de lucru (aceeași origine), nu direct din pagina extensiei. | decis de Robert (probat, §11) |
| E6 | 13.10.2026 | Fila de lucru se deschide goală și primește adresa după ce e pus ascultătorul de încărcare. | decis de Robert (§4) |
| E7 | 13.10.2026 | Codul stă în același depozit, în `extensie/`; `config/*.json`, `dashboard.js/.css`, `app.css`, `templates/raport.html` și `demo-data.js` rămân surse unice, copiate la build. | decis de Robert |
| E8 | 13.10.2026 | Versiunea extensiei are o singură sursă, `extensie/manifest.json`, separată de versiunea programului. | decis de Robert |
| E9 | 13.10.2026 | Istoric: propunerea cerea „neoficial” în nume și nu folosea sigla eMAG. Înlocuită de E15 pe 16.10.2026; nu se mai impune „neoficial” în nume. | depășit explicit de E15 |
| E15 | 16.10.2026 | Numele exact: „Cât am cheltuit pe eMAG”, fără „neoficial” în nume; autor Robert Pop. Mențiunea descriptivă de neafiliere și lipsa siglei eMAG rămân. | decis de Robert |
| E10 | 13.10.2026 | Declarația din magazin: non-trader (persoană fizică, fără bani din extensie). | decis de Robert |
| E11 | 13.10.2026 | Istoric: Robert urca manual arhiva din CI; E22 din 16.10.2026 autorizează asistentul să publice și să trimită extensia în magazin. | depășit explicit de E22 |
| E12 | 14.10.2026 | Diferența lxml / HTML5 la o entitate fără „;” e acceptată: extensia o decodează, ca pagina văzută de om; testul o fixează exact. | decis de Robert |
| E13 | 14.10.2026 | Iconița: bonul aplicației pe un pătrat deschis cu colțuri rotunjite (varianta B), vizibil și pe bara întunecată. | decis de Robert |
| E14 | 14.10.2026 | Capturile de verificare ale extensiei rămân pe disc (`docs/extensie/capturi/`), în afara git și a arhivei programului. | decis de Robert |

## 2. Ce există și ce se refolosește

**Neschimbat (copiat la build în `extensie/dist/`):**
- `interfata/assets/dashboard.js` și `dashboard.css`: raportul întreg; nu face cereri, numele produselor intră doar ca text.
- `interfata/assets/app.css`: designul ecranelor aplicației locale.
- `interfata/assets/demo-data.js`: analiza demonstrativă gata calculată („Încearcă cu date inventate”, fără cont).
- `config/categorii.json`, `avertismente.json`, `culori.json`, `restituiri.json`.
- `templates/raport.html`: scheletul raportului autonom descărcabil.
- Celelalte scripturi ale aplicației locale (temă, formatare, DOM) doar dacă nu depind de serverul local; lista exactă intră
  în planul de implementare, după citirea lor.

**Portat 1:1 în JS** (același nume de fișier, `.js`, în `extensie/src/calcul/` și `extensie/src/exporturi/`), cam 2.900 de
rânduri Python cu comentarii: `html_lines` (BeautifulSoup devine `DOMParser`), `order_parser`, `return_parser`,
`block_status`, `money_ro`, `dates_ro`, `text_normalize`, `models` (LineOutcome), `line_ledger`, `block_payment`,
`proportional_split`, `return_matcher`, `refund_modes`, `paid_totals`, `classifier`, `product_key`, `price_history`,
`warning_messages`, `warning_details`, `spend_analysis`, `order_links`, `csv_export`, `price_history_csv`, `report_html`.

**Rescris pentru Chrome** (aceeași logică, alt mecanism), în `extensie/src/colectare/`: `browser_session` (verificarea
login-ului), `order_list_scraper`, `return_list_scraper`, `page_fetcher`, `emag_collector`, `progress`.

**Nu intră** (nu au rost într-o extensie): actualizatorul (`update_*.py`, `app_update_job.py`: magazinul actualizează singur),
serverul local (`app_server.py`, `app_*.py`), lansatoarele, `session_cleaner.py` (sesiunea e a Chrome-ului utilizatorului),
generatorul demo (`demo_*.py`: demo-ul vine gata calculat), `site_demo_writer.py`, `report_opener.py`, `browser_check.py`.

## 3. Arhitectura

```
iconița extensiei ── background.js ──> deschide sau aduce în față aplicatie.html (o filă a extensiei)

aplicatie.html: toată analiza rulează aici, cât e deschisă fila
  ├─ colectare/  fila de lucru www.emag.ro, în fundal: navigare, funcții ambalate injectate (chrome.scripting),
  │              citirea listelor randate, cererile de detalii din filă (aceeași origine, sesiunea utilizatorului)
  ├─ calcul/     html_lines -> order_parser / return_parser -> spend_analysis (portul din emag_spend/)
  ├─ exporturi/  raport.html autonom, produse.csv, istoric_preturi.csv, analiza.json, comenzi.json, retururi.json, jurnal.txt
  ├─ stocare/    chrome.storage.local: ultima analiză (E4) și jurnalul ei
  └─ ecrane/     ecranele aplicației locale, cu același design; raportul = dashboard.js neschimbat
```

- **De ce o filă, nu worker-ul din fundal:** Chrome oprește worker-ul după 30 s fără activitate și după 5 min pe o operație;
  o analiză durează câteva minute. `background.js` doar deschide fila și închide fila de lucru rămasă orfană.
- **Permisiuni, exact:** `storage`, `scripting`, `https://www.emag.ro/*`. Fără `tabs`, `downloads`, `cookies`, `webRequest`,
  `<all_urls>`, `content_scripts`, `web_accessible_resources`. La instalare Chrome arată un singur avertisment: citirea și
  modificarea datelor de pe www.emag.ro. Descărcările se fac din pagina extensiei, cu `<a download>` pe un Blob.
- **CSP:** cea implicită din Manifest V3 (`script-src 'self'; object-src 'self'`): fără scripturi inline, fără `eval`, fără
  WebAssembly, fără cod de pe internet. Cerința magazinului „No remote code” e îndeplinită prin construcție.
- **Versiunea minimă de Chrome:** propus 120 (toate API-urile folosite există dinainte); e2e rulează doar pe versiunea curentă.
- **Configurările fără `fetch`:** la build, fiecare `config/*.json` devine un modul JS (`export default …`), deci extensia nu
  face cereri nici la propriile fișiere; singurul `fetch` din cod rămâne cel spre eMAG (§9, garda de rețea).
- **Memorie:** HTML-ul unei pagini se parsează imediat și se aruncă, ca în `page_fetcher.py`.
- **Granița cu pagina eMAG:** funcțiile injectate rulează în lumea izolată a extensiei (`world: 'ISOLATED'`), deci scripturile
  paginii nu le pot modifica. Ce întorc (HTML, numere de comandă) e tratat ca date neîncrezute: `DOMParser` nu rulează
  scripturi și nu încarcă resurse, iar raportul pune textul doar prin `textContent`, ca azi.

## 4. Fluxul unei analize

Constantele au aceleași nume și valori ca în `emag_spend/settings.py`; un test de paritate le compară (§6).

1. **Deschidere.** Dacă există o analiză salvată, apare raportul ei, cu data, plus „Analiză nouă” și „Șterge datele”.
   Altfel: „Gata de start”, cu pragul pentru achiziții mari, „Pornește analiza” și „Încearcă cu date inventate”.
2. **Fila de lucru (E6).** `chrome.tabs.create({url: 'about:blank', active: false})`, apoi o singură funcție de navigare
   pentru toate paginile: pune ascultătorul de încărcare, navighează, așteaptă `complete`, verifică redirectul la login.
   De ce: ascultătorul există înainte de navigare, deci încărcarea nu poate fi ratată (cursă reală la `create` cu adresă).
   Efect secundar, de spus deschis (CLAUDE.md §4): la `create` cu adresă, Playwright nu poate intercepta prima navigare
   (probat 13.10.2026), deci testele n-ar putea servi eMAG-ul fals primei pagini. Alternativa fără schimbare în producție:
   testele pun www.emag.ro pe 127.0.0.1 (`--host-resolver-rules`) cu un server HTTPS local și certificat de test; e mai
   complicată și cere un certificat generat la fiecare rulare. **Decide Robert.**
3. **Login.** Semnele de azi: pagina are „Comenzile mele” și „Log out”. Fără ele: ecranul „Loghează-te în eMAG”, cu un buton
   care aduce fila de lucru în față; verificare la 2 s (`LOGIN_POLL_SECONDS`), cel mult 10 min (`LOGIN_WAIT_SECONDS`). Parola
   și codul 2FA le scrie omul, în pagina eMAG; extensia nu atinge câmpurile și nu citește cookie-uri.
4. **Lista de comenzi.** Ca `order_list_scraper.py`: pagina 1, apoi 2…N după paginare; citire stabilă (două citiri identice,
   fără scheletele `000000000`, termen `LIST_RENDER_TIMEOUT_SECONDS`), dubluri eliminate, plafon `MAX_LIST_PAGES`.
5. **Detaliile comenzilor.** Ca `page_fetcher.py`: câte `FETCH_CONCURRENCY` (3) deodată, `FETCH_RETRIES` încercări cu pauză
   `FETCH_BACKOFF_SECONDS` × încercarea, `FETCH_TIMEOUT_MS` pe cerere; redirect la login = „sesiunea a expirat”. Cererea e
   un `fetch` pe cale relativă, injectat în fila de lucru; HTML-ul vine în pagina extensiei, se parsează și se aruncă.
6. **Lista de retururi.** Ca `return_list_scraper.py`: „Vezi mai mult” până nu mai crește lista (15 s pe creștere, plafon
   `MAX_RETURN_LOAD_MORE_CLICKS`); cont fără retururi = listă goală, cu notă în jurnal.
7. **Detaliile retururilor.** Ca la pasul 5.
8. **Final.** Fila de lucru se închide (și la eroare, la oprire sau când se închide fila extensiei); urmează analiza, salvarea
   (E4) și raportul.

**Progres:** fazele și numărătorile din `progress.py` („Caut comenzile: pagina 4 din 12”, „Citesc detaliile: 57/240”).
**Oprire:** „Oprește” anulează cererile rămase și închide fila de lucru. **O singură analiză odată:** lacăt în
`chrome.storage.session`; a doua filă a extensiei spune că rulează deja una.

## 5. Erorile

Mesajele urmează `app_errors.py`: ce s-a întâmplat, ce poți face, „Descarcă jurnalul”. Cazuri: login neterminat în 10 min;
sesiune expirată la jumătate; pagină schimbată (lipsește „Comanda nr.” sau „Retur #”); rețea căzută după toate încercările;
fila de lucru închisă de om; fila extensiei închisă (analiza se oprește); a doua analiză simultană; stocare plină.

## 6. Paritatea Python ↔ JS (E2)

Fără ea, o diferență mică de port dă cifre greșite care arată normal. Metoda:

- **Generatorul**, `tests/paritate_export.py` (Python, cu `.venv`), scrie în `extensie/build/paritate/` (ignorat de git), din:
  paginile inventate din `tests/html_builders.py` (ambele așezări), scenariile din `tests/scenario.py`, comenzile demonstrative
  (`demo_data.py`) și un corpus de capcane. Pentru fiecare intrare: ieșirea Python (liniile și numele din HTML,
  `Order`/`ReturnRequest` ca `to_dict`, analiza întreagă, octeții CSV-urilor, rezultatul fiecărei funcții-primitive) și
  constantele din `settings.py` folosite de extensie.
- **Testele JS** citesc fișierele și cer egalitate exactă: aceeași structură și aceleași valori, ordinea listelor contează,
  CSV-urile la octet. Rulează local și în CI, la fiecare push; o schimbare de calcul în Python neportată pică CI-ul.
  Doar `html_lines` are nevoie de `DOMParser`, deci testul lui rulează în Chromium, printr-o pagină de test a extensiei;
  parserele primesc liniile gata extrase de Python și, ca restul, se testează în Node.
- **Capcanele cunoscute**, fiecare cu o funcție în `extensie/src/calcul/python_compat.js` și cazuri în corpus:
  1. `round(x, 1)` din Python rotunjește jumătatea la par pe valoarea binară exactă; `toFixed` nu (12,25 dă 12,2 în
     Python, 12,3 în JS). Folosit la `last_vs_prev_pct`.
  2. `//` și `%` pe numere negative (podea, nu trunchiere): liniile negative de tip „Custom Discount”.
  3. Sortările cu chei-tuplu compară textul pe puncte de cod; JS compară unități UTF-16 (diferă la emoji).
  4. Regex: în Python, `\b`, `\d`, `\s`, `\w` sunt Unicode, în JS nu (sau cu alt set); `$` din Python acceptă un `\n` final.
     `classifier.js` traduce modelele din `config/categorii.json` într-un subset portabil: azi se folosesc doar `\b` (705 de
     ori), `(?:…)`, ancore, `\d`, `\s`, clase și `{n,m}`. Un test în Python și unul în JS refuză orice altă construcție, ca o
     regulă nouă să nu dea categorii diferite în extensie.
  5. `normalize_text`: NFKD e la fel; `unicodedata.combining` și `str.casefold` (ß devine „ss”) nu au echivalent exact în JS,
     deci tabelele vin din Python, într-un fișier JS generat și comis, cu test de prospețime.
  6. `difflib.get_close_matches` / `SequenceMatcher` (pragul 0,88 la potrivirea retururilor, cu „autojunk” peste 200 de
     caractere): port fidel, verificat pe mii de perechi de nume.
  7. `str.strip()` / `str.split()` fără argument folosesc spațiile Unicode din Python; `int()` acceptă cifre din alte alfabete.
  8. Cheile numerice („2024”) au altă ordine în obiectele JS; comparația e pe structură, iar ordinea afișată vine din liste
     deja sortate explicit.
  9. CSV: regulile modulului `csv` din Python (ghilimele doar la nevoie, CRLF, BOM).
  10. Parserul HTML: lxml și parserul HTML5 din Chrome pot construi arbori diferiți pe HTML stricat. Paginile inventate sunt
      bine formate și nu dovedesc nimic aici, deci se acoperă prin testul de acceptanță pe contul real (§10).
- **Comparatorul pe date reale**, `tests/compara_extensie.py`: primește un folder al programului (`iesiri/<rulare>`) și
  fișierele descărcate din extensie; compară `comenzi.json` și `retururi.json` exact și recalculează analiza Python din
  comenzile extensiei, fără regulile personale de categorii (extensia nu le are în v1), comparând-o cu `analiza.json` a extensiei.

## 7. Interfața

- **Designul e cel al aplicației locale** (`app.css` și `dashboard.css`): „Gata de start”, „Analiza e în lucru”, „Raportul
  tău” cu descărcările, „Analiza s-a oprit din cauza unei probleme”, „Analiza a fost oprită” și întrebările frecvente.
- **Dispar:** cheia de acces, oprirea serverului, actualizările, „Șterge sesiunea” (sesiunea e a Chrome-ului) și istoricul
  rulărilor (E4: doar ultima).
- **Piese fără design**, făcute în limbajul vizual existent și arătate cu capturi înainte să intre în cod (**APROBARE**):
  1. ecranul „Loghează-te în eMAG” (butonul care aduce fila eMAG în față, termenul de 10 minute);
  2. butonul „Șterge datele” și confirmarea lui;
  3. rândul „Ultima analiză: <data>” la deschidere;
  4. iconițele extensiei (16, 32, 48 și 128 px), generate prin script din bonul de azi (favicon-ul aplicației);
  5. textele noi: întrebările frecvente ale extensiei și mesajele de eroare noi din §5.
- **Fără fereastră pop-up:** clicul pe iconiță deschide direct fila aplicației.
- **Limba:** doar română, în extensie și în magazin.
- Un test verifică faptul că fiecare clasă CSS folosită de `aplicatie.html` din extensie există în `app.css` sau `dashboard.css`.

## 8. Stocare, confidențialitate, încadrare legală

- **Stocare (E4):** o singură intrare în `chrome.storage.local`: versiunea extensiei, data, pragul, analiza, comenzile și
  retururile citite, jurnalul. La contul real de azi, cam 0,5 MB; cota e 10 MB fără `unlimitedStorage`. O analiză nouă o
  înlocuiește pe cea veche abia când se termină cu bine; jurnalul rulării în curs se salvează separat, pe parcurs, și rămâne
  și după o eroare, până la rularea următoare. „Șterge datele” golește tot; dezinstalarea la fel.
- **Nu se păstrează niciodată:** HTML-ul paginilor, cookie-uri, parola, numele, adresa, telefonul, e-mailul (parserele nu le
  citesc, ca în Python).
- **Rețea:** doar www.emag.ro, doar citire (GET) plus clicurile pe „Vezi mai mult”, totul din fila de lucru. Fără altă gazdă,
  fără telemetrie, fără verificare de versiune.
- **Jurnalul (CLAUDE.md §9):** fiecare rulare scrie pe parcurs (după fiecare fază) mesajele de la INFO în sus, cu ora,
  nivelul și modulul, deci o rulare căzută la pasul 5 lasă pașii 1–4. Se descarcă drept `jurnal.txt`.
- **Politica de confidențialitate:** obligatorie în magazin chiar dacă datele nu pleacă de pe calculator (User Data FAQ).
  Fișier nou, `docs/CONFIDENTIALITATE-EXTENSIE.md`, cu declarația „Limited Use” cerută de magazin; textul trece pe la
  **APROBARE**.
- **Încadrare (`site-legal.md`):** unealtă gratuită, open-source (GPL-3.0), fără cont, fără server, publicată de o persoană
  fizică; nu e site de prezentare, magazin, aplicație cu abonament, chatbot sau aplicație de sănătate. Autorul nu primește
  date personale, iar politica o spune explicit. Interpretare (nu text de lege): CRA nu se aplică software-ului liber
  nemonetizat (considerentul 18 al Reg. (UE) 2024/2847); se reevaluează dacă apar donații sau bani din extensie. Declarația
  de non-trader (E10) are același temei: fără scop comercial.

## 9. CI și construire

- **Node 24** (cel instalat), cu `engines` în `package.json`; trecerea la 26 după 28.10.2026, conform `intretinere.md`.
- **Dependențe doar de dezvoltare:** `playwright-core` (aceeași versiune ca Playwright-ul din `requirements.txt`).
  `package-lock.json` comis, `npm ci`, `npm audit --omit=dev --audit-level=high`, Dependabot pentru `extensie/`.
- **Comenzi** (în `extensie/package.json`): `build` (copiază sursele unice în `dist/`, face arhiva), `test:unit`,
  `test:paritate` (rulează întâi generatorul Python), `test:e2e`, `verify` (toate, în ordine).
- **CI:** job nou `extensie` în `teste.yml`, pe `ubuntu-24.04`: Python (generatorul), Node, `npm ci`,
  `npx playwright-core install --with-deps chromium`, `npm run verify`, arhiva ca artefact cu păstrare scurtă (constantă cu
  nume). Fără secrete, `permissions: contents: read`, acțiunile fixate pe SHA, ca în restul workflow-urilor.
- **Gărzile Python existente cresc:** rețeaua (JS-ul extensiei: `fetch` doar în modulul de descărcare, doar căi relative sub
  www.emag.ro; fără `eval`, `new Function`, scripturi externe sau `innerHTML` cu date; manifestul are exact permisiunile din
  §3), caracterele și sedilele (și pe `extensie/`), deciziile (seria E). Garda de parole acoperă deja tot depozitul.

## 10. Testare și verificare

- **Unitare** (`node --test`): fiecare modul portat, separat.
- **Paritate:** §6.
- **E2e** (Playwright + extensia din `dist/` + un eMAG fals servit prin `context.route`, sau prin serverul HTTPS local dacă
  Robert alege alternativa din §4, pasul 2). Local pe Edge (canalul `msedge`):
  probat pe 13.10.2026, Edge 155 încarcă extensia, iar Chromium-ul descărcat de Playwright nu pornește din aplicația Claude
  (CLAUDE.md §15) și Chrome oficial nu mai încarcă extensii din linia de comandă. În CI pe Chromium-ul Playwright, pe Linux.
  Scenarii: cont nelogat, apoi login și analiză; cont fără retururi; sesiune expirată la jumătate; fila de lucru închisă;
  oprire; demo; ultima analiză la redeschidere; ștergere; descărcări (CSV la octet egal cu Python); a doua filă.
  **Testele nu ating niciodată rețeaua reală:** browserul de test pornește cu `--host-resolver-rules=MAP * ~NOTFOUND`
  (nicio adresă nu se rezolvă), iar eMAG-ul fals nu folosește redirecționări: urmarea unei redirecționări nu mai trece
  prin `context.route` și ar pleca spre serverul real (probat pe 13.10.2026). Redirecturile spre login se testează unitar,
  pe colector, cu o filă falsă.
- **Accesibilitate:** axe pe fiecare ecran, ca la aplicația locală. Regula celor trei motoare nu se aplică: extensia e doar
  pentru Chrome.
- **`security-auditor`** pe codul extensiei, înainte de „gata”.
- **Acceptanța pe contul real [R]:** în aceeași zi, programul Python și extensia pe contul lui Robert, apoi comparatorul din §6.
  Orice diferență se explică sau se repară înainte de publicare. Prietenii cu versiunea nelistată compară totalul extensiei cu
  „Comenzile mele” de pe eMAG.

## 11. Ce s-a probat deja (13.10.2026)

Probă de unică folosință, în folderul temporar al sesiunii, cu o extensie minimă și un eMAG fals servit de Playwright:

| Verificare | Rezultat |
|---|---|
| Edge 155 (Playwright, `msedge`) încarcă o extensie MV3 din folder | da |
| Chrome oficial (`chrome`) o încarcă | nu (nu pornește worker-ul extensiei) |
| Chromium-ul descărcat de Playwright pornește din aplicația Claude | nu (`spawn UNKNOWN`) |
| Lista randată de JS se citește din fila deschisă de extensie | da |
| `fetch` din fila eMAG trimite cookie-ul `SameSite=Lax` și pe cel `None` | da, pe amândouă |
| `fetch` direct din pagina extensiei trimite cookie-ul `SameSite=Lax` | **nu** (doar pe cel `None`) |
| Prima navigare a unei file creată cu adresă trece prin `context.route` | nu; creată goală și apoi navigată: da |
| Urmarea unei redirecționări servite de eMAG-ul fals trece prin `context.route` | **nu**: pleacă în rețeaua reală |
| Cu `--host-resolver-rules=MAP * ~NOTFOUND`, cererile scăpate ajung în rețea | nu (eșuează la rezolvarea adresei) |

Concluzie: cererile pleacă din fila eMAG (E5), iar testele blochează rețeaua reală (§10). Notă: în timpul acestor probe au
ajuns la www.emag.ro adevărat câteva cereri anonime (pagina listei și pagina de login, fără cont), din profiluri de browser
temporare, șterse după.

**Pe contul real** (pasul 1 din §13, 14.10.2026, Edge 155, cu sesiunea salvată de program, dintr-o copie temporară a
profilului, ștearsă după; rulat de Opus cu permisiunea dată de Robert pentru exact comenzile din `extensie/scripts/cont_real.mjs`):

| Verificare | Rezultat |
|---|---|
| Login recunoscut prin „Comenzile mele” + „Log out” | da |
| Lista de comenzi citită dintr-o filă din fundal | da: 10 comenzi pe pagină, primele la ~0,85 s, listă stabilă la ~1,6 s, fără schelete |
| Pagina unei comenzi, cerută din fila eMAG | 200, cu sesiune, ~0,6 s, ~230 KB |
| Aceeași pagină, cerută direct din pagina extensiei | 200, cu sesiune (pe acest profil Edge cookie-ul a plecat; E5 rămâne, fiindcă nu depinde de setări) |
| „Vezi mai mult” la retururi | există, e vizibil, lista crește la un clic în ~0,6 s |

Toată proba a durat 12 s. Folderul `extensie/proba/` s-a șters după.

**Acceptanța pe contul real** (§10, 14.10.2026, Edge 155, comenzile exacte permise de Robert): programul Python (`ruleaza.py --iesire iesiri/acceptanta`) și extensia construită (`cont_real.mjs acceptanta`), una după alta, pe același cont. `tests/compara_extensie.py`: comenzile și retururile citite de extensie sunt identice câmp cu câmp cu ale programului, iar analiza recalculată de Python din comenzile extensiei (fără regulile personale) e identică cu `analiza.json` al extensiei. Durata: programul ~3,5 min, extensia 4 min 18 s.

## 12. Nu intră în v1

- Regulile personale de categorii (`config/categorii.personal.json`): importul lor în extensie (propus pentru v1.1).
- Istoricul mai multor rulări (E4).
- `rezumat.txt` (`summary_text.py`): raportul și CSV-urile acoperă aceleași cifre.
- Publicarea automată prin API-ul magazinului (E11).
- Alte browsere (Edge Add-ons, Firefox), `emag.bg`, `emag.hu`, alte limbi.
- Buton pe paginile eMAG (`content_scripts`): intrarea rămâne iconița extensiei.

## 13. Ordinea de lucru

Robert = [R], Claude și agenții = [C]. Agenții sunt Sonnet, cu brief, fișiere disjuncte și verificare proprie înainte de
„gata”; Opus face planul detaliat, brief-urile și verificarea finală.

1. [C] Extensia de probă pentru contul real: raportează doar numărători, coduri HTTP și da/nu, nimic personal.
   [R] o încarcă în Chrome (Developer mode, „Load unpacked”) și apasă un buton: cam 15 min.
   Verifică: login, lista randată într-o filă din fundal (și cât durează), `fetch` din filă cu sesiune, `fetch` direct
   (așteptat: fără sesiune), „Vezi mai mult”. **APROBARE:** arhitectura merge pe date reale.
2. [C] În paralel cu 1 (nu depinde de el): agentul A, cu generatorul de paritate, `python_compat.js`, tabelele Unicode,
   `SequenceMatcher` și traducerea regex.
3. [C] După 2, în paralel: agentul B (parsarea: `html_lines`, `money_ro`, `dates_ro`, `text_normalize`, `block_status`,
   `order_parser`, `return_parser`) și agentul C (analiza și exporturile, restul modulelor din §2).
4. [C] După 1, în paralel cu 3: agentul D (extensia: manifestul, `background.js`, ecranele, colectarea, stocarea, jurnalul,
   build-ul, iconițele). **APROBARE vizuală:** capturile pieselor fără design (§7).
5. [C] Agentul E, după 3 și 4: e2e, gărzile extinse, jobul de CI.
6. [C] Agentul F, în paralel cu 5: textele (secțiune în README și SECURITY, politica de confidențialitate, textele și
   capturile pentru magazin, întrebările frecvente, rândurile E din DECIZII.md, CHANGELOG-ul extensiei). **APROBARE:** texte.
7. [C] Verificarea finală (Opus): diff-ul întreg, toate testele Python și JS, `security-auditor`.
8. [R] Acceptanța pe contul real (§10). **APROBARE:** publicare nelistată.
9. [R] Magazinul: contul de dezvoltator, declarația (E10), formularul de date, arhiva, vizibilitate „Nelistat”, trimiterea la
   recenzie (de obicei câteva zile, uneori săptămâni). Ghid pas cu pas [R]/[C], salvat și în README.
10. [R] Prietenii testează pe conturile lor. **APROBARE:** trecerea pe „Public” și postarea pe Reddit.

Scara: 6 agenți Sonnet, cel mult 3 deodată, în 3 valuri (A; apoi B, C și D; apoi E și F). Estimare grosieră: o zi de lucru
a agenților, plus timpul de recenzie al Google. Nimic nu se comite fără cererea lui Robert.

## 14. Riscuri

| Risc | Efect | Ce îl prinde sau îl reduce |
|---|---|---|
| Diferențe de port Python↔JS | cifre greșite care par corecte | paritate în CI (§6), comparatorul pe contul real |
| eMAG schimbă paginile | extensia și programul greșesc deodată | aceleași fixture-uri pentru ambele; avertismentele existente din analiză |
| Pagini reale stricate parsate altfel de Chrome decât de lxml | linii lipsă sau în plus | acceptanța pe contul real (§10) |
| Fila de lucru în fundal randează lent (Chrome încetinește filele ascunse) | analiză lentă, termen depășit | proba de la pasul 1 măsoară; dacă e cazul, fila se aduce în față cât se citesc listele |
| Marca „eMAG” în nume | plângere, extensie scoasă | fără siglă, mențiunea descriptivă de neafiliere; numele exact fără „neoficial” este decis prin E15 |
| Termenii eMAG (accesul automat) | eMAG poate bloca tiparul sau reclama | mențiunea din README; ritmul de azi (3 cereri deodată); publicitatea pe Reddit crește vizibilitatea |
| Recenzia magazinului respinge | întârziere | permisiuni minime, fără cod de la distanță, modul demo pentru recenzent, justificări scrise |
| Edge încetează să încarce extensii din linia de comandă | e2e doar în CI | CI-ul rămâne poarta; local, Chromium dintr-un terminal deschis din Start |
| Utilizatorul închide fila extensiei în timpul analizei | analiză pierdută | worker-ul închide fila de lucru; jurnalul salvat pe parcurs spune unde s-a oprit |

## 15. Ce rămâne pentru Robert

- Aprobarea acestei specificații și a deciziilor marcate „propus” (mai ales E6, E9, E10).
- Pasul 1 (cam 15 min) și acceptanța de la pasul 8.
- Contul de dezvoltator Chrome Web Store: taxă unică, 5 $ după surse neoficiale (Google nu scrie suma în documentație; o
  vezi pe ecranul de înregistrare), e-mailul de dezvoltator (nu se mai schimbă după), declarația trader / non-trader.
- Urcarea arhivei și butoanele din magazin, după ghidul pregătit.

## 16. Surse (citite pe 13.10.2026)

- Cereri din extensii: https://developer.chrome.com/docs/extensions/develop/concepts/network-requests
- Cookie-uri și extensii: https://developer.chrome.com/docs/extensions/develop/concepts/storage-and-cookies
- Viața worker-ului: https://developer.chrome.com/docs/extensions/develop/concepts/service-workers/lifecycle
- CSP în extensii: https://developer.chrome.com/docs/extensions/reference/manifest/content-security-policy
- `chrome.storage`: https://developer.chrome.com/docs/extensions/reference/api/storage
- Date personale (FAQ): https://developer.chrome.com/docs/webstore/program-policies/user-data-faq
- Limited Use: https://developer.chrome.com/docs/webstore/program-policies/limited-use
- Trader / non-trader: https://developer.chrome.com/docs/webstore/program-policies/trader-disclosure
- Recenzia: https://developer.chrome.com/docs/webstore/review-process
- Înregistrarea: https://developer.chrome.com/docs/webstore/register
- Imaginile din magazin: https://developer.chrome.com/docs/webstore/images
- Câmpurile de confidențialitate: https://developer.chrome.com/docs/webstore/cws-dashboard-privacy
- Impersonare și proprietate intelectuală: https://developer.chrome.com/docs/webstore/program-policies/impersonation-and-intellectual-property
- API-ul magazinului v2: https://developer.chrome.com/blog/cws-api-v2
- Playwright și extensiile: https://playwright.dev/docs/chrome-extensions

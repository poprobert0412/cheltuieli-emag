# Instalare și folosire, pas cu pas

Ghid pentru cineva care nu a instalat niciodată un program de acest fel. Prima dată durează cam 10 minute, din care cea mai mare parte e descărcarea.

**Cuprins:** [Ce îți trebuie](#ce-îți-trebuie) · [1. Descarcă și extrage](#1-descarcă-și-extrage) · [2. Calea principală: porneste.bat](#2-calea-principală-pornestebat) · [3. Varianta cu pași separați](#3-varianta-cu-pași-separați) · [Actualizare](#actualizare) · [Dezinstalare completă](#dezinstalare-completă) · [Probleme frecvente](#probleme-frecvente) · [Pentru programatori](#pentru-programatori) · [Ce a fost testat și ce nu](#ce-a-fost-testat-și-ce-nu)

> [!WARNING]
> Proiect independent, **neafiliat cu eMAG**. Partea cu browserul (login și citirea paginilor eMAG) **nu a fost încă validată cap-la-cap pe mai multe conturi reale**: eMAG își poate schimba paginile, iar atunci programul poate da erori sau cifre greșite. Compară totalurile cu pagina „Comenzile mele” de pe eMAG. Accesul automat poate fi contrar termenilor eMAG: îl folosești pe răspunderea ta, doar pe contul tău.

## Ce îți trebuie

| Ce | Detalii |
|---|---|
| **Windows 10 sau 11** | Lansatoarele `.bat` sunt doar pentru Windows. Testat pe Windows 11. |
| **Edge sau Chrome** | Edge vine cu Windows. Programul folosește browserul deja instalat: nu descarcă altul. Implicit e Edge; pentru Chrome vezi [Probleme frecvente](#probleme-frecvente). |
| **Python 3.10 sau mai nou** | Se instalează o singură dată, de pe [python.org](https://www.python.org/downloads/). Testat cu 3.13 și 3.14; 3.10–3.12 ar trebui să meargă, dar nu au fost încercate. |
| **Internet** | La instalare (1–3 minute) și când programul citește contul tău. |
| **Spațiu pe disc** | În jur de 150 MB pentru mediul `.venv`, plus rapoartele tale. |
| **Cont eMAG** | Doar pentru analiza reală. Demonstrația cu date inventate nu cere cont. |

**Cum instalezi Python** (dacă nu îl ai):

1. Deschide [python.org/downloads](https://www.python.org/downloads/) și apasă butonul mare **Download Python 3.x**.
2. Pornește fișierul descărcat. În prima fereastră, **bifează „Add python.exe to PATH”** (jos, înainte de „Install Now”). Fără ea, lansatoarele pot să nu găsească Python (uneori îl găsesc oricum prin comanda `py`, dar bifa evită problemele).
3. Apasă **Install Now**, așteaptă „Setup was successful” și închide.

## 1. Descarcă și extrage

1. Pe pagina depozitului ([github.com/poprobert0412/cheltuieli-emag](https://github.com/poprobert0412/cheltuieli-emag)) apasă butonul verde **Code**, apoi **Download ZIP**.
2. Găsește fișierul descărcat (de obicei în `Descărcări`/`Downloads`), clic dreapta pe el → **Extract All…** (Extrage tot) → alege un folder **simplu și scurt**, de exemplu `C:\cheltuieli-emag` → **Extract**.
3. Deschide folderul extras. Trebuie să vezi fișiere ca `porneste.bat`, `instaleaza.bat`, `ruleaza.py` și folderul `interfata`.

Reguli pentru folder:

- **Extrage, nu rula din ZIP.** Dacă dai dublu-click pe un `.bat` direct din fereastra ZIP-ului, el nu găsește celelalte fișiere și spune „nu găsesc fișierele programului lângă acest script”.
- **Nu în OneDrive și nu într-un folder sincronizat cu un cloud** (Desktop și Documente pot fi sincronizate de OneDrive). Rapoartele din `iesiri/` și sesiunea eMAG din `.profil_browser/` ar ajunge în cloud, adică exact ce vrei să eviți.
- **Cale scurtă.** `instaleaza.bat` refuză un folder a cărui cale are peste 190 de caractere (Windows nu poate porni anumite fișiere cu căi lungi) și te roagă să muți folderul în `C:\cheltuieli-emag`.
- **Caractere speciale:** spații, diacritice și paranteze au fost încercate și merg (`instaleaza.bat`, `demo.bat`, `sterge_sesiunea.bat`, într-un folder de test). Caracterele `&`, `%`, `!` și `^` în calea folderului **nu au fost încercate**; o cale simplă evită problemele.

### Avertismente Windows la prima rulare

Fișierele `.bat` descărcate de pe internet nu sunt semnate digital, deci Windows poate arăta un avertisment (SmartScreen: „Windows a protejat computerul”, sau „Nu putem verifica cine a creat acest fișier”). Textul exact diferă puțin după versiunea de Windows. Nu înseamnă că fișierul e periculos și nu înseamnă că e sigur: înseamnă doar că Windows nu-l cunoaște.

Cum verifici ce rulezi:

1. Clic dreapta pe `porneste.bat` → **Edit** (sau **Open with → Notepad**). Sunt câteva zeci de rânduri de text; comentariile (rândurile cu `rem`) spun ce face fiecare.
2. Lansatoarele nu conțin comenzi de ștergere și nu descarcă nimic ele însele; singurul lucru descărcat e instalarea pachetelor din `requirements.txt` (de pe pypi.org, de către `pip`), la `instaleaza.bat`. Ștergerea sesiunii o face programul Python, după ce scrii `DA`.
3. Dacă ai încredere, apasă **Mai multe informații** (More info), apoi **Rulează oricum** (Run anyway).

Ca să nu mai apară avertismentul pentru niciun fișier din folder, poți face un pas în plus **înainte** de extragere: clic dreapta pe ZIP → **Proprietăți** → bifează **Deblocare** (Unblock) → OK. Abia apoi extragi. Acest pas nu a fost verificat pe fiecare versiune de Windows.

Dacă antivirusul blochează sau șterge un fișier, **nu-l dezactiva**. Verifică întâi conținutul fișierului (e text), compară-l cu cel din depozitul de pe GitHub și, dacă ai dubii, nu rula nimic.

## 2. Calea principală: porneste.bat

Un dublu-click pornește aplicația locală, cu un singur buton pentru toată analiza.

1. **Dublu-click pe `porneste.bat`.** Se deschide o fereastră neagră (consola). Dacă programul nu a fost instalat încă, vezi „Prima pornire: instalez ce lipsește. Se face o singură dată, durează 1-3 minute și are nevoie de internet.” și apoi mesajele lui `instaleaza.bat` („Caut Python 3.10 sau mai nou…”, „Creez mediul izolat .venv…”, „Instalez pachetele din requirements.txt…”). Dacă lipsește Python, mesajul îți spune cum îl instalezi (vezi [Ce îți trebuie](#ce-îți-trebuie)); după ce l-ai instalat, dai din nou dublu-click pe `porneste.bat`.
2. **Se deschide pagina aplicației în browserul tău implicit.** În consolă vezi „Aplicația rulează doar pe acest calculator, la adresa http://127.0.0.1:…” și „Pagina s-a deschis în browserul tău. Lasă această fereastră deschisă cât folosești aplicația.” Adresa `http://127.0.0.1:<număr>` înseamnă un server care rulează doar pe calculatorul tău, nu pe internet. **Lasă fereastra neagră deschisă** cât folosești aplicația.
3. **Apasă „Pornește analiza”.** (Dacă vrei alt prag pentru „achiziție mare”, îl schimbi înainte, în același ecran.) Se deschide o fereastră Edge separată, cu profilul programului, pe pagina de comenzi eMAG. **Te loghezi tu**: parola și codul 2FA le scrii tu în fereastra aceea; programul nu le vede, nu le tastează și nu le salvează. Dacă ești deja logat de la o rulare anterioară, pasul acesta se sare singur. Programul așteaptă până la 10 minute să te loghezi.
4. **Urmărești progresul pe pași** în aceeași pagină: **Conectare, Comenzi, Retururi, Calcul**. Durează aproximativ 2–3 minute pentru ~400 de comenzi (măsurat o singură dată, pe un cont real; depinde de conexiune și de numărul de comenzi). Butonul **„Oprește”** anulează analiza. Cât rulează, **nu închide și nu reîncărca pagina** și nu închide nici fereastra Edge a programului, nici fereastra neagră: analiza s-ar opri.
5. **Raportul apare în aceeași pagină.** Fișierele rulării (`raport.html`, `produse.csv`, `istoric_preturi.csv`, `rezumat.txt`) sunt în folderul `iesiri\<data>_<ora>\`; pagina le poate descărca cu „Descarcă fișierele”. „Rulează din nou” pornește o analiză nouă.
6. **Rulări anterioare:** lista din pagină arată rulările din `iesiri/`; deschizi una ca să vezi din nou raportul, fără să mai intri în eMAG.
7. **Fără cont:** butonul **„Încearcă cu date inventate”** rulează aceeași analiză pe comenzi făcute de noi, fără login.
8. **Sesiunea salvată:** pagina arată dacă sesiunea eMAG e salvată pe calculator. „Șterge sesiunea salvată” o șterge după ce scrii `DA` în câmpul de confirmare.
9. **Cum închizi:** apeși **„Închide aplicația”** din ecranul de start sau `Ctrl+C` în fereastra neagră. Dacă uiți aplicația deschisă, se oprește singură după 30 de minute fără nicio cerere (nu și cât rulează o analiză). Fereastra neagră spune cum s-a oprit („Aplicația a fost închisă din pagină.” și „Aplicația s-a oprit. Rezultatele rămân în folderul iesiri.”); apoi apeși o tastă și se închide.

**Dacă pagina nu se deschide singură:** fereastra neagră scrie „Nu am putut deschide browserul automat” și adresa de deschis (conține cheia de acces a aplicației; nu o da nimănui). Lipește-o în browser.

**Dacă pagina spune „Pagina nu mai are cheia de acces”:** ai reîncărcat-o sau ai deschis-o fără adresa pregătită de program. Închide fila și dă din nou dublu-click pe `porneste.bat`: se deschide o pagină nouă, cu o cheie nouă. Ce era deja terminat rămâne în `iesiri/`.

## 3. Varianta cu pași separați

Pentru cine vrea să vadă fiecare pas sau să ruleze din terminal. Fiecare lansator se pornește cu dublu-click, din folderul programului.

### 3.1. `instaleaza.bat` (o singură dată)

Caută Python 3.10+, creează mediul izolat `.venv` **în folderul programului** și instalează în el pachetele din `requirements.txt`, apoi verifică dacă se pot încărca. Nu scrie în Registry, în AppData sau în folderul tău personal. Ai nevoie de internet; durează 1–3 minute. Se termină cu „Instalarea s-a terminat cu succes” și îți spune pasul următor. Dacă `.venv` există deja, îl reutilizează.

### 3.2. `login.bat`

1. Se deschide o fereastră Edge, pe pagina de comenzi eMAG. În consolă vezi: „Loghează-te în fereastra de browser care s-a deschis (parola și codul 2FA le introduci tu). Aștept până la 10 minute.”
2. **Te loghezi tu**, cu parola și codul 2FA. Programul nu le tastează.
3. Când programul vede că ești logat, **fereastra Edge se închide singură** și consola spune „Gata: sesiunea ta eMAG e salvată pe acest calculator, în folderul .profil_browser.”

Folderul `.profil_browser/` conține sesiunea ta: **tratează-l ca pe o parolă** și nu-l trimite nimănui.

### 3.3. `ruleaza.bat`

Citește comenzile și retururile din contul tău, calculează și deschide raportul în browser la final. Dacă sesiunea e încă activă, nu mai ai de făcut login. Durează aproximativ 2–3 minute pentru ~400 de comenzi (măsurat o singură dată; depinde de conexiune). **Nu închide fereastra** cât rulează.

Opțiunile se scriu după nume, într-un terminal sau în Command Prompt: `ruleaza.bat --prag 1000` schimbă pragul pentru „achiziție mare” la 1000 Lei pe bucată (implicit 500). Lista completă e la [Pentru programatori](#pentru-programatori).

### 3.4. Cum citești raportul

Raportul (`raport.html`) e un singur fișier care se deschide fără internet. De sus în jos:

- **Cât ai cheltuit**: cifra mare, adică produsele livrate sau ridicate, fără cele returnate sau anulate.
- **De la comandat la păstrat**: lanțul „comandat − anulat − returnat − în curs = păstrat”.
- **Pe ce s-au dus banii**, **pe ani**, **vânzători**, **produse cu cea mai mare valoare** și **achiziții peste prag**.
- **Prețuri la același produs**: apare doar dacă ai cumpărat același model în cel puțin două comenzi diferite; arată „mai scump” sau „mai ieftin” cu X Lei față de data trecută. Prețul include promoții, e dinainte de vouchere și vânzătorii pot diferi: e o schimbare de preț, nu o pierdere sau un câștig.
- **Rămase în afara calculului** și **cifre de control**: asigurări plătite fără livrare, vouchere, transport, taxe.
- **Avertismente**: grupe care se deschid; fiecare spune ce înseamnă, dacă afectează cifrele și ce poți face, cu linkuri către comenzile de pe eMAG (se deschid doar când apeși pe ele).
- **Nota de metodă**: cum se calculează fiecare cifră.

Dacă deschizi `produse.csv` în Excel și caracterele arată ciudat, folosește **Date → From Text/CSV** și alege UTF-8; separatorul este `;`.

### 3.5. Unde sunt fișierele

```
folderul-programului\
├─ iesiri\<data>_<ora>\     o rulare (cu _demo la final dacă e demonstrația)
│    ├─ raport.html         raportul, un singur fișier
│    ├─ produse.csv         câte un rând pe produs
│    ├─ istoric_preturi.csv prețuri la același produs
│    ├─ rezumat.txt         cifrele principale, în text
│    ├─ analiza.json        rezultatul complet (din el se desenează raportul)
│    ├─ comenzi.json, retururi.json   ce a citit programul din cont
│    └─ run_info.json       ce s-a rulat (ora, prag, numere)
├─ logs\<data>_<ora>.log    jurnalul sesiunii
└─ .profil_browser\         sesiunea eMAG (ca o parolă)
```

`comenzi.json`, `retururi.json`, `analiza.json` și rapoartele conțin istoricul tău de cumpărături. **Nu le trimite nimănui, nu le atașa în Issues, nu le pune pe GitHub sau în cloud.**

### 3.6. `demo.bat`

Același raport ca la o rulare reală, dar cu comenzi **inventate**: fără login, fără cont, fără nicio citire din eMAG. Bun ca să vezi cum arată programul înainte să-l folosești. Creează un folder `iesiri\<data>_<ora>_demo\` și rescrie fișierul de date demonstrative al site-ului explicativ.

### 3.7. `deschide_interfata.bat`

Deschide site-ul explicativ (`interfata\index.html`) în browser: ce face programul, ce citește și ce nu, cum se calculează cifrele, plus un raport demonstrativ. E o pagină statică, fără server și fără cereri de rețea; nu poate porni analiza (pentru asta e `porneste.bat`).

### 3.8. `sterge_sesiunea.bat`

Șterge folderul `.profil_browser/`, deci sesiunea eMAG salvată. Programul îți cere să scrii exact `DA` (cu majuscule); orice altceva anulează. Rapoartele din `iesiri/` nu se șterg. Data viitoare te loghezi din nou. Închide întâi fereastra Edge a programului, dacă e deschisă.

## Actualizare

Cu ZIP:

1. Descarcă ZIP-ul nou și extrage-l într-un **folder nou** (de exemplu `C:\cheltuieli-emag-nou`).
2. Din folderul vechi copiază în cel nou doar ce vrei să păstrezi: folderul `iesiri\` (rapoartele tale) și, dacă ai creat-o, `config\categorii.personal.json`.
3. În folderul nou dă dublu-click pe `porneste.bat` și te loghezi din nou.
4. Apoi curăță folderul vechi: urmează pașii de la [Dezinstalare completă](#dezinstalare-completă), începând cu `sterge_sesiunea.bat` **din folderul vechi**, înainte să-l ștergi.

Cu git: `git pull`, apoi `instaleaza.bat` dacă `requirements.txt` s-a schimbat.

## Dezinstalare completă

Programul nu scrie în Registry, în AppData sau în folderul tău personal, deci nu are ce să dezinstalezi în afara folderului lui. Ordinea contează:

1. **Închide** fereastra Edge a programului și aplicația (`Închide aplicația`).
2. **Rulează `sterge_sesiunea.bat`** (scrii `DA`) **înainte** să ștergi folderul. Ștergerea o face programul, definitiv (nu prin Coșul de reciclare), îți spune dacă ceva n-a putut fi șters (de obicei Edge încă deschis) și curăță și profilul, dacă ai mutat sesiunea în alt loc cu `EMAG_PROFILE_DIR`: un profil din afara folderului ar rămâne altfel pe disc.
3. Dacă vrei să păstrezi rapoartele, copiază-le dintr-un loc în care nu se sincronizează cu un cloud.
4. **Șterge folderul programului** (de exemplu `C:\cheltuieli-emag`). Dacă vrei doar să cureți datele, șterge în Explorer folderele `iesiri` și `logs` din el.
5. **Golește Coșul de reciclare**: fișierele șterse rămân acolo și pot fi restaurate.
6. **Sesiunea de pe eMAG nu se închide de pe calculatorul tău:** `sterge_sesiunea.bat` doar șterge fișierele locale. Dacă vrei să închizi o sesiune veche, schimbă parola contului eMAG.
7. Opțional: Edge, pornit de program, își scrie în `%TEMP%` fișiere proprii (două `.tmp` șterse la închidere și `cv_debug.log`, care rămâne). Le poți șterge din `%TEMP%` (tastezi `%TEMP%` în bara Explorer). Python rămâne instalat; îl scoți din **Setări → Aplicații** dacă nu-l mai folosești.

## Probleme frecvente

| Ce vezi | Cauza | Ce faci |
|---|---|---|
| „EROARE: nu am găsit Python 3.10 sau mai nou” sau „python nu este recunoscut ca o comandă internă sau externă” | Python lipsește, e prea vechi sau nu a fost bifat „Add python.exe to PATH” | Instalează Python de pe python.org cu bifa „Add python.exe to PATH”. Închide fereastra și rulează din nou. Dacă la comanda `python` se deschide Microsoft Store, e doar un alias Windows, nu Python-ul real: instalează-l de pe python.org. |
| „Windows a protejat computerul” sau „Nu putem verifica cine a creat acest fișier” | Fișier descărcat de pe internet, nesemnat | Vezi [Avertismente Windows](#avertismente-windows-la-prima-rulare): verifici conținutul în Notepad, apoi **Mai multe informații → Rulează oricum**. |
| Antivirusul blochează sau șterge un `.bat` sau fișiere din `.venv` | Un program care pornește un browser și îl controlează seamănă cu ce fac unele programe periculoase | Nu dezactiva antivirusul. Verifică fișierul (e text) și compară-l cu depozitul. Dacă ai dubii, nu rula. |
| „nu găsesc fișierele programului lângă acest script” | Ai dat dublu-click pe `.bat` din interiorul ZIP-ului | Clic dreapta pe ZIP → **Extract All**, apoi rulează din folderul extras. |
| „Programul nu este instalat încă. Rulează mai întâi instaleaza.bat, apoi încearcă din nou.” | Lipsește mediul `.venv` (nu ai rulat `instaleaza.bat` sau ai copiat folderul fără `.venv`) | Rulează `instaleaza.bat` (sau `porneste.bat`, care îl pornește singur) în folderul în care vrei să folosești programul. După ce muți un folder, rulează din nou `instaleaza.bat`; dacă tot nu merge, șterge folderul `.venv` și repetă. |
| „calea acestui folder e prea lungă” | Calea întreagă are peste 190 de caractere | Mută folderul în `C:\cheltuieli-emag` și rulează din nou. |
| Instalarea pachetelor eșuează | Fără internet, firewall sau antivirus care blochează pypi.org, sau o versiune de Python foarte nouă, pentru care pachetele nu au încă fișiere gata făcute | Verifică internetul, apoi rulează din nou `instaleaza.bat`. Programul a fost testat cu Python 3.13 și 3.14. |
| Eroare cu textul „Chromium distribution 'msedge' is not found” | Edge nu e instalat | Folosește Chrome: vezi pașii de sub tabel. |
| „nu te-ai logat în timpul alocat; rulează din nou scriptul” | Programul așteaptă 10 minute să te loghezi; login-ul (parolă, cod 2FA) a durat mai mult sau fereastra a fost închisă | Rulează din nou și termină login-ul în fereastra Edge. Pentru mai mult timp, mărește `EMAG_LOGIN_WAIT_SECONDS` (pașii de sub tabel). |
| „redirecționat la login pentru …” sau „nicio comandă pe prima pagină a listei (sesiune expirată sau pagină schimbată?)” | Sesiunea eMAG a expirat | Rulează din nou și loghează-te când se deschide fereastra Edge. Dacă se repetă imediat după un login reușit, eMAG poate să-și fi schimbat paginile: deschide un Issue fără date personale. |
| Fereastra Edge a programului nu pornește sau eroarea spune că profilul e în uz | Mai rulează o instanță a programului sau a ferestrei lui | Închide ferestrele Edge deschise de program și rulează o singură dată. |
| Cifrele diferă de ce văd pe eMAG | Prețuri dinainte de vouchere, anulate și returnate scăzute, „în curs” scăzut, plăți reale diferite | Vezi [întrebarea din README](../README.md#întrebări-frecvente). Deschide comanda din link și compară-o cu raportul. |
| Calea folderului are caractere speciale | `&`, `%`, `!`, `^` în cale pot încurca fișierele `.bat` | Mută folderul într-o cale simplă, de exemplu `C:\cheltuieli-emag`. |

**Cum folosești Chrome în loc de Edge** (la fel pentru `porneste.bat`, `login.bat`, `ruleaza.bat`):

1. Apasă tasta Windows, scrie `cmd` și deschide **Command Prompt**.
2. Scrie `cd /d C:\cheltuieli-emag` (folderul tău) și Enter.
3. Scrie `set EMAG_BROWSER_CHANNEL=chrome` și Enter.
4. În **aceeași fereastră** scrie `porneste.bat` (sau `login.bat`, apoi `ruleaza.bat`) și Enter.

Variabila se pierde când închizi fereastra; la fiecare folosire repeți pașii 1–4. Folosește același browser la login și la rulare; dacă schimbi browserul, rulează întâi `sterge_sesiunea.bat` și te loghezi din nou (recomandare prudentă, neverificată).

**Cum mărești timpul de login:** aceiași pași, dar la pasul 3 scrii, de exemplu, `set EMAG_LOGIN_WAIT_SECONDS=1800` (30 de minute).

## Pentru programatori

Instalare manuală, fără `.bat`, în folderul proiectului (PowerShell sau Command Prompt):

```
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install --disable-pip-version-check --no-cache-dir --only-binary=:all: -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest
```

`requirements.txt` conține doar ce rulează programul; `requirements-dev.txt` adaugă `pytest`. Versiunile sunt fixate, la cele mai mici fără vulnerabilități cunoscute la verificarea cu `pip-audit`; `siguranta.yml` le verifică săptămânal, iar Dependabot propune actualizările. Nu e nevoie de `playwright install`: se folosește Edge sau Chrome instalat. Testele de browser pornesc Edge sau Chrome fără fereastră și se sar dacă nu e instalat niciunul.

Opțiuni din linia de comandă (`.venv\Scripts\python.exe ruleaza.py …`):

| Opțiune | Ce face |
|---|---|
| *(fără opțiuni)* | rulare completă |
| `--aplicatie` | pornește aplicația locală (server pe `127.0.0.1`) și deschide pagina; `--fara-browser` nu deschide browserul |
| `--prag 1000` | alt prag pentru „achiziție mare”, în Lei pe bucată (implicit 500) |
| `--limita-comenzi 20` | citește doar primele 20 de comenzi, pentru un test rapid |
| `--din-cache iesiri\<rulare>` | refă raportul din `comenzi.json` și `retururi.json`, fără browser |
| `--doar-login` | doar te loghezi și salvezi sesiunea |
| `--demo` | comenzi inventate, fără browser și fără login |
| `--sterge-sesiunea` | șterge sesiunea salvată, după ce scrii `DA` (cu `--fara-confirmare`, fără întrebare) |
| `--deschide` | deschide raportul la final |
| `--iesire <folder>` | folderul în care se creează rularea |

Variabile de mediu (toate opționale; singurele pe care le citește programul):

| Variabilă | Implicit | Rost |
|---|---|---|
| `EMAG_BROWSER_CHANNEL` | `msedge` | browserul instalat (alternativ `chrome`) |
| `EMAG_PROFILE_DIR` | `<proiect>\.profil_browser` | folderul profilului cu sesiunea; **`--sterge-sesiunea` îl șterge**, deci trebuie să fie un folder dedicat programului, nu profilul tău real de browser |
| `EMAG_FETCH_CONCURRENCY` | `3` | câte pagini de detalii se cer simultan |
| `EMAG_LOGIN_WAIT_SECONDS` | `600` | cât așteaptă programul să te loghezi manual |
| `EMAG_APP_IDLE_MINUTES` | `30` | după câte minute fără nicio cerere se oprește singură aplicația locală (între 1 și 1440; nu se oprește cât rulează o analiză) |

**Mac și Linux (netestat).** Codul e portabil, dar `.bat`-urile sunt doar pentru Windows și nimic nu a fost încercat acolo; pachetele fixate au fost verificate doar pentru Windows. Încercare:

```
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
EMAG_BROWSER_CHANNEL=chrome .venv/bin/python ruleaza.py --aplicatie
```

## Ce a fost testat și ce nu

**Testat** (de autor, pe Windows 11):

- Testele automate, pe Python 3.13 și 3.14 (Edge pentru testele de browser).
- `instaleaza.bat` de la zero, într-o copie cu cale cu spații, diacritice și paranteze, apoi a doua rulare (reutilizează `.venv`); `demo.bat` de două ori; `sterge_sesiunea.bat` pe profiluri de probă (anulare, `DA`, folder care nu e profil); mesajul pentru calea prea lungă; mesajul pentru lipsa lui `.venv`.
- Parserele, pe pagini inventate și, manual, pe pagini reale.

**Netestat sau nevalidat:**

- Fluxul complet cu login și citire, pe mai multe conturi reale diferite.
- Windows 10, Python 3.10–3.12, Chrome în locul Edge, Mac și Linux.
- Comportamentul exact al SmartScreen și al antivirusurilor pe fiecare versiune.
- Pasul „Deblocare” din proprietățile ZIP-ului și caracterele `&`, `%`, `!`, `^` în calea folderului.
- Rularea efectivă pe GitHub a verificărilor automate, CodeQL și Dependabot.

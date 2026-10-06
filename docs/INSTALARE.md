# Instalare și folosire, pas cu pas

Ghid pentru cineva care nu a instalat niciodată un program de acest fel, pe **Windows, macOS sau Linux**. Nu trebuie să instalezi Python: la prima pornire programul își aduce singur, în folderul lui, tot ce îi trebuie (cam un minut, cu internet).

**Cuprins:** [Ce îți trebuie](#ce-îți-trebuie) · [1. Descarcă și extrage](#1-descarcă-și-extrage) · [2. Pornește](#2-pornește) · [3. Folosește aplicația](#3-folosește-aplicația) · [4. Varianta cu pași separați (Windows)](#4-varianta-cu-pași-separați-windows) · [Ce se descarcă la prima pornire](#ce-se-descarcă-la-prima-pornire) · [Actualizare](#actualizare) · [Dezinstalare completă](#dezinstalare-completă) · [Probleme frecvente](#probleme-frecvente) · [Pentru programatori](#pentru-programatori) · [Ce a fost testat și ce nu](#ce-a-fost-testat-și-ce-nu)

> [!WARNING]
> Proiect independent, **neafiliat cu eMAG**. Partea cu browserul (login și citirea paginilor eMAG) a rulat cap-la-cap pe **un singur cont real**, pe Windows; eMAG își poate schimba paginile, iar atunci programul poate da erori sau cifre greșite. Compară totalurile cu pagina „Comenzile mele” de pe eMAG. Accesul automat poate fi contrar termenilor eMAG: îl folosești pe răspunderea ta, doar pe contul tău.

## Ce îți trebuie

| Ce | Detalii |
|---|---|
| **Windows 10/11, macOS sau Linux** | Procesor x64 sau ARM (Apple Silicon). Pe Linux: o distribuție cu interfață grafică (fereastra de login trebuie să se vadă). |
| **Un browser** | Microsoft Edge (vine cu Windows) sau Google Chrome. Dacă nu ai niciunul, programul descarcă o singură dată Chromium (~150 MB), doar pentru el. |
| **Internet** | La prima pornire (programul își descarcă uneltele) și când citește contul tău. |
| **Spațiu pe disc** | În jur de 300 MB pentru folderele `.uv` și `.venv` (plus ~150 MB dacă trebuie descărcat Chromium), plus rapoartele tale. |
| **Cont eMAG** | Doar pentru analiza reală. Demonstrația cu date inventate nu cere cont. |

**Nu ai nevoie** de Python instalat, de drepturi de administrator sau de alte programe.

## 1. Descarcă și extrage

1. Pe pagina depozitului ([github.com/poprobert0412/cheltuieli-emag](https://github.com/poprobert0412/cheltuieli-emag)) intră la **Releases** (în dreapta) și descarcă arhiva `cheltuieli-emag-v….zip` a ultimei versiuni. (Merge și butonul verde **Code → Download ZIP**, care dă ultima variantă din cod.)
2. Extrage arhiva într-un folder simplu și scurt:
   - **Windows:** clic dreapta pe fișierul descărcat → **Extract All…** (Extrage tot) → de exemplu `C:\cheltuieli-emag` → **Extract**.
   - **macOS:** Safari o extrage de obicei singur în **Descărcări**; altfel dublu-clic pe ZIP. Mută folderul extras în folderul tău personal (de exemplu `~/cheltuieli-emag`).
   - **Linux:** `unzip cheltuieli-emag-v*.zip` în folderul tău personal.
3. Deschide folderul extras. Trebuie să vezi `porneste.bat`, `porneste.command`, `porneste.sh`, `ruleaza.py` și folderul `interfata`.

Reguli pentru folder:

- **Extrage, nu rula din ZIP.** Un lansator pornit din fereastra ZIP-ului nu găsește celelalte fișiere și spune „nu găsesc fișierele programului lângă acest script”.
- **Nu într-un folder sincronizat cu un cloud** (OneDrive pe Windows, iCloud Drive pe Mac: Desktop și Documente pot fi sincronizate). Rapoartele din `iesiri/` și sesiunea eMAG din `.profil_browser/` ar ajunge în cloud.
- **Windows, cale scurtă:** pregătirea refuză un folder a cărui cale are peste 190 de caractere (Windows nu poate porni anumite fișiere cu căi lungi) și te roagă să muți folderul în `C:\cheltuieli-emag`.
- **Caractere speciale:** spații și diacritice în cale merg. Caracterele `&`, `%`, `!` și `^` **nu au fost încercate**; o cale simplă evită problemele.

## 2. Pornește

### Windows

**Dublu-clic pe `porneste.bat`.** Se deschide o fereastră neagră (consola). La prima pornire vezi „Prima pornire: descarc uv…” și „Pregătesc Python 3.13 și pachetele programului…”; durează cam un minut. De la a doua pornire, pregătirea ține o secundă.

Fișierele `.bat` descărcate de pe internet nu sunt semnate digital, deci Windows poate arăta un avertisment (SmartScreen: „Windows a protejat computerul” sau „Nu putem verifica cine a creat acest fișier”). Nu înseamnă că fișierul e periculos și nu înseamnă că e sigur: înseamnă doar că Windows nu-l cunoaște. Cum verifici ce rulezi:

1. Clic dreapta pe `porneste.bat` (și pe `instaleaza.bat`, pe care îl cheamă) → **Edit** (sau **Open with → Notepad**). Comentariile (rândurile cu `rem`) spun ce face fiecare pas.
2. Dacă ai încredere, apasă **Mai multe informații** (More info), apoi **Rulează oricum** (Run anyway).

Ca să nu mai apară avertismentul pentru fiecare fișier, poți face **înainte** de extragere: clic dreapta pe ZIP → **Proprietăți** → bifează **Deblocare** (Unblock) → OK. (Pas neverificat pe fiecare versiune de Windows.) Dacă antivirusul blochează un fișier, **nu-l dezactiva**: verifică întâi fișierul și, dacă ai dubii, nu rula nimic.

### macOS

**Dublu-clic pe `porneste.command`.** Se deschide aplicația Terminal și pornește programul. Prima dată, macOS îl oprește, fiindcă scriptul nu e semnat de un dezvoltator înregistrat la Apple:

1. Apare mesajul că „porneste.command” nu poate fi deschis. Apasă **Gata** (Done), nu **Mută la Coș**.
2. Deschide **Setări de sistem → Confidențialitate și securitate**, coboară la mesajul despre „porneste.command” și apasă **Deschide oricum** (Open Anyway), apoi confirmă cu parola sau cu Touch ID. (Pe macOS 14 și mai vechi: Control-clic pe fișier → **Deschide** → **Deschide**.)
3. De la a doua pornire, dublu-clicul merge direct.

Alternativă fără aprobări: în Terminal, `cd ~/cheltuieli-emag` (folderul tău) și `sh porneste.command`. Înainte să aprobi, poți citi scriptul: Control-clic → **Deschide cu → TextEdit**.

### Linux

Din Terminal, în folderul programului: `./porneste.sh` (dacă primești „Permission denied”: `sh porneste.sh`). Ai nevoie de `curl` (sau `wget`) și `tar`, care există pe aproape orice distribuție. Scriptul nu cere niciodată `sudo`.

**Browserul pe Linux:** programul folosește Google Chrome sau Microsoft Edge, dacă sunt instalate. Dacă nu, descarcă o singură dată Chromium; acesta are nevoie de câteva biblioteci de sistem. Dacă lipsesc, scriptul îți spune exact ce să faci: fie instalezi [Google Chrome](https://www.google.com/chrome/), fie (pe Ubuntu și Debian) rulezi o dată comanda afișată, `sudo "…/.venv/bin/python" -m playwright install-deps chromium`. Fără browser, demonstrația merge, dar citirea contului nu.

## 3. Folosește aplicația

1. **Se deschide pagina aplicației în browserul tău implicit.** În consolă vezi „Aplicația rulează doar pe acest calculator, la adresa http://127.0.0.1:…”. Adresa `http://127.0.0.1:<număr>` înseamnă un server care rulează doar pe calculatorul tău, nu pe internet. **Lasă fereastra consolei deschisă** cât folosești aplicația.
2. **Apasă „Pornește analiza”.** (Dacă vrei alt prag pentru „achiziție mare”, îl schimbi înainte, în același ecran.) Se deschide o fereastră de browser separată, cu profilul programului, pe pagina de comenzi eMAG. **Te loghezi tu**: parola și codul 2FA le scrii tu în fereastra aceea; programul nu le vede, nu le tastează și nu le salvează. Dacă ești deja logat de la o rulare anterioară, pasul se sare singur. Programul așteaptă până la 10 minute.
3. **Urmărești progresul pe pași:** **Conectare, Comenzi, Retururi, Calcul**. Durează cam 2–3 minute pentru ~400 de comenzi (măsurat pe un cont real; depinde de conexiune). Butonul **„Oprește”** anulează analiza. Cât rulează, nu închide pagina, fereastra browserului programului sau consola.
4. **Raportul apare în aceeași pagină.** Fișierele rulării sunt în `iesiri/<data>_<ora>/`; pagina le poate descărca. Numerele de comandă și numele produselor sunt linkuri spre comanda ta de pe eMAG (se deschid doar când apeși pe ele, în browserul tău, unde trebuie să fii logat în eMAG).
5. **Rulări anterioare:** lista din pagină arată rulările din `iesiri/`; deschizi una ca s-o vezi din nou, fără să mai intri în eMAG.
6. **Fără cont:** butonul **„Încearcă cu date inventate”** rulează aceeași analiză pe comenzi făcute de noi, fără login.
7. **Sesiunea salvată:** pagina arată dacă sesiunea eMAG e salvată; „Șterge sesiunea salvată” o șterge după ce scrii `DA`.
8. **Cum închizi:** **„Închide aplicația”** din ecranul de start sau `Ctrl+C` în consolă. Dacă o uiți deschisă, se oprește singură după 30 de minute fără nicio cerere (nu și cât rulează o analiză).
9. **Versiunea:** sub titlu vezi versiunea pe care o ai; când apare una nouă, pagina arată „Versiune nouă” și butonul „Actualizează acum” (vezi [Actualizare](#actualizare)).

**Dacă pagina nu se deschide singură:** consola scrie „Nu am putut deschide browserul automat” și adresa de deschis (conține cheia de acces a aplicației; nu o da nimănui). Lipește-o în browser.

**Dacă pagina spune „Pagina nu mai are cheia de acces”:** ai reîncărcat-o. Închide fila și pornește din nou lansatorul: se deschide o pagină nouă, cu o cheie nouă. Ce era terminat rămâne în `iesiri/`.

### Cum citești raportul

Raportul (`raport.html`) e un singur fișier care se deschide fără internet. De sus în jos: **cât ai cheltuit** (cifra mare: banii plătiți efectiv, după reduceri și vouchere, cu transportul și taxele, minus banii primiți înapoi la retururi), **lanțul de la comandat la plătit**, **pe ce s-au dus banii** (categorii), **pe ani**, **vânzători**, **produsele cu cea mai mare valoare**, **achiziții peste prag**, **prețuri la același produs**, **rămase în afara calculului**, **cifre de control** și **avertismente** (grupe care se deschid, fiecare cu explicația, efectul asupra cifrelor și linkuri spre comenzi). Cum se calculează fiecare cifră: în [README](CALCUL.md) și în nota de metodă de la finalul raportului.

Dacă deschizi `produse.csv` în Excel și caracterele arată ciudat, folosește **Date → From Text/CSV** și alege UTF-8; separatorul este `;`.

### Unde sunt fișierele

```
folderul-programului/
├─ iesiri/<data>_<ora>/       o rulare (cu _demo la final dacă e demonstrația)
│    ├─ raport.html           raportul, un singur fișier
│    ├─ produse.csv           câte un rând pe produs
│    ├─ istoric_preturi.csv   prețuri la același produs
│    ├─ rezumat.txt           cifrele principale, în text
│    ├─ analiza.json          rezultatul complet (din el se desenează raportul)
│    ├─ comenzi.json, retururi.json   ce a citit programul din cont
│    └─ run_info.json         ce s-a rulat (versiunea programului, ora, prag, numere)
├─ logs/<data>_<ora>.log      jurnalul sesiunii
├─ .profil_browser/           sesiunea eMAG (ca o parolă)
├─ .uv/                       uneltele descărcate la prima pornire (uv, Python, eventual Chromium)
├─ .venv/                     pachetele programului
└─ .actualizare/              doar cât ține o actualizare (arhiva descărcată, versiunea nouă, copiile
                              fișierelor înlocuite, jurnalul); după, rămâne doar fișierul gol lacat
                              (o descărcare oprită la mijloc se șterge la o actualizare pornită
                              după cel puțin o oră)
```

`comenzi.json`, `retururi.json`, `analiza.json` și rapoartele conțin istoricul tău de cumpărături. **Nu le trimite nimănui, nu le atașa în Issues, nu le pune pe GitHub sau în cloud.**

### Cele două pagini din `interfata/`

Sunt două pagini, ambele în folderul `interfata/`:

**Aplicația locală (`aplicatie.html`)** e calea obișnuită: o pornești cu dublu-click pe `porneste.bat` (sau, din terminal, cu `python ruleaza.py --aplicatie`). Butonul **„Pornește analiza”** face tot: deschide fereastra de login, citește comenzile și retururile, calculează și arată raportul în aceeași pagină, cu progres pe pași. Lista **„Rulări anterioare”** (din `iesiri/`) înlocuiește tragerea de fișiere, iar **„Încearcă cu date inventate”** rulează demonstrația fără login. Sub titlu vezi versiunea programului și, când apare una nouă, butonul **„Actualizează acum”** ([Actualizări](INSTALARE.md#actualizare)). Pagina vorbește doar cu un server pornit local de program, pe `127.0.0.1` (vezi [SECURITY.md](../SECURITY.md)); când închizi aplicația, serverul se oprește.

**Site-ul explicativ (`index.html`)** se deschide cu dublu-click pe `deschide_interfata.bat` (sau direct în browser, din folder), fără server. Explică ce face programul, ce citește și ce nu, cum se calculează fiecare cifră și arată un raport demonstrativ cu date inventate. Poate vedea și un `analiza.json` din `iesiri\<data>_<ora>\`: fișierul se citește local, în browser, și nu se trimite nicăieri. Pagina nu face cereri de rețea (o politică de conținut din `index.html` le blochează în browser) și nu poate porni programul; numerele de comandă sunt linkuri către eMAG care se deschid doar când apeși pe ele, în browserul tău.

Fișierele: `aplicatie.html` și `index.html` cu `assets/` (stiluri și scripturi), `assets/dashboard.css` și `assets/dashboard.js` (componenta raportului, aceeași sursă ca raportul generat) și `assets/demo-data.js` (date inventate, regenerate cu `ruleaza.py --demo`).

## 4. Varianta cu pași separați (Windows)

Pentru cine vrea să vadă fiecare pas. Fiecare lansator se pornește cu dublu-clic, din folderul programului. (Pe macOS și Linux, aceleași opțiuni se dau lansatorului din Terminal, de exemplu `./porneste.sh --demo`; lista e la [Pentru programatori](#pentru-programatori).)

- **`instaleaza.bat`** – doar pregătirea (uv, Python, pachete, browser), fără să pornească programul. `porneste.bat` o face oricum, singur, la fiecare pornire.
- **`login.bat`** – se deschide fereastra Edge pe pagina de comenzi; te loghezi tu; când programul vede că ești logat, fereastra se închide și sesiunea rămâne în `.profil_browser/`.
- **`ruleaza.bat`** – citește contul, calculează și deschide raportul la final. Opțiunile se scriu după nume, de exemplu `ruleaza.bat --prag 1000`.
- **`demo.bat`** – același raport, cu comenzi **inventate**: fără login, fără cont.
- **`deschide_interfata.bat`** – site-ul explicativ (`interfata/index.html`): ce face programul, ce citește și ce nu, plus un raport demonstrativ. Pagină statică, fără server.
- **`sterge_sesiunea.bat`** – șterge `.profil_browser/` după ce scrii exact `DA`. Rapoartele din `iesiri/` nu se șterg. Închide întâi fereastra browserului programului.

## Ce se descarcă la prima pornire

Totul din folderul programului, nimic în altă parte (în afara fișierelor temporare pe care browserul le scrie singur):

| Ce | De unde | Cum e verificat |
|---|---|---|
| **uv** (instalatorul de Python, ~18 MB) | `github.com/astral-sh/uv/releases`, exact versiunea din `instalare/versiuni.txt` | Lansatorul calculează amprenta SHA-256 a arhivei și o folosește doar dacă e identică cu cea scrisă în `instalare/versiuni.txt`; după o dezarhivare reușită, șterge arhivele uv din `.uv/descarcari/`. O arhivă rămasă de la o pornire oprită înainte de dezarhivare (`.uv/descarcari/uv-<versiune>-<sistem>.zip`, pe macOS și Linux `.tar.gz`, cu versiunea în nume) se folosește dacă are amprenta corectă; altfel se șterge și se descarcă încă o dată, iar una proaspăt descărcată și greșită se șterge și pregătirea se oprește. |
| **Python 3.13** | adus de uv (distribuțiile „python-build-standalone”) | uv verifică amprenta fiecărei descărcări. |
| **Pachetele** din `requirements.txt` | pypi.org | Versiuni fixate, doar pachete gata făcute (`--only-binary`): niciun cod de instalare nu rulează pe calculatorul tău. |
| **Chromium** (doar dacă nu ai Edge sau Chrome, ~150 MB) | serverele Playwright | Prin Playwright, pachetul fixat. |

## Actualizare

Programul nu se actualizează niciodată fără să apeși tu. Ai patru căi; prima e cea obișnuită.

### Din aplicație

1. Pornește aplicația ca de obicei (`porneste.bat`, `porneste.command` sau `./porneste.sh`). La pornire, ea întreabă GitHub, în fundal, care e ultima versiune publicată (o singură cerere, fără nimic despre tine sau comenzile tale; detalii în [SECURITY.md](../SECURITY.md#ce-face-programul-în-rețea)). Versiunea ta se vede mereu în pagină.
2. Dacă există una nouă, apare **„Versiune nouă: X (ai Y)”**, cu „Ce e nou”. Apasă **„Actualizează acum”**. Cât rulează o analiză, butonul e dezactivat; cât rulează actualizarea, „Pornește analiza” e dezactivat.
3. Pagina arată pașii: descarc, verific amprenta, instalez, gata. Apoi aplicația se oprește, iar lansatorul pornește singur versiunea nouă (cu pachetele noi, dacă s-au schimbat) și deschide o pagină nouă. Fila veche poate fi închisă. Dacă nu se deschide nimic (de exemplu ai pornit aplicația direct cu `ruleaza.py --aplicatie`, fără lansator), pornește-o din nou cu lansatorul.

### Din terminal

`porneste.bat --actualizeaza` (Windows), `./porneste.sh --actualizeaza` (Linux), `sh porneste.command --actualizeaza` (macOS) sau direct `.venv/bin/python ruleaza.py --actualizeaza` (pe Windows `.venv\Scripts\python.exe`). Programul arată versiunea ta, pe cea nouă și ce e nou, și cere să scrii `DA`. La final scrie „Actualizat la X.Y.Z. Pornește din nou programul.”: pornește-l din nou ca de obicei.

### Ce se păstrează

Actualizarea înlocuiește doar fișierele programului (lista lor e `instalare/fisiere.txt`, în arhiva fiecărei versiuni) și șterge doar fișierele care erau în lista versiunii vechi și nu mai sunt în cea nouă. Nu atinge niciodată: `iesiri/` (rapoartele), `logs/` (jurnalele), `.profil_browser/` (sesiunea eMAG; și folderul din `EMAG_PROFILE_DIR`), `config/categorii.personal.json` (regulile tale), `.uv/` și `.venv/` (uneltele), `.git/` și orice fișier pus de tine pe o cale pe care programul nu o folosește. Atenție: un fișier al tău aflat chiar pe o cale adusă de versiunea nouă (de exemplu un `docs/notite.md` al tău, dacă versiunea nouă aduce un fișier cu exact acest nume) e înlocuit, fără copie; ține-ți fișierele proprii în afara folderului programului. La categorii contează unde ai scris: regulile din `config/categorii.personal.json` rămân; modificările făcute direct în `config/categorii.json` se pierd la actualizare (e un fișier al programului, deci versiunea nouă îl înlocuiește). Dacă folderul tău nu are lista versiunii vechi (de exemplu l-ai luat cu **Code → Download ZIP**, nu din Releases), actualizarea nu șterge nimic. Nu trebuie să te loghezi din nou.

### Dacă actualizarea nu reușește

- **O eroare la descărcare sau la verificarea amprentei:** nu se schimbă nimic în folderul programului; arhiva greșită se șterge. **O eroare la instalare:** programul pune la loc versiunea veche, fișier cu fișier. În ambele cazuri spune de ce, iar aplicația merge mai departe pe versiunea de acum. Încearcă din nou mai târziu.
- **Actualizare întreruptă** (curent căzut, fereastră închisă la mijloc): la următoarea pornire, înaintea pregătirii lansatorului și a restului programului, programul vede actualizarea neterminată, pune la loc versiunea veche, îți spune și apoi face ce i-ai cerut (de obicei pornește aplicația, pe versiunea veche). Merge și fără internet, fiindcă pregătirea vine abia după. Doar dacă `.venv` lipsește sau Python-ul din el nu pornește (de exemplu după ce ai mutat folderul), recuperarea vine imediat după pregătire. Poți încerca din nou oricând.
- **Se repetă:** folosește calea manuală de mai jos și deschide un Issue (fără date personale), cu mesajul primit.

### Manual

1. Descarcă arhiva nouă din **Releases** și extrage-o într-un **folder nou**.
2. Din folderul vechi copiază în cel nou doar ce vrei să păstrezi: `iesiri/` (rapoartele) și, dacă ai creat-o, `config/categorii.personal.json`.
3. Pornește lansatorul din folderul nou și te loghezi din nou.
4. Curăță folderul vechi: [Dezinstalare completă](#dezinstalare-completă), începând cu ștergerea sesiunii **din folderul vechi**.

### Cu git

Într-o copie făcută cu `git clone`, actualizarea din program e refuzată („Folderul ăsta e o copie git: actualizează cu git pull.”); verificarea versiunii merge în continuare. Rulează `git pull`, apoi pornește lansatorul ca de obicei (dacă `requirements.txt` s-a schimbat, pregătirea reinstalează singură pachetele).

## Dezinstalare completă

Programul nu scrie în Registry, în AppData, în `~/Library` sau în folderul tău personal, deci nu are ce să dezinstalezi în afara folderului lui. Ordinea contează:

1. **Închide** fereastra browserului programului și aplicația.
2. **Șterge sesiunea**: Windows `sterge_sesiunea.bat`; macOS/Linux `./porneste.sh --sterge-sesiunea` (pe Mac: `sh porneste.command --sterge-sesiunea`). Scrii `DA`. Se face **înainte** de ștergerea folderului: dacă ai mutat sesiunea în alt loc cu `EMAG_PROFILE_DIR`, ea ar rămâne altfel pe disc.
3. Dacă vrei să păstrezi rapoartele, copiază-le într-un loc care nu se sincronizează cu un cloud.
4. **Șterge folderul programului.** Apoi golește Coșul (fișierele șterse rămân acolo și pot fi restaurate).
5. **Sesiunea de pe eMAG nu se închide de pe calculatorul tău:** ștergerea locală doar șterge fișierele. Ca să închizi o sesiune veche, schimbă parola contului eMAG.
6. Opțional: browserul pornit de program își scrie singur fișiere temporare (pe Windows, în `%TEMP%`: două `.tmp` șterse la închidere și `cv_debug.log`, care rămâne).

## Probleme frecvente

| Ce vezi | Cauza | Ce faci |
|---|---|---|
| „Windows a protejat computerul” / „Nu putem verifica cine a creat acest fișier” | Fișier descărcat de pe internet, nesemnat | [Windows](#windows): verifici conținutul, apoi **Mai multe informații → Rulează oricum**. |
| macOS: „porneste.command” nu poate fi deschis | Script nesemnat de un dezvoltator înregistrat la Apple | [macOS](#macos): **Setări de sistem → Confidențialitate și securitate → Deschide oricum**, sau `sh porneste.command` din Terminal. |
| Linux: „Permission denied” la `./porneste.sh` | Arhiva n-a păstrat dreptul de execuție | `sh porneste.sh` sau, o dată, `chmod +x porneste.sh porneste.command instalare/pregatire.sh`. |
| „nu găsesc fișierele programului lângă acest script” | Lansator pornit din interiorul ZIP-ului | Extrage tot, apoi pornește din folderul extras. |
| „Programul nu este pregătit încă. Dă mai întâi dublu-clic pe porneste.bat: pregătește singur tot ce lipsește.” | Ai pornit `login.bat`, `ruleaza.bat`, `demo.bat` sau `sterge_sesiunea.bat` înainte de prima pornire | Pornește o dată `porneste.bat`. |
| „nu am putut descărca uv” sau „instalarea pachetelor a eșuat” | Fără internet, sau un antivirus/firewall care blochează github.com sau pypi.org | Verifică internetul și pornește din nou. |
| „arhiva uv descărcată nu are amprenta SHA-256 așteptată” | Descărcare stricată sau modificată pe drum | Programul a șters-o și nu a folosit-o. Încearcă din nou; dacă se repetă, deschide un Issue (fără date personale). |
| „calea acestui folder e prea lungă” (Windows) | Calea întreagă are peste 190 de caractere | Mută folderul în `C:\cheltuieli-emag` și pornește din nou. |
| „ATENȚIE: nu pot porni niciun browser” | Lipsesc Edge și Chrome, iar Chromium descărcat nu pornește (pe Linux: lipsesc biblioteci) | Instalează Edge sau Chrome; pe Ubuntu/Debian poți rula comanda `sudo … install-deps chromium` afișată. Demonstrația merge și fără. |
| „nu te-ai logat în timpul alocat” | Programul așteaptă 10 minute să te loghezi | Pornește din nou și termină login-ul în fereastra browserului. Pentru mai mult timp: `EMAG_LOGIN_WAIT_SECONDS` (vezi mai jos). |
| „redirecționat la login…” sau „nicio comandă pe prima pagină a listei” | Sesiunea eMAG a expirat | Pornește din nou și loghează-te. Dacă se repetă imediat după un login reușit, eMAG și-a schimbat paginile: deschide un Issue fără date personale. |
| Eroarea spune că profilul e în uz | Mai rulează o copie a programului sau fereastra lui | Închide ferestrele browserului deschise de program și pornește o singură dată. |
| Cifrele diferă de ce văd pe eMAG | Vezi [întrebarea frecventă](INTREBARI.md) | Deschide comanda din link și compară-o cu raportul. |
| Am mutat folderul și nu mai pornește | Mediul `.venv` ține minte vechea cale | Pornește lansatorul: refă singur `.venv`. Dacă tot nu merge, șterge folderele `.venv` și `.uv` și pornește din nou. |
| „Folderul ăsta e o copie git: actualizează cu git pull.” | Programul a fost luat cu `git clone`, nu din arhiva lansării | `git pull`, apoi pornește lansatorul ([Cu git](#cu-git)). |
| „Nu pot ajunge la GitHub: fără internet sau conexiunea e blocată.” | Fără internet, un firewall care blochează GitHub sau o rețea care cere proxy (actualizarea nu folosește setările de proxy ale sistemului) | Verifică internetul și încearcă din nou; în spatele unui proxy, actualizează [manual](#manual). Programul merge mai departe cu versiunea de acum. |
| „Limita de cereri GitHub a fost atinsă; încearcă peste o oră.” | GitHub limitează cererile fără cont venite de la aceeași adresă IP | Așteaptă și pornește din nou. |
| „Amprenta arhivei descărcate nu se potrivește…” | Descărcare stricată sau modificată pe drum | Arhiva a fost ștearsă și nu s-a instalat nimic. Încearcă din nou; dacă se repetă, deschide un Issue (fără date personale). |
| „Actualizarea nu s-a putut instala (…); am revenit la versiunea …” | Un fișier al programului, numit în mesaj, a fost ținut deschis (de obicei de altă fereastră a programului, de un editor sau de un antivirus) ori discul e plin | Închide ce ține deschis fișierul numit în mesaj (de obicei celelalte ferestre ale programului) și încearcă din nou. Nimic nu s-a schimbat. |
| „O altă actualizare e în curs…” | Altă fereastră a programului, din același folder, instalează sau desface chiar acum o actualizare (programul o așteaptă 2 secunde înainte de mesaj). Apare și la pornire, dacă tocmai atunci cealaltă lucrează; programul se oprește atunci fără să facă altceva | Așteaptă să termine cealaltă fereastră, apoi încearcă din nou sau pornește din nou programul. |
| „Calea folderului programului e prea lungă pentru Windows…” | Calea folderului plus cea mai lungă cale din versiunea nouă trec de limita Windows | Mută folderul în `C:\cheltuieli-emag` și încearcă din nou. |
| „Actualizarea la versiunea … a fost întreruptă; am revenit la versiunea …” | Actualizarea s-a oprit la mijloc (curent căzut, fereastră închisă) | Nimic de reparat: programul a pus la loc versiunea veche, apoi a făcut ce i-ai cerut (de obicei pornește aplicația). Poți încerca iar actualizarea. |
| „…revenirea la versiunea … nu s-a terminat” sau „Jurnalul actualizării (…) nu se poate citi…”; la pornire, lansatorul adaugă „Pornirea s-a oprit: actualizarea întreruptă nu a putut fi desfăcută.” | Un fișier blocat, un disc plin sau o legătură spre alt loc (pusă în folderul programului după întrerupere) chiar în calea revenirii; programul se oprește fără să facă altceva, ca să nu ruleze pe fișiere amestecate. Căile nerefăcute sunt toate în jurnalul din `logs/` | Închide ce ține deschis fișierul numit și pornește din nou programul: reîncearcă singur. O legătură numită în mesaj o muți sau o ștergi (nu folderul spre care duce). Dacă tot nu merge, ia arhiva din Releases într-un folder nou și copiază `iesiri/` și `config/categorii.personal.json` ([manual](#manual)). |
| „…e o legătură spre alt loc; din siguranță, nu …” | În folderul programului (sau în `.actualizare/`) e o legătură sau o joncțiune spre alt folder, exact unde actualizarea ar scrie, ar muta sau ar șterge; programul nu urmează legături, ca să nu atingă nimic din afara lui | Mută sau șterge legătura numită în mesaj (nu folderul spre care duce) și încearcă din nou. |

**Cum alegi alt browser:** variabila `EMAG_BROWSER_CHANNEL` (`msedge`, `chrome` sau `chromium`); fără ea, programul încearcă singur, în ordine, Edge, Chrome și Chromium-ul descărcat. Windows: în Command Prompt, în folderul programului, `set EMAG_BROWSER_CHANNEL=chrome`, apoi `porneste.bat` în **aceeași fereastră**. macOS/Linux: `EMAG_BROWSER_CHANNEL=chrome ./porneste.sh`. Folosește același browser la login și la rulare; dacă îl schimbi, șterge întâi sesiunea și te loghezi din nou.

**Cum mărești timpul de login:** la fel, cu `EMAG_LOGIN_WAIT_SECONDS=1800` (30 de minute).

**Cum oprești verificarea versiunii noi:** la fel, cu `EMAG_UPDATE_CHECK=0` (Windows: `set EMAG_UPDATE_CHECK=0`, apoi `porneste.bat` în aceeași fereastră; macOS/Linux: `EMAG_UPDATE_CHECK=0 ./porneste.sh`). Aplicația scrie atunci „Verificarea versiunilor noi e oprită.” și nu mai face nicio cerere spre GitHub; `--actualizeaza` merge în continuare, când îl rulezi tu.

## Pentru programatori

După prima pornire a lansatorului (care creează `.venv` cu uv), testele:

```
Windows:
.uv\bin\uv.exe pip install --cache-dir .uv\cache --python .venv\Scripts\python.exe --only-binary :all: -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest

macOS / Linux:
.uv/bin/uv pip install --cache-dir .uv/cache --python .venv/bin/python --only-binary :all: -r requirements-dev.txt
.venv/bin/python -m pytest
```

`requirements.txt` conține doar ce rulează programul; `requirements-dev.txt` adaugă `pytest`. Versiunile sunt fixate; `siguranta.yml` (pip-audit) le verifică săptămânal, iar Dependabot propune actualizările. Versiunea lui uv, a lui Python și amprentele arhivelor uv stau în `instalare/versiuni.txt`. Testele de browser pornesc Edge sau Chrome fără fereastră și se sar dacă nu e instalat niciunul.

Opțiuni din linia de comandă (`ruleaza.py …`; pe Windows `porneste.bat …`, pe macOS/Linux `./porneste.sh …` le pasează mai departe):

| Opțiune | Ce face |
|---|---|
| *(fără opțiuni)* | rulare completă |
| `--aplicatie` | pornește aplicația locală (server pe `127.0.0.1`) și deschide pagina; `--fara-browser` nu deschide browserul |
| `--prag 1000` | alt prag pentru „achiziție mare”, în Lei pe bucată (implicit 500) |
| `--limita-comenzi 20` | citește doar primele 20 de comenzi, pentru un test rapid |
| `--din-cache iesiri/<rulare>` | refă raportul din `comenzi.json` și `retururi.json`, fără browser |
| `--doar-login` | doar te loghezi și salvezi sesiunea |
| `--demo` | comenzi inventate, fără browser și fără login |
| `--sterge-sesiunea` | șterge sesiunea salvată, după ce scrii `DA` (cu `--fara-confirmare`, fără întrebare) |
| `--deschide` | deschide raportul la final |
| `--iesire <folder>` | folderul în care se creează rularea |
| `--versiune` | scrie versiunea programului („Cheltuieli eMAG X.Y.Z”) și se oprește |
| `--actualizeaza` | trece la ultima versiune publicată, după ce scrii `DA` (cu `--fara-confirmare`, fără întrebare); vezi [Actualizare](#actualizare) |

Variabile de mediu (toate opționale; singurele pe care le citește programul):

| Variabilă | Implicit | Rost |
|---|---|---|
| `EMAG_BROWSER_CHANNEL` | gol (automat) | browserul: `msedge`, `chrome` sau `chromium`; gol = primul găsit, în această ordine |
| `EMAG_PROFILE_DIR` | `<proiect>/.profil_browser` | folderul profilului cu sesiunea; **`--sterge-sesiunea` îl șterge**, deci trebuie să fie un folder dedicat programului, nu profilul tău real de browser |
| `EMAG_FETCH_CONCURRENCY` | `3` | câte pagini de detalii se cer simultan |
| `EMAG_LOGIN_WAIT_SECONDS` | `600` | cât așteaptă programul să te loghezi manual |
| `EMAG_APP_IDLE_MINUTES` | `30` | după câte minute fără nicio cerere se oprește singură aplicația locală (între 1 și 1440) |
| `EMAG_UPDATE_CHECK` | pornită | `0` oprește verificarea versiunii noi la pornirea aplicației locale (cererea spre `api.github.com`); `--actualizeaza` merge și așa, la cerere |

## Ce a fost testat și ce nu

**Testat:**

- **Windows 11, cont real** (al autorului, ~400 de comenzi), cu Edge: `porneste.bat` și aplicația („Pornește analiza”), `login.bat`, `ruleaza.bat`; cifrele au ieșit identice între variante.
- **Windows 11, de la zero**, fără Python instalat, într-o copie a programului într-o cale cu spații: `porneste.bat --demo` a descărcat și a verificat uv, a adus Python și pachetele și a făcut raportul.
- **Linux (Ubuntu, în WSL, fără interfață grafică):** pregătirea de la zero, demonstrația și aplicația locală (cheie, Host, oprire). Browserul descărcat n-a pornit acolo din lipsa bibliotecilor de sistem, caz pentru care scriptul afișează ce trebuie făcut.
- **Pe GitHub, la fiecare modificare** (`.github/workflows/`): toate testele automate pe Windows, macOS și Linux, și „Pornire de la zero” pe toate trei (lansatorul, demonstrația, aplicația locală; pe Linux și varianta cu Chromium descărcat).
- **Actualizarea**, în testele automate cu un GitHub fals (descărcare, amprente, arhive greșite, legături care nu se urmează, revenire după eroare și după întrerupere, inclusiv cu procesul omorât de-a binelea în timpul instalării, după care lansatorul real o desface fără internet, înaintea pregătirii) și, pe GitHub, după fiecare lansare și săptămânal (`actualizare.yml`): o copie „îmbătrânită” a ultimei lansări și, când există, lansarea anterioară, neîmbătrânită, se actualizează din terminal și din aplicație, pe Windows, macOS și Linux. O lansare se publică doar după ce trec testele și pornirea de la zero, iar dacă testul de după publicare pică, ea e retrasă (devine „pre-release”) și aplicația n-o mai oferă; rularea săptămânală doar semnalează o problemă (în fila Actions), fără să retragă ceva.

**Netestat sau nevalidat:**

- Fluxul cu login real pe macOS și pe Linux și pe mai multe conturi eMAG diferite.
- Windows 10, Windows pe ARM, Mac cu procesor Intel.
- Comportamentul exact al SmartScreen, Gatekeeper și al antivirusurilor pe fiecare versiune.
- Pasul „Deblocare” din proprietățile ZIP-ului pe Windows și caracterele `&`, `%`, `!`, `^` în calea folderului.
- Trecerea reală de la o versiune publicată la următoarea: 1.0.0 e prima versiune cu actualizări, deci prima trecere adevărată va fi spre versiunea de după ea; de atunci, `actualizare.yml` o încearcă la fiecare lansare, pornind de la lansarea anterioară (până atunci, doar copia „îmbătrânită”). Revenirea după un proces omorât și lacătul dintre două ferestre au fost încercate cu procese reale pe Windows și pe Linux (Ubuntu, în WSL); pe macOS le încearcă doar testele automate de pe GitHub. Lansatorul care desface o actualizare întreruptă înaintea pregătirii, fără internet, a fost încercat cap-coadă doar pe Windows (`porneste.bat`, iar `porneste.sh` și `porneste.command` sub sh-ul din Git for Windows); pe Linux și macOS reale îl încearcă doar testele automate de pe GitHub. Actualizarea în spatele unui proxy nu merge (vezi [Probleme frecvente](#probleme-frecvente)).

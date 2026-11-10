# Chrome Web Store: texte, formular de date și ghid de publicare

**10 noiembrie 2026 — versiunea 1.1.0:** cele șase funcții aprobate adaugă panoul `sidePanel`, lista, țintele, bugetele, etichetele și exportul PNG. Robert a aprobat [addendumul](aprobare-confidentialitate-2026-11-08.md) pe 10 nov. 2026 (E26); textele lui sunt integrate în politică și în §4, §5, §7 și §9 de mai jos. Descrierea lungă (§3), capturile și plăcuța mică (§10) pentru 1.1.0 sunt aprobate tot pe 10 nov. 2026 (E27). Pașii rămași sunt în [predarea lansării](handoff/2026-11-08-lansare-extensie.md).

Materialele pentru extensia **Cât am cheltuit pe eMAG**: numele, descrierile, justificările, răspunsurile din formularul de date, instrucțiunile pentru recenzent, imaginile și ghidul de publicare. Starea la 16 oct. 2026: identitatea, plăcuța 2 cu slogan, modul întunecat obligatoriu, criptarea locală, descrierile, politica și corecturile de interfață sunt **aprobate** (E15–E20). Robert a cerut lansare **publică de la început** (E21) și a autorizat asistentul să facă publicarea (E22). Sursele oficiale de mai jos au fost citite pe 14 oct. 2026; etichetele dashboard-ului se verifică la completare.

Ce vede publicul (numele, descrierile) e în română: extensia și magazinul sunt doar în română. Câmpurile pe care le citesc doar recenzenții (scopul unic, justificările, codul de la distanță, instrucțiunile) sunt date în engleză, ca să se lipească direct în dashboard, cu explicația în română alături. Politica de confidențialitate: [CONFIDENTIALITATE-EXTENSIE.md](CONFIDENTIALITATE-EXTENSIE.md).

Legenda ghidului: **[R]** = Robert, **[C]** = asistentul care pregătește și operează publicarea autorizată.

**Înainte de trimitere:** verificările codului și pachetului, accesibilitatea publică a politicii și completarea câmpurilor reale din dashboard. Aprobările pentru textele din E20 și pentru publicare nu se cer din nou. Parola, codurile 2FA și o eventuală plată sunt introduse de Robert, în paginile furnizorului.

**Licență:** Robert a decis „Păstrăm GPL și continuăm lansarea” (E19). Licența GPL-3.0 existentă rămâne; `LICENSE` nu se modifică.

## 1. Numele și autorul (E15, aprobate pe 16 oct. 2026)

Numele exact este **Cât am cheltuit pe eMAG** (23 de caractere), cel din `extensie/manifest.json`. Autor: **Robert Pop**; subtitlul din produs și plăcuță este **creat de Robert Pop**. Limita oficială a numelui: cel mult 75 de caractere.

Robert a respins „neoficial” în nume. Propunerea E9 din 13 oct. 2026 este depășită explicit de E15; nu se mai cere alegerea unei variante de nume. Rămân bonul propriu, lipsa siglei eMAG și mențiunea descriptivă „Proiect independent, neafiliat cu eMAG”. Aprobarea numelui nu aprobă automat descrierile sau politica de confidențialitate.

Modul întunecat este obligatoriu (E17); alegerea temei se păstrează la reîncărcare și repornire. Plăcuța aprobată păstrează tema luminoasă a variantei 2 originale (E16).

## 2. Descrierea scurtă (aprobată pe 16 oct. 2026; 132 de caractere cel mult)

Descrierea din `extensie/manifest.json` (rândul 4) se folosește și în `chrome://extensions`, și în magazin (pagina oficială a cheii `description`). Textul de azi are **130 de caractere** (limita oficială: 132):

```
Cât ai plătit, de fapt, pe eMAG: citește comenzile și retururile din contul tău și calculează totul în browser. Neafiliat cu eMAG.
```

Dacă Robert vrea alt text, se schimbă manifestul (dashboard-ul îl citește de acolo); `extensie/tests/unit/build.test.js` verifică ≤ 132 de caractere și mențiunea de neafiliere.

## 3. Descrierea lungă (aprobată pe 16 oct. 2026; completată pentru 1.1.0 pe 10 nov. 2026)

Textul aprobat de Robert (E20), cu completările 1.1.0 aprobate pe 10 nov. 2026 (E27), de lipit în câmpul „Description”:

```
Cât ai plătit, de fapt, pe eMAG? Extensia citește comenzile și retururile din contul tău și calculează cât ai plătit efectiv pe ce ai păstrat, după reduceri, vouchere, anulări și retururi.

CE ÎȚI ARATĂ

- Totalul plătit pentru produsele păstrate, cu transportul și taxele.
- Cheltuielile pe categorii, ani, vânzători și produse.
- Evoluția prețurilor pentru produsele cumpărate de mai multe ori.
- Avertismente despre comenzile care necesită verificare.
- Raport HTML, tabele CSV și date JSON pe care le poți descărca.
- Planificarea campaniilor, ca Black Friday: perioada cu date și ore, lista de produse cu prețuri-țintă și bilanțul comenzilor din acel interval.
- Bugete lunare sau anuale, comparate cu ce ai plătit efectiv.
- Retururile fără rezultat sau fără rambursare, de urmărit.
- Etichete personale pentru cumpărături și bilanțul anului ca imagine PNG, cu suma ascunsă dacă vrei.
- Pe pagina unui produs eMAG, în panoul lateral Chrome: cât ai plătit ultima dată și minimul tău pentru același produs.

CUM O FOLOSEȘTI

1. Apasă iconița extensiei și apoi „Pornește analiza”.
2. Dacă este necesar, te loghezi tu în fila eMAG deschisă de extensie.
3. Aștepți raportul. Durata depinde de numărul comenzilor și de răspunsurile site-ului.

„Încearcă cu date inventate” arată un raport demonstrativ fără cont și fără citirea datelor tale.

DATELE TALE

Analiza se face local. Autorul nu primește istoricul cumpărăturilor și extensia nu are server sau telemetrie. Extensia citește paginile comenzilor și retururilor în memorie, apoi păstrează câmpurile necesare raportului. Pe o pagină de produs, doar la cererea ta, citește denumirea, adresa și prețul produsului principal. Nu extrage parola, codul 2FA, cookie-urile sau datele cardului. Browserul trimite către site sesiunea ta existentă, ca la o vizită obișnuită.

Ultima analiză, jurnalul, lista de produse, bugetele și etichetele sunt păstrate criptat în profilul browserului. Cheia rămâne locală; nu introduci o parolă suplimentară. Cine folosește profilul tău deschis poate vedea raportul. „Șterge datele” elimină analiza, jurnalul, lista de produse, bugetele, etichetele și cheia locală. Fișierele descărcate, inclusiv imaginea bilanțului, sunt necriptate și trebuie șterse separat.

DE ȘTIUT

Proiect independent, neafiliat cu eMAG. Folosește extensia numai pentru propriul cont și verifică termenii site-ului privind accesul automat. Dacă paginile se schimbă, pot apărea erori sau rezultate incomplete: compară raportul cu istoricul din cont.

Doar în română, pentru Chrome 120 sau mai nou. Nu include regulile personale de categorii din programul pentru calculator.

Cod și suport: https://github.com/poprobert0412/cheltuieli-emag

Politica de confidențialitate: https://github.com/poprobert0412/cheltuieli-emag/blob/main/docs/CONFIDENTIALITATE-EXTENSIE.md
```

## 4. Scopul unic („Single purpose”)

Cerința oficială: scopul trebuie să fie îngust și ușor de înțeles. Câmpul îl citesc recenzenții.

Text aprobat pe 10 nov. 2026 (E26), pentru 1.1.0:

```
Help users understand and plan their own eMAG spending, with local purchase reports, budgets, return follow-up, personal labels, a wishlist and a product-page comparison against their own purchase history.
```

În română: ajută utilizatorul să-și înțeleagă și să-și planifice cheltuielile proprii pe eMAG: rapoarte locale, bugete, urmărirea retururilor, etichete personale, o listă de dorințe și comparația paginii de produs cu propriul istoric. Toate funcțiile servesc acestui scop.

## 5. Justificarea permisiunilor („Permission justification”)

Câte un câmp pentru fiecare permisiune din manifest (`extensie/manifest.json`, rândurile 7-8). Textele, în engleză, se lipesc ca atare; completările 1.1.0 pentru `storage` și `scripting` și justificarea `sidePanel` sunt aprobate pe 10 nov. 2026 (E26):

**`storage`**

```
Stores the last analysis (report figures, extracted orders and returns, and the run log) and the current run log locally with AES-GCM encryption. The key is generated locally and kept separately in the extension's IndexedDB storage; there is no extra password and the key is not sent to the author. The "Delete data" button deletes the analysis, log and local key. A short-lived "one analysis at a time" record is kept in chrome.storage.session. The theme preference is stored separately in localStorage. Extension data is not synced through the user's Google account. Also stores the user's wishlist, observed and target prices, budgets, campaign dates and personal labels locally, encrypted. These preferences survive a new analysis and are removed by Delete data.
```

**`scripting`**

```
Runs small functions that are packaged in the extension (src/colectare/page_functions.js) inside the extension's own background work tab on www.emag.ro, in the isolated world (chrome.scripting.executeScript). They read the rendered order and return lists, check whether the user is logged in, click the "Vezi mai mult" (Load more) button of the returns list, and request the order and return detail pages with the user's own session. No code is fetched from the network. On the user's action, also reads the main product name, URL and available price from the active eMAG product page in the isolated world. It does not change the merchant page or execute remote code.
```

**`sidePanel`**

```
Displays the user's personal product comparison and target-price controls in Chrome's side panel while they view an eMAG product. The panel opens on the user's action and does not read other websites.
```

**Host permission `https://www.emag.ro/*`**

```
The only site the extension works on. It is needed to open and script the work tab on www.emag.ro and to see that tab's address, which tells the extension when the user was sent to the login page. The extension does not access any other site.
```

Nu cere: `tabs`, `cookies`, `downloads`, `webRequest`, `<all_urls>`, scripturi de conținut, pagini accesibile din web. La instalare, Chrome arată un singur avertisment (citirea și modificarea datelor de pe `www.emag.ro`); pentru `storage` și `scripting` nu arată niciunul, iar pentru `sidePanel` se verifică la încărcarea ciornei 1.1.0 ([lista oficială](https://developer.chrome.com/docs/extensions/reference/permissions-list)). Politica magazinului cere cele mai înguste permisiuni necesare; o permisiune nouă cere schimbarea acestei secțiuni, a politicii și a gărzii `tests/test_garda_extensie.py`.

## 6. Cod de la distanță („Remote code”)

Răspuns: **No, I am not using remote code.** Justificarea, în engleză:

```
No. All JavaScript, HTML and CSS are inside the extension package. The manifest keeps Chrome's default Manifest V3 content security policy, and the extension page adds a stricter one in a meta tag: default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'none'; base-uri 'none'; form-action 'none'. There is no eval, no new Function, no inline or external script, no WebAssembly and no importScripts of remote files. The only network requests are GET requests to www.emag.ro made from the extension's own work tab; the HTML that comes back is parsed as data with DOMParser (it never runs) and is never inserted into a page as HTML.
```

Temeiuri: `extensie/src/aplicatie.html:6` (politica de conținut), `extensie/src/colectare/page_functions.js:72` (singurul `fetch`), `tests/test_garda_extensie.py` (fără `eval`, `new Function`, `innerHTML`, scripturi externe). Cerința oficială: întreaga funcționalitate trebuie să se vadă din codul trimis; logica adusă de la distanță e interzisă.

## 7. Formularul de date („Privacy practices”)

Politica magazinului cere ca formularul, politica de confidențialitate și comportamentul să se potrivească; o nepotrivire e încălcare. User Data FAQ (întrebarea 3) cere dezvăluirea și pentru datele prelucrate doar pe dispozitiv, deci formularul declară ce **atinge** extensia, chiar dacă nu pleacă nimic nicăieri.

**Tipuri de date** (etichetele de mai jos sunt cele știute din dashboard, în engleză; pagina oficială a câmpurilor le arată doar ca imagine, iar User Data FAQ, întrebarea 4, folosește denumiri puțin diferite, de exemplu „Web browsing activity”; Robert le potrivește la completare):

| Tip | Se bifează? | De ce |
|---|---|---|
| Financial and payment information | **Da** | Sumele plătite și istoricul tranzacțiilor din comenzi și retururi (totaluri, vouchere, transport, rambursări); din 1.1.0 și prețurile observate, prețurile-țintă și bugetele introduse de utilizator. Nu numere de card |
| Website content | **Da** | Textul și linkurile paginilor eMAG de comenzi și retururi, citite prin extensie; din 1.1.0 și denumirea, adresa și prețul produsului principal, la cererea utilizatorului |
| Personally identifiable information | **Da** | Paginile procesate temporar pot include datele cumpărătorului, chiar dacă acestea nu sunt extrase în câmpuri dedicate; declarare aprobată prin E20 |
| Health information | Nu | Nu citește și nu caută date de sănătate. Numele produselor cumpărate sunt text de produs: pot sugera ce a cumpărat omul, dar nu sunt simptome, diagnostice sau istoric medical (judecată proprie, de confirmat la completare) |
| Authentication information | Nu | Parola, codul 2FA și cookie-urile nu sunt citite: omul se loghează în pagina eMAG |
| Personal communications | Nu | Nu citește mesaje, e-mailuri sau chat |
| Location | Nu | Nu citește locația |
| Web history | **Da** | Numai adresele necesare filei de lucru, căile comenzilor/retururilor și, din 1.1.0, adresa paginii de produs citite la cerere sau salvate în listă; nu istoricul general al navigării. Declarare aprobată prin E20; se potrivește etichetei „Web browsing activity” dacă dashboard-ul o folosește |
| User activity | Nu | Nu urmărește clicuri, mișcarea mouse-ului sau tastele; singurul clic în pagina eMAG e al extensiei („Vezi mai mult”) |

Lista de produse și etichetele personale (1.1.0) sunt conținut introdus de utilizator. Dacă dashboard-ul are o categorie pentru conținut generat de utilizatori, se bifează și aceea; altfel sunt acoperite de rândurile de mai sus (adrese, prețuri, bugete) și de politica publică (E26).

Lista oficială de exemple de date de utilizator (User Data FAQ, întrebarea 4): date personale (inclusiv numere de identificare), informații financiare și de plată, informații de sănătate, informații de autentificare, conținut și resurse ale site-urilor, date din formulare, activitate de navigare, comunicații personale și conținut generat de utilizatori.

**Cele trei certificări** se bifează, toate adevărate. Formularea exactă nu apare ca text pe nicio pagină oficială citită; cea de mai jos e cea știută din dashboard și se verifică la completare:

- I do not sell or transfer user data to third parties, outside of the approved use cases: datele nu se transmit nicăieri.
- I do not use or transfer user data for purposes that are unrelated to my item's single purpose: se folosesc doar pentru raport.
- I do not use or transfer user data to determine creditworthiness or for lending purposes: nu.

**URL-ul politicii de confidențialitate:** `https://github.com/poprobert0412/cheltuieli-emag/blob/main/docs/CONFIDENTIALITATE-EXTENSIE.md` (depozitul e public; adresa funcționează după ce fișierul e pe `main`).

**Criptarea datelor stocate (E18) și textele aprobate (E20).** Ultima analiză și jurnalul sunt criptate local cu AES-GCM. Cheia este locală, separată de date, fără parolă suplimentară; „Șterge datele” șterge analiza, jurnalul și cheia. Cine controlează profilul browserului sau folosește extensia deschisă poate vedea raportul. Exporturile sunt necriptate și se șterg separat. Comportamentul se verifică în testele criptării înainte de trimitere.

Politica magazinului, în versiunea anunțată pe 1 iul. 2026 și aplicată din 1 aug. 2026, cere ca datele colectate să fie strict necesare scopului unic și dezvăluite vizibil, iar orice schimbare ulterioară a felului în care sunt tratate datele să fie anunțată utilizatorilor. Extensia păstrează doar ce folosește raportul (câmpurile enumerate în politică). O versiune care ar citi sau ar păstra altceva trebuie să schimbe întâi formularul, politica și acest document.

## 8. Dezvăluirea din produs

User Data FAQ (întrebarea 10) cere ca dezvăluirea și acordul pentru datele utilizatorului să fie în interfața produsului, înainte de colectare, printr-o acțiune clară; descrierea din magazin nu ajunge. Azi, în extensie:

- ecranul „Gata de start” spune ce citește extensia (comenzile și retururile din contul tău eMAG), ce face cu ele (cât ai plătit efectiv) și că „totul rămâne în browserul tău” (`extensie/src/aplicatie.html:77`);
- sub butonul „Pornește analiza” spune că se deschide o filă eMAG în care te loghezi tu și că parola nu trece prin extensie (`extensie/src/aplicatie.html:83`);
- citirea pornește doar la apăsarea butonului (`extensie/src/ecrane/start_screen.js:13-21`);
- detaliile (ce se ia din pagini, ce nu se citește, ce se salvează) sunt în întrebările frecvente de pe aceeași pagină (`extensie/src/aplicatie.html:274-277` și `:306-309`), dar pliate.

Textul suplimentar aprobat pe 16 oct. 2026 (E20) este aplicat sub butonul de pornire: „Analiza și jurnalul se păstrează criptat în acest browser. Nu ajung la autor. Le elimini cu «Șterge datele».” Întrebările frecvente explică cheia locală, limita protecției profilului deschis și exporturile necriptate.

## 9. Instrucțiuni pentru recenzent („Test instructions”)

Se lipesc în fila „Test instructions” (sau în câmpul de note pentru recenzent din dashboard):

```
No eMAG account is needed to review this extension.

1. Install the extension and click its toolbar icon. The extension page opens in a new tab (there is no popup).
2. Click "Încearcă cu date inventate" ("Try with invented data"), the secondary button under "Pornește analiza". A full report built from invented orders appears. This path reads nothing from any account and makes no network request. You can download raport.html and analiza.json from the report.
3. Optional: click "Pornește analiza" ("Start the analysis"). The extension opens a background tab on https://www.emag.ro/history/shopping?time=older. Without an eMAG login it shows the screen "Loghează-te în eMAG" ("Log in to eMAG") and waits up to 10 minutes. It never types into the page and never reads the password. Click "Oprește" ("Stop") to cancel; the work tab is closed.
4. A real analysis needs a Romanian eMAG account (www.emag.ro). After the user logs in, the extension reads the order and return history with GET requests made from that tab (3 detail pages at a time) and shows the report. No shared test account is provided: an eMAG account holds a person's purchase history, and the demo path above shows the whole interface and report.
5. Side panel (version 1.1.0): open any product page on https://www.emag.ro/ and click the extension's toolbar icon. Chrome's side panel opens and, on "Citește produsul" ("Read the product"), the extension reads the product name, URL and price from that page and compares them locally with the user's own purchases. Without a saved analysis there is nothing to compare, but the reading and the target-price controls still work. On any other page the toolbar icon opens the extension page instead.
6. Everything is in the package: no remote code, and only these permissions: storage, scripting, sidePanel and the host permission https://www.emag.ro/*. The only external link is the "Snow Globe" footer link (https://snowglobe.ro/), opened by the user in a new tab with noopener and noreferrer; no data is sent with it. The source code and the tests are public: https://github.com/poprobert0412/cheltuieli-emag (folder extensie/). The extension page is in Romanian only.
```

Fiecare pas e verificabil în cod: butoanele (`extensie/src/aplicatie.html:82`, `:98`, `:176`), prima adresă din fila de lucru (`extensie/src/settings.js:6-7`), așteptarea de 10 minute (`:36`), 3 pagini deodată (`:30`), demo-ul fără rețea (`extensie/src/ecrane/main.js:61` și `connect-src 'none'`).

## 10. Imaginile

Cerințele oficiale ([imagini](https://developer.chrome.com/docs/webstore/images)): obligatorii sunt iconița, cel puțin o captură și plăcuța mică; plăcuța mare e opțională. Toate imaginile folosesc doar date inventate (raportul demonstrativ și stări simulate) și nu au sigla eMAG (E15).

| Imagine | Cerință oficială | Stare |
|---|---|---|
| Iconița magazinului | 128×128 px, PNG; desenul de 96×96 px, cu margine transparentă de 16 px | **Gata:** `extensie/src/iconite/icon-128.png` (128×128, desenul ocupă pixelii 16-111, măsurat). Bonul aplicației pe un pătrat deschis cu colțuri rotunjite, varianta B (E13); e și iconița din manifest |
| Capturi | cel puțin 1, cel mult 5; 1280×800 px (preferat) sau 640×400 px; colțuri drepte, fără margini | **1.1.0, aprobate pe 10 nov. 2026 (E27):** 5 PNG-uri din `docs/extensie/capturi/2026-11-10-magazin/`, ordinea de mai jos. Istoric 1.0, **actualizate pe 16 oct. 2026:** 5 PNG-uri de 1280×800 px, RGB, în `outputs/magazin/` al sesiunii; sursele construite actuale, numele și textele aprobate. Imaginile din `docs/extensie/capturi/magazin/` sunt arhiva din 14 octombrie |
| Plăcuța mică | 440×280 px | **Varianta 2 cu slogan aprobată** pe 16 oct. 2026 (E16); antetul folosește numele și autorul din E15. Randarea 1.1.0, aprobată pe 10 nov. 2026 (E27): `docs/extensie/capturi/2026-11-10-magazin/placuta-mica-440x280.png` |
| Plăcuța mare (marquee) | 1400×560 px, opțională | Nu e planificată |

Ordinea capturilor 1.1.0 (E27), toate din `docs/extensie/capturi/2026-11-10-magazin/`, tema luminoasă, date demonstrative:

1. `1-raport-light-1280x800.png`: raportul, cifra mare și lanțul de la comandat la plătit;
2. `3-black-friday-light-1280x800.png`: Black Friday — perioada, bugetul și lista cu ținte (produse inventate);
3. `5-buget-light-1280x800.png`: bugetul anual;
4. `6-recap-light-1280x800.png`: bilanțul anului ca imagine;
5. `4-gata-de-start-light-1280x800.png`: ecranul de start, cu „Încearcă cu date inventate”.

Istoric 1.0. Formatul capturilor nu e precizat de pagina oficială; fișierele finale sunt PNG RGB, fără transparență. Ordinea pentru cele 5 capturi actuale (de la prima, cea mai importantă), toate din `outputs/magazin/`:

1. `1-raport-cifra-mare-si-lantul-1280x800.png`: raportul demonstrativ, cifra mare și lanțul de la comandat la plătit;
2. `2-categorii-1280x800.png`: „Pe ce s-au dus banii”, pe categorii;
3. `3-preturi-la-acelasi-produs-1280x800.png`: prețurile la același produs;
4. `4-gata-de-start-1280x800.png`: ecranul de start, cu „Pornește analiza” și „Încearcă cu date inventate”;
5. `5-analiza-in-lucru-simulata-1280x800.png`: analiza în lucru (stare simulată prin modulele reale, cu valorile inventate ale machetei originale).

Robert a ales **varianta 2 cu sloganul „Cât ai cheltuit de fapt pe eMAG”** (E16). Randarea finală este `placuta-2-slogan-cat-am-cheltuit-pe-emag-440x280.png`, în `outputs/magazin/` al livrabilelor sesiunii din 16 oct. 2026; sursa HTML este alături. Păstrează designul original: bonul, fundalul luminos, fonturile, sloganul și markerul galben, cu numele „Cât am cheltuit pe eMAG” și subtitlul „creat de Robert Pop”. Originalele din `docs/extensie/capturi/magazin/` rămân arhivă; varianta 1 nu a fost aleasă. Publicarea materialelor actuale este autorizată prin E22. Fișierele `preview-*` sunt dovezi înainte/după, nu imagini de încărcat în magazin.

## 11. Declarația trader / non-trader (E28, înlocuiește E10)

Pagina oficială ([Trader disclosure](https://developer.chrome.com/docs/webstore/program-policies/trader-disclosure)) folosește definițiile Comisiei Europene: **trader** e cine acționează în scopuri legate de comerțul, afacerea, meseria sau profesia lui; **non-trader** e cine acționează în afara lor. Declarația o face dezvoltatorul și e responsabilitatea lui s-o facă exact.

- **Ce se declară (E28, 10 nov. 2026):** *trader*. Publisher-ul afișat este **Snow Globe Solutions**, iar entitatea declarată este **POP M. D. ROBERT PERSOANĂ FIZICĂ AUTORIZATĂ** (CUI 55776662), cu datele din `SnowGlobe/config/business.json`. Datele de contact cerute de Google le introduce Robert, direct în dashboard.
- **Efectul:** datele de identificare și contact ale traderului apar public pe pagina extensiei, iar utilizatorii din UE păstrează drepturile din legislația de protecție a consumatorului față de un trader. Extensia rămâne gratuită, fără plăți sau reclame.
- Interpretare, nu text de lege (Claude, în rolul de jurist cerut de Robert): publicarea sub marca unei firme, ca parte a portofoliului ei, este o activitate legată de profesie, deci *trader* este declarația exactă; *non-trader* sub numele unei firme ar fi fost inexactă. E10 (non-trader, persoană fizică) este înlocuită.

## 12. Alte câmpuri ale paginii

| Câmp | Valoare propusă | Observații |
|---|---|---|
| Limba | română | Extensia și magazinul sunt doar în română |
| Preț | gratuit | Fără plăți în extensie |
| Vizibilitate | **Public** | E21 din 16 oct. 2026 înlocuiește etapa nelistată din E3 |
| Categorie | propus „Shopping” | Nu e din specificație; etichetele exacte se văd în dashboard |
| Regiuni | implicit (toate) | Nu e din specificație; extensia e utilă doar celor cu cont `emag.ro` |
| Site-ul extensiei | `https://github.com/poprobert0412/cheltuieli-emag` | Codul și documentația |
| Adresa de suport | `https://github.com/poprobert0412/cheltuieli-emag/issues` | Fără numere de comandă în mesaje |
| Politica de confidențialitate | adresa din §7 | |
| Versiunea | 1.1.0 | Din `extensie/manifest.json` (E8); fiecare urcare nouă cere o versiune mai mare |

## 13. Ghid pas cu pas

Etichetele din dashboard pot diferi puțin de cele de aici (interfața o ține Google). Parola contului Google, codurile de verificare și datele de card le introduci doar tu, direct în paginile Google: nu le trimiți în chat și nu le scrii în depozit.

**Pasul 1 [C]. Contul de dezvoltator deja pregătit**
- Deschid [chrome.google.com/webstore/devconsole](https://chrome.google.com/webstore/devconsole) în contul pregătit de Robert pentru proiect. Nu creez un alt cont și nu repet înregistrarea.
- [R] Numai dacă Google cere autentificare, cod 2FA sau o plată: Robert introduce valoarea direct în pagina Google, fără s-o trimită în chat. O eventuală taxă afișată se raportează înainte de plată; asistentul nu completează date de card.
- **Rezultat:** acces la dashboard-ul existent; nu se confundă această verificare cu publicarea extensiei.

**Pasul 2 [C]. Declarația trader / non-trader**
- [R] În dashboard, la Settings, publisher-ul rămâne **Snow Globe Solutions** și alegi **Trader**, cu datele PFA-ului (E28; ce înseamnă, la §11). Datele de contact le introduce Robert.
- Costă: nu. Google poate cere mai târziu verificarea declarației. **Îmi trimiți:** „gata”.

**Pasul 3 [C]. Arhiva**
- Construiesc și verific arhiva `cheltuieli-emag-1.1.0.zip`: `npm run verify` în `extensie/` (teste, paritate, construire, e2e), apoi arhiva are `manifest.json` în rădăcină, versiunea 1.1.0 și permisiunile descrise în addendumul actual. Pachetul local verificat este în `extensie/build/functii-2026-11-08/`; CI îl produce în `extensie/dist/`. E22 autorizează operarea publicării; completările de transparență ale noilor funcții așteaptă aprobarea înaintea trimiterii.
- Dacă iau arhiva din CI, GitHub împachetează artefactul într-un ZIP: dezarhivezi și urci ZIP-ul din interior, nu pe cel exterior.

**Pasul 4 [C]. Elementul nou**
- În dashboard apeși butonul de element nou („Add new item” sau similar) și alegi arhiva ZIP. **Ce face:** încarcă pachetul și citește manifestul (nume, descriere, versiune, permisiuni); nu publică nimic. Costă: nu.
- **Rezultat:** apare o ciornă, eventual cu avertismente. **Îmi trimiți:** o captură cu avertismentele, dacă sunt (fără date personale).

**Pasul 5 [C]. Fila „Store listing”**
- Limba: română. Descrierea lungă aprobată: din §3. Categorie și adrese: din §12. Se folosesc capturile actuale pe date demonstrative și plăcuța 2 finală (§10); arhiva imaginilor din 14 octombrie nu înlocuiește verificarea brandingului actual.
- **Nu pune** capturi cu comenzi reale și nu adăuga sigla eMAG.

**Pasul 6 [C]. Fila „Privacy”**
- Scopul unic: §4. Justificările permisiunilor: §5. Codul de la distanță: §6. Tipurile de date și cele trei certificări: §7. URL-ul politicii: §7.
- **Nu bifa** mai puține tipuri de date decât în §7 și nu alege „nu colectez date”: ar contrazice politica și comportamentul.

**Pasul 7 [C]. Fila „Distribution”**
- Vizibilitate: **Public** (E21). Preț: gratuit. Regiuni: implicit.
- Etapa nelistată din E3 a fost înlocuită explicit pe 16 oct. 2026.

**Pasul 8 [C]. Trimiterea la recenzie**
- Pui instrucțiunile din §9 la „Test instructions”, apoi apeși „Submit for review”, conform autorizării E22. Dacă dashboard-ul oferă publicare automată după aprobarea recenziei, o alegi pentru lansarea publică cerută de Robert (E21).
- Costă: nu. **Rezultat:** starea „Pending review”. Documentația oficială spune că recenzia durează de obicei câteva zile, dar poate dura până la câteva săptămâni; peste trei săptămâni, scrii suportului pentru dezvoltatori.
- **Îmi trimiți:** mesajul de aprobare sau de respingere (cu motivul). La o primă trimitere, o respingere înseamnă doar că extensia nu se publică; o repar și retrimit.

**Pasul 9 [C]. Verificarea paginii publice**
- După aprobarea recenziei verific pagina publică față de materialele de aici: nume, descriere, imagini, avertismentul de permisiuni, secțiunea „Privacy practices” (tipurile de date și certificările din §7) și politica. Starea „trimisă la recenzie” se raportează separat de „publicată”.

**Pasul 10 [R]. Test cu prietenii (opțional după publicare)**
- Le poți trimite linkul public și mesajul de la §14. Fiecare compară totalul din extensie cu „Comenzile mele” de pe eMAG. [C] strâng rezultatele (fără numere de comandă) și compar. Această etapă nu mai este o condiție pentru vizibilitatea publică (E21).

**Pasul 11 [R]. Promovarea (separat de publicare)**
- Extensia este trimisă public de la început. Trimiterea mesajelor către prieteni și postarea pe Reddit rămân decizii separate de publicarea tehnică; acest ghid nu le execută automat.

**Pasul 12 [C]. După publicare**
- Adaug linkul magazinului în README (secțiunea „Extensia Chrome”) și verific live pagina publică.

**Ce să NU apeși și ce să NU faci**
- Nu reveni la etapa nelistată din E3: decizia curentă este Public (E21).
- Nu activa plăți sau achiziții în aplicație; extensia e gratuită.
- Nu completa formularul de date cu mai puțin decât în §7.
- Nu urca o arhivă veche din `extensie/dist/`: versiunea din manifest trebuie să fie cea din dashboard și mai mare decât a oricărei urcări anterioare.
- Nu pune în magazin capturi cu date reale sau cu sigla eMAG.
- Nu adăuga permisiuni, pagini sau cereri de rețea noi fără să refaci întâi textele din acest document, politica și garda `tests/test_garda_extensie.py`.
- Nu comite și nu posta fișiere descărcate din extensie (`comenzi.json`, `retururi.json` ș.a.): conțin istoricul de cumpărături.

## 14. Mesaj pentru prietenii care testează

```
Salut. Încerci o extensie pentru Chrome care adună cât ai plătit, de fapt, pe eMAG. E în testare și neafiliată cu eMAG.

1. Instalează din link: <linkul public>
2. Apasă iconița extensiei, apoi „Pornește analiza”. Se deschide o filă eMAG în fundal: loghează-te acolo, în contul tău.
3. Așteaptă să se termine (minute). Compară cifra mare cu totalul tău din „Comenzile mele” de pe eMAG.
4. Dacă ceva nu merge sau cifrele diferă, scrie-mi ce ai văzut. Fără numere de comandă și fără fișierele descărcate din extensie.
Extensia nu trimite nimic nicăieri; ștergi tot cu „Șterge datele” sau dezinstalând-o.
```

Mesajul e o propunere: Robert îl poate scrie în tonul lui.

## 15. Ce trebuie să rămână adevărat

Aceeași afirmație despre date apare în mai multe locuri; la o schimbare (ce citește, ce păstrează, ce permisiuni, ce rețea) se actualizează toate, în același pas:

1. [CONFIDENTIALITATE-EXTENSIE.md](CONFIDENTIALITATE-EXTENSIE.md), cu comentariile `temei`;
2. descrierea lungă (§3) și răspunsurile din formularul de date (§7);
3. justificările din §5 și §6 și instrucțiunile din §9;
4. întrebările frecvente din pagina extensiei (`extensie/src/aplicatie.html`);
5. secțiunea „Extensia Chrome” din [SECURITY.md](../SECURITY.md) și din [README.md](../README.md);
6. `tests/test_garda_extensie.py` (manifestul și rețeaua).

## 16. Surse oficiale (citite pe 14 oct. 2026)

- Înregistrarea dezvoltatorului (taxa unică, e-mailul care nu se mai schimbă): https://developer.chrome.com/docs/webstore/register
- Recenzia (de obicei câteva zile, până la câteva săptămâni): https://developer.chrome.com/docs/webstore/review-process
- Imaginile magazinului: https://developer.chrome.com/docs/webstore/images
- Câmpurile de confidențialitate: https://developer.chrome.com/docs/webstore/cws-dashboard-privacy
- Limited Use (declarația din politică): https://developer.chrome.com/docs/webstore/program-policies/limited-use
- User Data FAQ (politica de confidențialitate, dezvăluirea din produs): https://developer.chrome.com/docs/webstore/program-policies/user-data-faq
- Trader / non-trader: https://developer.chrome.com/docs/webstore/program-policies/trader-disclosure
- Politicile programului (permisiuni înguste, fără cod de la distanță, metadate): https://developer.chrome.com/docs/webstore/program-policies/policies
- Actualizarea politicilor din 1 iul. 2026 (date strict necesare, dezvăluire vizibilă, aplicare din 1 aug. 2026): https://developer.chrome.com/blog/cws-policy-updates-2026
- Limitele `name` (75) și `description` (132): https://developer.chrome.com/docs/extensions/reference/manifest/name și https://developer.chrome.com/docs/extensions/reference/manifest/description
- Avertismentele permisiunilor: https://developer.chrome.com/docs/extensions/reference/permissions-list
- `chrome.storage` (ștergerea la dezinstalare, golirea sesiunii): https://developer.chrome.com/docs/extensions/reference/api/storage

Ce n-am putut confirma dintr-o pagină oficială: etichetele exacte ale tipurilor de date și ale celor trei certificări din dashboard (pagina oficială le arată doar ca imagine) și suma taxei de înregistrare (documentația nu o scrie).

# Snow Globe în extensie și extensia în portofoliu

## Cererea și responsabilitățile

Robert a cerut pe 8 noiembrie 2026 firma Snow Globe în partea de jos a aplicației și prezentarea proiectului pe site, inclusiv faptul că firma poate dezvolta extensii browser pentru companii. A autorizat explicit coordonarea cu chatul care lucrează la Snow Globe.

- Chatul extensiei, „Propune idei pentru extensia Chrome”, deține numai acest depozit și propunerea pentru subsolul extensiei.
- Chatul „Verifică verificarea Google Business”, ID `01a1ba21-da8c-7f12-bba6-7f24f194a6e6`, lucrează în SnowGlobe și deține exclusiv portofoliul, serviciile și capturile acelui site.
- Mesajele de coordonare au fost schimbate; fiecare chat păstrează modificările în propriul proiect. Lucrările de publicare/indexare deja în curs în SnowGlobe continuă separat.

## Deja decis și verificat

- Marca oficială: Snow Globe Solutions; forma scurtă: Snow Globe; domeniu canonic: `https://snowglobe.ro/`, confirmate din `SnowGlobe/config/business.json` de chatul proprietar.
- Autorul extensiei rămâne Robert Pop, conform E15; numele proiectului, licența GPL-3.0 și neafilierea eMAG se păstrează.
- Versiunea 1.1.0 și commit-ul `73369ca60966ee608a2eaa102e9fd6db32067da4` au toate cele cinci workflow-uri CI trecute; pachetul instalat nu este modificat de machetă.
- Portofoliul Snow Globe este un registru comun pentru home și pagina Proiecte, în RO/EN/HU. Chatul site-ului pregătește al treilea proiect ca produs propriu/extensie Chrome și leagă oferta de pagina existentă Aplicații web.
- Extensia nu este încă disponibilă în Chrome Web Store. Linkul public utilizabil este depozitul `https://github.com/poprobert0412/cheltuieli-emag`; nu se inventează un URL de instalare sau o relație comercială cu eMAG.

## APROBAT și integrat — subsolul extensiei

Robert a aprobat explicit pe 08.11.2026: „Da, integrează această variantă”. Textul integrat este **Un proiect Snow Globe**, cu „Snow Globe” ca link spre domeniul canonic, după rândul de copyright, jos de tot. Linkul deschide o filă nouă, fără opener și fără referrer. Marca nu se traduce automat.

Macheta aprobată folosea DOM-ul și CSS-ul reale din build-ul 1.1.0. Rândul de marcă este acum integrat în surse și în folderul încărcat în Chrome, cu o țintă tactilă de 44 px; conturul roșu și cifra 1 au existat numai în capturile pentru aprobare.

Galerie finală: `docs/extensie/capturi/2026-11-08-snowglobe/subsol-implementat.html`; propunerea inițială rămâne în `aprobare-subsol.html`. Include comparații înainte/după la 1440 și 320 px, în temele luminoasă și întunecată. Datele și profilul de browser sunt de demonstrație, fără acces la contul real.

Regula aplicabilă: `~/.codex/rules/capturi-interfata.md`, „Orice text nou [...] apare întâi într-o captură a ecranului lui [...] În cod și în publicare intră doar după «da»-ul lui”. Aprobarea concretă a rândului a fost primită înaintea integrării.

Integrarea este în `extensie/src/aplicatie.html`, cu stil minim în `extensie/src/extensie.css`. Nu adaugă permisiuni, cereri automate sau transmitere a istoricului către Snow Globe. Panoul de produs, exportul PNG și site-ul desktop rămân în afara schimbării aprobate.

## Captura pentru Snow Globe

Fișierul `docs/extensie/capturi/2026-11-08-snowglobe/raport-demo-1.1.0-light-1440.png` este capturat efectiv în Edge, la 1440×900, din versiunea 1.1.0. Se văd versiunea, cele șase file și bannerul cu date inventate. Nu este retușat și nu conține date din cont. Calea absolută a fost transmisă chatului Snow Globe; imaginea are deja raportul 16:10 folosit de cadrul existent al portofoliului.

Descrierea proiectului poate folosi numai funcțiile implementate: raportul cheltuielilor, calcul după reduceri și retururi, filtrarea Black Friday cu date și ore, bugete, urmărirea retururilor, etichete, bilanț PNG și comparația produsului cu istoricul propriu. Nu există monitorizare automată a prețurilor sau alerte. Stocarea și calculele sunt locale; nu se prezintă eMAG drept client sau partener.

## APROBARE — site și publicare

Chatul Snow Globe prezintă separat textele și capturile pentru home, Proiecte și modificarea serviciului existent, în toate limbile afectate. Nu introduce prețuri, promisiuni sau pagini noi necerute. După alegerea lui Robert, verifică integrarea conform instrucțiunilor locale ale site-ului.

Cererea de branding nu autorizează automat un nou commit/push în acest depozit sau un nou deploy Snow Globe. Ultimele aprobări de publicare priveau corecțiile CI deja publicate. Nu se schimbă metadatele magazinului sau versiunea extensiei înaintea definirii pachetului final.

## Verificarea machetei

Parser JS trecut; 4/4 combinații de lățime și temă fără scroll orizontal; destinația, rel, translate, focusul și înălțimea de 44 px verificate. Zero cereri externe și zero erori observate. Browserul și profilul temporar se închid la final. Aceste probe verifică macheta, nu declară o integrare în aplicația instalată.

## Verificarea implementării

- Build strict trecut; 106 fișiere în pachet, fără permisiuni sau dependențe noi; versiunea rămâne 1.1.0, încă nelansată în magazin.
- 855/855 teste unitare, 7/7 probe demo; zero eșecuri și teste sărite. Loguri: `logs/functii-2026-11-08/_meta/snowglobe-unit.log` și `snowglobe-demo.log`.
- 4/4 combinații vizuale (320/1440 px, luminos/întunecat), toate cele șase file și ecranul de start verificate pe pachetul final. Linkul se deschide în filă nouă, fără opener/referrer; destinația a fost interceptată local pentru probă. Zero cereri automate externe și zero erori observate.
- Validatorul de build confunda navigarea prin linkuri cu încărcarea resurselor; acum permite generic linkuri HTTPS izolate și continuă să respingă resurse externe, inclusiv în SVG. Testul de regresie a fost întâi roșu, apoi verde; fără excepție pentru domeniul firmei.
- Review `verifica-cod` pe diff și apelanți: nicio constatare deschisă după păstrarea verificării `xlink:href`; zero comentarii `shortcut:` noi. Încărcare presupusă: build local pe fișierele controlate ale extensiei, câte o pagină deschisă de utilizator. Nu există server comun sau procesare suplimentară a comenzilor.
- Folderul instalat a fost actualizat numai cu cele două fișiere vizuale; 106/106 fișiere sunt identice prin SHA-256 cu build-ul final. Copiile anterioare sunt în `logs/functii-2026-11-08/_meta/snowglobe-installed-before/`.
- Arhivă: `extensie/build/snowglobe-2026-11-08/cheltuieli-emag-1.1.0.zip`; SHA-256 `1bb98c968c306d6a1342eee4dca8afbb5dd40d3234ce80fff06be4a046b37841`. Pachetul inițial și dovezile CI pentru `73369ca` rămân separate; nu se afirmă că noul pachet este cel publicat anterior.
- Browserele temporare au fost închise. Contul real nu a fost recitit pentru această schimbare de subsol; verificarea anterioară a funcțiilor rămâne documentată separat. În profilul Chrome al lui Robert este necesară reîncărcarea extensiei pentru a vedea noul subsol.
- Nu s-a făcut commit/push nou și nu s-a publicat în magazin; integrarea pe site este în sarcina chatului Snow Globe.

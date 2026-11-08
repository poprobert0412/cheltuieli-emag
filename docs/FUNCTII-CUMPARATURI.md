# Cumpărăturile din extensie

Implementare locală, 8 noiembrie 2026. Raportul existent rămâne prima filă. Funcțiile folosesc ultima analiză salvată; sumele nu se actualizează automat din cont.

## Black Friday: ce trebuie completat

Pentru **bilanțul comenzilor deja făcute**, nu trebuie adăugat niciun produs sau buget. Datele și orele delimitează evenimentul; comenzile vin din analiza contului. Intervalul este editabil pentru alte campanii sau ediții, fără a schimba algoritmul.

**Lista, bugetul și prețurile-țintă sunt opționale**, pentru cumpărături viitoare. Bugetul limitează valoarea produselor bifate în listă. Prețul-țintă este suma pe care utilizatorul ar accepta să o plătească; interfața compară reperul cu prețul observat/salvat. Nu reprezintă abonarea la o alertă și nu produce cumpărături automate.

Panoul compară prețul curent cu prețurile propriilor cumpărături păstrate, după reduceri. [Pricy](https://www.pricy.ro/extensie) oferă istoric de prețuri din magazine, alternative între magazine și alerte de preț (funcții publice verificate la 8 noiembrie 2026). Extensia de aici urmărește cheltuielile, retururile și bugetele personale; nu construiește un istoric al pieței și nu înlocuiește acele alerte.

## Folosire

1. **Black Friday:** alege datele, orele și bugetul, adaugă produse sau salvează-le din panoul Chrome. Intervalul aprobat este 6 noiembrie 2026, 07:15 → 7 noiembrie, 00:00, în ora României; începutul intră, sfârșitul nu intră. Bifează ce intră în buget; fiecare produs poate avea un preț observat și o țintă. Bilanțul folosește momentul comenzii și retururile cunoscute în ultima analiză, inclusiv retururile ulterioare intervalului.
2. **Panoul Chrome:** deschide un produs pe `www.emag.ro` și apasă iconița extensiei. Panoul citește numai după clic. Pe alte pagini, iconița deschide raportul. „Citește produsul” reia citirea după navigare. Lipsa sau ambiguitatea prețului rămâne explicită.
3. **Buget:** alege anul și luna sau „Tot anul”, apoi suma proprie. Anul curent este disponibil și înaintea primei comenzi; anii bugetelor salvate rămân accesibili. Gol elimină bugetul; zero este un buget valid. Comenzile încă pe drum sunt separate de plătit efectiv.
4. **Retururi:** vezi retururile fără rezultat ori fără sumă de rambursare, cu pașii disponibili. În analiza reală poți deschide pagina eMAG; demo nu navighează către identificatori fictivi.
5. **Etichete:** numește scopul unei cumpărături și filtrează după el. Etichetele nu modifică încadrarea automată sau totalurile.
6. **Bilanț:** alege anul, verifică previzualizarea și descarcă PNG-ul. „Ascunde suma” scoate suma și din imagine, și din descrierea accesibilă. Imaginea nu include numere de comandă sau produse.

## Date și limite

- Lista, intervalul, țintele, bugetele și etichetele sunt criptate în browser, separat de analiză. O analiză nouă le păstrează. „Șterge datele” elimină toate aceste date și cheia; este disponibil și înaintea primei analize.
- Demo folosește comenzile inventate ale raportului existent; modificările lui se pierd la închidere și nu ajung în datele reale.
- Potrivirea panoului este după denumirea integrală, cu spațiile normalizate și fără diferențe de majuscule. Nu combină culori, capacități ori dimensiuni. Nu este un minim al pieței.
- Prețul personal pe produs include reducerile alocate, fără transport. Pentru mai multe bucăți este media rotunjită la ban; totalul liniei rămâne exact. Două cumpărări cu prețuri diferite în aceeași zi nu sunt ordonate arbitrar drept „ultima”.
- O analiză veche fără comenzi brute oferă numai detaliul existent; nu se inventează luni ori produse. Datele din cont se reîmprospătează printr-o analiză nouă.
- O comandă fără oră precisă nu intră în bilanțul Black Friday și apare separat ca oră lipsă. Orele locale ambigue sau inexistente la schimbarea orei sunt refuzate; bugetele lunare/anuale păstrează selecția calendaristică existentă.
- Preferințele vechi trec la schema 2 fără pierderea listei, etichetelor sau bugetelor. Datele proprii se păstrează; dacă orele configurate nu formează un interval valid pentru ele, interfața cere completarea orelor.
- Nu există monitorizare automată a prețurilor, notificări, servicii plătite sau stocare în cloud.

## Pentru dezvoltare

`config/black-friday.json` furnizează perioada inițială; schimbarea ei nu suprascrie preferințele salvate. Bugetele implicite sunt nesetate. `extensie/scripts/scrie_demo_cumparaturi.py` generează datele brute demo din același generator ca raportul; testul `tests/test_shopping_demo_source.py` detectează abaterea.

Build-ul strict verifică toate paginile HTML, inclusiv panoul. Permisiunile sunt `storage`, `scripting`, `sidePanel` și gazda unică eMAG. Extensia se testează nativ într-un profil Edge separat, cu pagini eMAG inventate și rețeaua blocată; profilul personal nu este folosit.

Acceptanța autorizată pe cont real rulează separat prin `node extensie/scripts/cont_real.mjs acceptanta`. `EXT_DIST_DIR` selectează build-ul (implicit `extensie/dist`), `EMAG_PROFILE_DIR` profilul dedicat al programului (implicit `.profil_browser`), iar `EMAG_ACCEPTANCE_PRODUCT_URL` produsul real ales pentru panou. Runnerul copiază profilul opac, verifică cele șase funcții, colectează din nou cu Python și compară datele și calculele. Dacă e necesar login, Robert îl face în fila eMAG deschisă; programul nu completează credențiale. Preferințele sunt restaurate, copia este eliminată la final, iar rapoartele și exporturile reale rămân exclusiv în `iesiri/acceptanta/`, ignorat de Git. Un pas blocat sau eșuat înseamnă cod de ieșire diferit de zero. Conform E25, commit-ul și push-ul așteaptă această acceptanță.

Verificările suplimentare de accesibilitate sunt în `extensie/tests/browser/shopping_surfaces.test.js` și `sidepanel_accessibility.test.js`. Cer `AXE_CORE_PATH` către axe-core instalat separat și `EXT_DIST_DIR` către build-ul verificat. Nu fac parte din `npm run verify`; raportul `docs/implementare-2026-11-08/ui-motoare.md` păstrează rezultatele și limita CSP a widgetului nativ WebKit. Testele native ale extensiei rămân cele Chromium din `verify`.

Commit-ul salvează versiunea codului în istoricul local; push-ul o trimite pe GitHub. Aceste acțiuni nu reîncarcă extensia instalată și nu publică o versiune în Chrome Web Store. Capturile de verificare rămân locale, conform deciziei E14.

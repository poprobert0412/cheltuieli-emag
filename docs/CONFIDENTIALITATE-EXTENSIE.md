# Politica de confidențialitate: Cât am cheltuit pe eMAG

Ultima actualizare: 16 octombrie 2026. Se aplică extensiei Chrome, versiunea 0.1.0. Text aprobat de Robert pe 16 octombrie 2026 (E20).

**Cât am cheltuit pe eMAG** este un proiect independent al lui Robert Pop, gratuit pentru utilizator. Nu este afiliat cu eMAG. Contactul și raportarea problemelor sunt disponibile în [depozitul proiectului](https://github.com/poprobert0412/cheltuieli-emag); nu publica acolo comenzi sau fișiere cu datele tale. Vulnerabilitățile se raportează conform SECURITY.md. <!-- temei: docs/DECIZII.md E15/E20; extensie/src/aplicatie.html antet/subsol; SECURITY.md -->

### Ce citește și de ce

Doar după ce apeși „Pornește analiza”, extensia deschide o filă de lucru pe www.emag.ro și citește istoricul comenzilor și retururilor pentru a calcula raportul de cheltuieli. Dacă trebuie să te autentifici, o faci tu în pagina site-ului. Extensia nu completează și nu extrage parola sau codul 2FA și nu are acces la API-ul pentru citirea cookie-urilor. <!-- temei: extensie/src/ecrane/start_screen.js; extensie/src/colectare/work_tab.js; extensie/src/colectare/session_check.js; extensie/manifest.json -->

Paginile sunt procesate în memorie și pot conține date personale afișate de site. Extensia nu extrage intenționat numele cumpărătorului, adresa, telefonul, e-mailul, datele cardului ori codurile de ridicare. HTML-ul paginilor nu se păstrează. <!-- temei: extensie/src/calcul/html_lines.js; extensie/src/colectare/page_fetcher.js; extensie/src/calcul/order_parser.js; extensie/src/calcul/return_parser.js; extensie/src/stocare/last_analysis.js -->

Se extrag numerele și datele comenzilor, vânzătorii, produsele și cantitățile, statusurile, sumele, reducerile, voucherele, transportul și taxele. Pentru retururi se extrag identificatorii și căile paginilor, comenzile și produsele asociate, statusurile și informațiile despre restituire. Unele texte sunt preluate din pagini; dacă structura site-ului se schimbă, pot include text nedorit din apropiere. <!-- temei: extensie/src/calcul/models.js; extensie/src/calcul/order_parser.js; extensie/src/calcul/return_parser.js -->

### Ce păstrează și cât timp

Se păstrează local doar ultima analiză reușită: raportul, comenzile și retururile extrase, data, versiunea, pragul ales și jurnalul. O analiză nouă o înlocuiește numai după încheiere și salvare reușită. Jurnalul rulării curente se scrie pe parcurs; după o eroare poate rămâne până la rularea următoare sau ștergere. <!-- temei: extensie/src/stocare/last_analysis.js saveLastAnalysis; extensie/src/stocare/run_log.js RunLog; extensie/src/rulare/run_pipeline.js -->

Analiza și jurnalul sunt criptate cu AES-GCM. Cheia criptografică este generată local și păstrată separat, în spațiul extensiei din browser, fără a fi transmisă autorului. Această protecție nu blochează accesul unei persoane care controlează profilul browserului sau folosește extensia deja deschisă. Nu există o parolă suplimentară pentru raport. <!-- temei: extensie/src/stocare/storage_encryption.js encryptRecord/decryptRecord; extensie/src/stocare/key_store.js createKeyStore; extensie/src/stocare/private_storage.js ensureKey; docs/DECIZII.md E18 -->

Evidența unei analize în curs rămâne în memoria sesiunii browserului. Preferința de temă se salvează separat și nu conține istoricul cumpărăturilor. Nu se folosește sincronizarea datelor extensiei prin contul Google. <!-- temei: extensie/src/stocare/run_lock.js; interfata/assets/app-theme.js; extensie/manifest.json -->

### Rețea și destinatari

Autorul nu primește datele citite și nu are server de colectare, telemetrie sau reclame. Extensia solicită pagini de pe www.emag.ro prin fila de lucru. Browserul folosește sesiunea ta pentru aceste cereri. Site-ul și serviciile încărcate de paginile lui primesc cererile unei vizite obișnuite; acestea sunt guvernate de politicile lor. Instalarea și actualizările prin Chrome Web Store sunt administrate de Google. <!-- temei: extensie/src/colectare/page_functions.js; extensie/src/colectare/work_tab.js; extensie/src/aplicatie.html CSP; extensie/manifest.json; https://developer.chrome.com/docs/extensions/develop/distribute/host -->

Datele sunt folosite numai pentru raport, nu pentru publicitate, vânzare, evaluarea bonității sau acordarea de credite. Utilizarea lor respectă politica Chrome Web Store pentru datele utilizatorilor, inclusiv cerințele Limited Use. <!-- temei: docs/DECIZII.md E20; https://developer.chrome.com/docs/webstore/program-policies/limited-use; https://developer.chrome.com/docs/webstore/program-policies/user-data-faq -->

### Ștergere și exporturi

„Șterge datele” elimină analiza, jurnalul și cheia locală. Dezinstalarea elimină stocarea extensiei. Preferința de temă și sesiunea contului eMAG sunt separate de analiza salvată. Ștergerea istoricului general de navigare nu este echivalentă cu ștergerea datelor extensiei. <!-- temei: extensie/src/stocare/last_analysis.js deleteAllData; extensie/src/stocare/private_storage.js clear; interfata/assets/app-theme.js; https://developer.chrome.com/docs/extensions/reference/api/storage -->

Exporturile HTML, CSV, JSON și TXT sunt necriptate, sunt salvate la cererea ta în folderul de descărcări și nu sunt șterse de extensie. Pot conține istoricul cumpărăturilor și numere de comandă; verifică-le înainte să le distribui. <!-- temei: extensie/src/exporturi/export_files.js REAL_FILES; extensie/src/exporturi/descarcare.js; extensie/src/aplicatie.html descărcări -->

Modificările acestei politici sunt indicate prin data actualizării și istoricul fișierului din depozitul proiectului. <!-- temei: istoricul docs/CONFIDENTIALITATE-EXTENSIE.md din depozitul proiectului -->

# Istoricul versiunilor extensiei

Ce s-a schimbat în fiecare versiune a extensiei Chrome „Cât am cheltuit pe eMAG”, cea mai nouă sus. Versiunea extensiei are o singură sursă, `manifest.json`, și nu e cea a programului (vezi [CHANGELOG.md](../CHANGELOG.md) din rădăcină). Fiecare versiune are o secțiune `## X.Y.Z — AAAA-LL-ZZ`.

## 1.1.0 — 2026-11-08

- Listă Black Friday cu ținte, selecție, buget și bilanț al intervalului editabil, cu ore în fusul Europe/Bucharest; începutul este inclus, sfârșitul este exclus.
- Panou pe pagina de produs eMAG: preț curent, ultima cumpărare și minim personal, cu potrivire strictă după denumire; ținte salvate în listă.
- Bugete lunare/anuale cu comenzile în curs separate, retururi de urmărit și etichete personale.
- Bilanț anual PNG din previzualizare, cu opțiunea de ascundere a sumei.
- Preferințele sunt criptate local, actualizate atomic între pagini și eliminate de „Șterge datele”; demo rămâne în memorie.
- Permisiune nouă `sidePanel`, fără gazde noi; calculele raportului păstrează paritatea cu Python.
- Subsolul paginii are rândul „Un proiect Snow Globe”, aprobat pe 8 noiembrie 2026; linkul spre `https://snowglobe.ro/` se deschide într-o filă nouă, fără opener și referrer, iar build-ul refuză orice alt link extern neizolat.

## 1.0.0 — 2026-10-20

Prima versiune stabilă, cu același comportament verificat în 0.1.0 și textele aprobate pe 16 octombrie 2026.

- Numele rămâne „Cât am cheltuit pe eMAG”, creat de Robert Pop.
- Analiza rulează local în browser, cu aceleași calcule ca programul Python.
- Ultima analiză și jurnalul rămân criptate local; „Șterge datele” elimină datele și cheia.
- Exporturile HTML, CSV, JSON și TXT rămân necriptate, iar raportul demonstrativ folosește date inventate, fără cont eMAG.

## 0.1.0 — 2026-10-16

Prima versiune, pregătită pentru publicare sub licența GPL-3.0.

- Un clic pe iconița extensiei deschide pagina ei, fără fereastră pop-up.
- „Pornește analiza” deschide o filă eMAG în fundal. Te loghezi tu în ea (extensia așteaptă cel mult 10 minute), iar extensia citește comenzile și retururile din cont, câte 3 pagini odată, apoi închide fila.
- Calculează în browser aceeași analiză ca programul: cât ai plătit efectiv pe ce ai păstrat, după vouchere și reduceri, pe categorii, ani, vânzători și produse, cu istoricul prețurilor și avertismentele. Calculul e portat din program și comparat automat cu el pe aceleași intrări; pe contul autorului, la 14 oct. 2026, extensia a citit și a calculat aceleași cifre ca programul.
- Păstrează criptat ultima analiză și jurnalul, fără HTML-ul paginilor. Cheia rămâne locală, fără parolă suplimentară; „Șterge datele” elimină și cheia. Datele vechi se migrează la citire, iar o migrare eșuată păstrează datele și afișează eroarea.
- Temă automată, luminoasă și întunecată, cu alegerea păstrată la redeschidere.
- Instrucțiunile din raport și din exportul HTML corespund extensiei; configurările și comenzile programului pentru calculator rămân în contextul lui.
- Descarcă `raport.html`, `produse.csv`, `istoric_preturi.csv`, `analiza.json`, `comenzi.json`, `retururi.json` și `jurnal.txt`.
- „Încearcă cu date inventate” arată un raport de probă, fără cont și fără login.
- „Oprește” întrerupe analiza. O singură analiză rulează odată, chiar dacă pagina extensiei e deschisă în mai multe file.
- Cere doar două permisiuni, `storage` și `scripting`, plus accesul la `www.emag.ro`. Nu încarcă cod de pe internet și nu trimite istoricul cumpărăturilor autorului.
- Limite: doar Chrome 120 sau mai nou, doar `emag.ro`, doar în română, fără regulile personale de categorii.

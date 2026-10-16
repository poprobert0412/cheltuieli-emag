# Istoricul versiunilor extensiei

Ce s-a schimbat în fiecare versiune a extensiei Chrome „Cât am cheltuit pe eMAG”, cea mai nouă sus. Versiunea extensiei are o singură sursă, `manifest.json`, și nu e cea a programului (vezi [CHANGELOG.md](../CHANGELOG.md) din rădăcină). Fiecare versiune are o secțiune `## X.Y.Z — AAAA-LL-ZZ`.

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

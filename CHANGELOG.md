# Istoricul versiunilor

Ce s-a schimbat în fiecare versiune a programului Cheltuieli eMAG, cea mai nouă sus. Fiecare versiune are o secțiune
`## X.Y.Z — AAAA-LL-ZZ`, scrisă înainte de lansare: textul ei apare în pagina lansării de pe GitHub și în aplicație, la
„Ce e nou”, ca text simplu (fără formatare), deci rândurile ei sunt fraze scurte, fără titluri `##`.

## 1.0.2 — 2026-10-07

Reparații. Cuprinde tot ce era în 1.0.1, o versiune care n-a fost oferită nimănui.

- Aplicația locală: dacă nu se încarcă o parte a paginii care nu ține de pornire (de exemplu întrebările frecvente sau istoricul), restul paginii pornește, în loc să rămână la „Se verifică aplicația…”.
- În raport, coloana aleasă cu tastatura în graficul pe ani rămâne aleasă, cu explicația deschisă, când fereastra își schimbă mărimea sau când faci zoom.
- Documentația: fiecare decizie la care trimite codul are acum rândul ei în docs/DECIZII.md.
- La actualizare, rapoartele tale și sesiunea eMAG rămân neatinse, iar regulile din config/categorii.personal.json rămân; modificările făcute direct în config/categorii.json se pierd la actualizare.

## 1.0.1 — 2026-10-06

Reparații.

- Aplicația locală: dacă nu se încarcă o parte a paginii care nu ține de pornire (de exemplu întrebările frecvente sau istoricul), restul paginii pornește, în loc să rămână la „Se verifică aplicația…”.
- În raport, coloana aleasă cu tastatura în graficul pe ani rămâne aleasă, cu explicația deschisă, când fereastra își schimbă mărimea sau când faci zoom.
- Documentația: fiecare decizie la care trimite codul are acum rândul ei în docs/DECIZII.md.
- La actualizare, rapoartele tale și sesiunea eMAG rămân neatinse, iar regulile din config/categorii.personal.json rămân; modificările făcute direct în config/categorii.json se pierd la actualizare.

## 1.0.0 — 2026-10-05

Prima versiune numerotată.

- Cât ai plătit efectiv: din „Total plătit eMAG” al fiecărei comenzi livrate sau ridicate, după vouchere și reduceri, cu transportul și taxele, minus banii primiți înapoi la retururi.
- Produsele și comenzile din raport se deschid cu un clic pe eMAG, ca să verifici repede orice cifră.
- Istoricul prețurilor: pentru același produs cumpărat de mai multe ori vezi cum s-a schimbat prețul.
- Aplicația locală cu un singur buton: pornești analiza și deschizi rapoartele vechi dintr-o pagină care rulează doar pe calculatorul tău.
- Merge pe Windows, macOS și Linux fără Python instalat: la prima pornire programul își aduce singur, în folderul lui, tot ce îi trebuie: uv, verificat cu amprentă SHA-256, apoi Python și pachetele, la versiuni fixate, iar dacă nu ai Edge sau Chrome, și Chromium.
- Actualizări din aplicație: programul îți spune când apare o versiune nouă și o instalează doar când apeși „Actualizează acum”, după ce verifică amprenta arhivei; dacă ceva nu merge, revine la versiunea veche, iar o actualizare întreruptă (curent căzut, fereastră închisă) o desface singur la pornirea următoare, apoi merge mai departe. Rapoartele tale și sesiunea eMAG rămân neatinse, iar regulile din config/categorii.personal.json rămân; modificările făcute direct în config/categorii.json se pierd la actualizare.
- Verificări automate la fiecare schimbare: teste pe Windows, macOS și Linux, pornirea de la zero ca un utilizator nou, căutarea de parole și date personale scăpate în cod și analiza de securitate CodeQL. O versiune nouă se publică doar după ce trec testele și pornirea de la zero pe toate trei sistemele; apoi actualizarea la ea se încearcă de la o copie veche și, când există, de la versiunea publicată înainte, iar dacă nu reușește, versiunea e retrasă și aplicația n-o mai oferă.

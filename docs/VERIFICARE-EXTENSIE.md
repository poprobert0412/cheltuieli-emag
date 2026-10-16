# Verificarea extensiei — 16 octombrie 2026

Versiunea verificată: **0.1.0 — Cât am cheltuit pe eMAG**. Acest raport descrie verificările locale; nu confirmă aprobarea sau publicarea în Chrome Web Store.

## Funcționalitate

- `npm run verify`: **795 teste unitare, 493 teste de paritate cu Python, 76 teste în browser; 1.364 trecute, zero eșecuri și zero teste sărite**.
- Build strict: 83 de fișiere, fără importuri sau resurse lipsă, cu manifestul în rădăcina arhivei.
- Analiza și jurnalul: criptare AES-GCM, migrare a datelor vechi, recuperare după date alterate sau cheie lipsă, ștergere și protecție împotriva scrierilor întârziate.
- Profil temporar de browser: raport și jurnal identice după repornire, două file, ștergere persistentă. La închiderea browserului au fost înregistrate separat patru diagnostice „The browser is shutting down”; sesiunile active au trecut verificările fără erori.
- Tema luminoasă/întunecată: alegerea persistă la reîncărcare și repornire; capturile finale au fost verificate pe desktop și la lățimea de 390 px.
- Contextul extensiei adaptează instrucțiunile raportului și exportului HTML; cifrele și datele JSON rămân identice. Mesajele brute din analiza comună sunt păstrate, inclusiv eventualele referințe la programul pentru calculator.

## Securitate

Audit local al extensiei și al resurselor comune incluse în pachet: **zero vulnerabilități confirmate**. Acesta nu este o certificare și nu acoperă infrastructura eMAG sau browserul în sine.

| Verificare | Rezultat |
|---|---|
| Semgrep 1.181.0, reguli OWASP și secrete | 113 fișiere, 105 reguli, zero constatări și zero erori de parsare |
| Gitleaks 8.30.1, surse și istoric relevant, cu redactare | Zero secrete detectate |
| npm audit, complet și fără dependențe de dezvoltare | Zero vulnerabilități raportate |
| Contracte de criptare | 14 din 14 trecute; autentificarea numelui intrării și cheia greșită probate separat |
| Export HTML în Edge, contexte desktop și extensie | Date ostile rămân text, date JSON identice, zero cod injectat executat, zero cereri de rețea și zero erori de pagină |

Cheia criptării rămâne în profilul local al browserului. Persoana care controlează profilul sau folosește extensia deschisă poate vedea raportul. Exporturile sunt necriptate, conform [politicii de confidențialitate](CONFIDENTIALITATE-EXTENSIE.md).

OSV nu a fost rulat, deoarece unealta nu era disponibilă. Testele și auditul acestei sesiuni au folosit date inventate, fără acces la conturi sau comenzi reale. Testarea reală din 14 octombrie, documentată în README, rămâne o verificare separată.

## Publicare

Robert a aprobat păstrarea GPL, numele, textele, imaginea promoțională 2, lansarea publică și efectuarea publicării (E15–E22). Materialele și pașii sunt în [MAGAZIN-EXTENSIE.md](MAGAZIN-EXTENSIE.md). Starea din consola Google și pagina publică trebuie verificate separat; un ZIP construit sau codul publicat pe GitHub nu înseamnă că extensia a fost trimisă ori aprobată în magazin.

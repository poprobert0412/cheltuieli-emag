# Întrebări frecvente

Răspunsurile scurte. Pașii complecți sunt în [ghidul de instalare și folosire](INSTALARE.md).

<details>
<summary><strong>De ce e nevoie de login?</strong></summary>

Istoricul de comenzi se vede doar după autentificare. Programul citește aceleași pagini pe care le vezi tu, în contul tău. Te loghezi tu, în fereastra browserului: parola și codul 2FA nu trec prin program, iar el nu le tastează și nu le salvează. Sesiunea rămâne în `.profil_browser/`, ca la rulările următoare să nu mai fie nevoie de login cât timp eMAG nu o expiră.
</details>

<details>
<summary><strong>E permis de eMAG?</strong></summary>

Nu știm. Proiectul nu are legătură cu eMAG, iar accesul automat poate fi contrar termenilor lor. Îl folosești pe răspunderea ta, doar pe contul tău. Programul cere paginile câte 3 odată, fără pauze între ele, deci nu rula analiza de zeci de ori pe zi. eMAG poate oricând să limiteze accesul automat sau să blocheze contul.
</details>

<details>
<summary><strong>De ce cifrele diferă de ce văd pe eMAG?</strong></summary>

Cifra mare pornește de la „Total plătit” al fiecărei comenzi livrate sau ridicate (după vouchere și reduceri, cu transportul și taxele) și scade banii primiți înapoi la retururi; anulatele și ce n-a ajuns încă nu intră. Un retur cu voucher sau sold eMAG nu se scade, fiindcă voucherul scade comanda în care îl folosești. Extrasul bancar poate da alt total: plăți în rate sau cu card cadou, bani întorși pe card mai târziu, comenzi anulate plătite și apoi rambursate. Dacă o diferență nu se explică așa, deschide comanda din link și compară-o cu raportul; dacă pare o greșeală a programului, deschide un Issue (fără date personale).
</details>

<details>
<summary><strong>Cum actualizez?</strong></summary>

Din aplicație: când apare „Versiune nouă”, apeși **„Actualizează acum”**. Programul descarcă versiunea, îi verifică amprenta, înlocuiește doar fișierele lui (rapoartele și sesiunea rămân, iar regulile din `config/categorii.personal.json` rămân; modificările făcute direct în `config/categorii.json` se pierd la actualizare) și repornește; dacă ceva nu merge, revine singur la versiunea veche. Din terminal: `porneste.bat --actualizeaza` sau `./porneste.sh --actualizeaza`. Cu o copie git: `git pull`. Manual: arhiva nouă într-un folder nou, în care copiezi `iesiri/` și `config/categorii.personal.json`; apoi ștergi sesiunea din folderul vechi **înainte** să-l ștergi. Pași exacți: [docs/INSTALARE.md](INSTALARE.md#actualizare).
</details>

<details>
<summary><strong>Merge pe Mac sau Linux?</strong></summary>

Da. macOS: dublu-clic pe `porneste.command` (prima dată aprobi în **Setări de sistem → Confidențialitate și securitate → Deschide oricum**). Linux: `./porneste.sh` din Terminal. Programul își aduce singur Python-ul, deci nu trebuie instalat nimic. Browserul: Chrome sau Edge; dacă nu ai niciunul, programul descarcă o dată Chromium (pe Linux poate cere câteva biblioteci de sistem, iar scriptul îți spune exact ce comandă să rulezi). Pornirea de la zero, demonstrația și aplicația sunt verificate automat pe macOS și Linux; login-ul pe un cont real a fost încercat doar pe Windows. Pași: [docs/INSTALARE.md](INSTALARE.md#2-pornește).
</details>

<details>
<summary><strong>Ce înseamnă fiecare avertisment din raport?</strong></summary>

Fiecare grupă din raport se deschide și are explicația ei, ce să faci și linkuri către comenzile în cauză. Pe scurt: **„lipsește Total plătit”** = pagina comenzii nu arată suma plătită la un vânzător; la un bloc livrat, suma se calculează atunci din componente (produse, reduceri, transport, taxe), fără verificare cu pagina; **„totalul din antet ≠ suma blocurilor”** = cel mai des o comandă cu un bloc anulat, al cărui „Total de plată” rămâne în antet; **„retur cerut, fără rezultat”** = returul nu e finalizat, deci produsul încă se numără ca păstrat; **„retur finalizat fără sumă restituită”** = produsul trece la returnat, iar pentru cât ai cheltuit se scade partea lui plătită (estimare; la voucher sau sold nu se scade nimic). Textele grupelor stau în `config/avertismente.json`.
</details>

<details>
<summary><strong>De ce apare „Necategorizat” și cum adaug o categorie?</strong></summary>

Regulile programului stau în `config/categorii.json` (expresii regulate pe numele produsului, fără diacritice, cu litere mici); prima categorie care se potrivește câștigă. Regulile tale (o categorie nouă, titluri de cărți, modele exacte) le pui în `config/categorii.personal.json`: copiezi `config/categorii.personal.exemplu.json` cu acest nume și adaugi intrările tale; ele se încearcă înaintea celor ale programului, iar fișierul e ignorat de git. Contează unde le scrii: regulile din `config/categorii.personal.json` rămân; modificările făcute direct în `config/categorii.json` se pierd la actualizare. Apoi refaci raportul fără să intri în eMAG: Windows `porneste.bat --din-cache iesiri\<rulare>`, macOS/Linux `./porneste.sh --din-cache iesiri/<rulare>`.
</details>

<details>
<summary><strong>Cum șterg tot?</strong></summary>

Ștergi sesiunea (Windows `sterge_sesiunea.bat`, macOS/Linux `./porneste.sh --sterge-sesiunea`; scrii DA), apoi ștergi folderul programului, cu tot cu `.uv/` și `.venv/`. Pentru rapoartele din `iesiri/` și jurnalele din `logs/` ștergi folderele. Ștergerea sesiunii nu te deloghează de pe eMAG: dacă vrei să închizi o sesiune veche, schimbă parola contului. Pași: [docs/INSTALARE.md](INSTALARE.md#dezinstalare-completă).
</details>

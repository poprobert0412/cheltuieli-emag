# Cum contribui

Mulțumim că vrei să ajuți. Proiectul e mic și lucrează cu date personale (istoricul de cumpărături al cuiva), deci regulile de mai jos sunt mai stricte decât la un proiect obișnuit.

## Înainte de orice

- **Probleme și idei:** deschide un [Issue](../../issues/new/choose) și completează formularul. **Nu atașa și nu lipi date personale**: `comenzi.json`, `retururi.json`, `analiza.json`, conținutul `iesiri/`, `logs/`, `.profil_browser/`, capturi cu comenzi reale. Folosește exemple inventate.
- **Vulnerabilități:** nu le descrie într-un Issue public; vezi [SECURITY.md](SECURITY.md).
- Pentru o schimbare mare, deschide întâi un Issue, ca să nu muncești degeaba.

## Mediu de lucru

Pornește o dată lansatorul (`porneste.bat`, `./porneste.command` sau `./porneste.sh`): pregătește `.uv/` (uv și Python) și `.venv/`. Apoi, din folderul programului:

```
Windows:
.uv\bin\uv.exe pip install --cache-dir .uv\cache --python .venv\Scripts\python.exe --only-binary :all: -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest

macOS / Linux:
.uv/bin/uv pip install --cache-dir .uv/cache --python .venv/bin/python --only-binary :all: -r requirements-dev.txt
.venv/bin/python -m pytest
```

Testele folosesc pagini și comenzi inventate și nu intră în niciun cont. Cele care verifică raportul și interfața pornesc Edge sau Chrome fără fereastră și se sar dacă nu e instalat niciunul. Mai multe detalii: [docs/INSTALARE.md](docs/INSTALARE.md#pentru-programatori).

## Regulile codului

- **Un fișier = o singură treabă, numit după ce face** (`order_parser.py`, `session_cleaner.py`). Fără `utils.py`, `helpers.py`, `common.py`.
- **Antet de 3–8 rânduri la fiecare `.py`** (ce face, ce primește, ce dă înapoi, ce nu e treaba lui) și **docstring la fiecare funcție**. Comentariul spune *de ce*, codul arată *cum*. Când schimbi codul, schimbi și comentariul.
- **Fără valori hardcodate din date reale.** Praguri și limite: constante cu nume, cu un comentariu care spune de ce are acea valoare. Valori care depind de mediu: variabile `EMAG_*`, documentate în `emag_spend/settings.py`. Reguli care depind de produse: date în `config/*.json`, nu în cod.
- **Exemplele și testele folosesc doar date inventate**: niciun nume, adresă, telefon, e-mail, număr de comandă sau produs real din contul cuiva.
- **Testele-gardă nu se ocolesc.** `tests/test_garda_parole.py`, `test_garda_retea.py` și `test_garda_scriere.py` opresc tastarea în pagini, citirea cookie-urilor, modulele de rețea neașteptate și scrierile în afara `iesiri/`, `logs/` și `.profil_browser/`, iar `test_garda_caractere.py` oprește caracterele invizibile (de control, bidi, de lățime zero) în tot ce urcă în depozit. `tests/conftest.py` pune `EMAG_UPDATE_CHECK=0` pentru fiecare test: un test care chiar are nevoie de verificarea versiunii o pornește explicit. Dacă ai nevoie de o excepție, explic-o în pull request: fiecare excepție existentă are un motiv scris în fișierul gărzii (de exemplu actualizarea: rețeaua doar prin `emag_spend/update_http.py`, spre gazdele GitHub fixate acolo, și scrieri doar în `.actualizare/` și în fișierele din lista lansării).
- **Calculele nu se schimbă fără teste** care arată ce se schimbă și de ce.
- Textele pentru utilizator sunt **în română, cu diacritice**. Fișierele `.bat` au sfârșituri de rând CRLF, restul LF, inclusiv `porneste.sh`, `porneste.command` și `instalare/*.sh` (vezi `.gitattributes`). Lansatoarele de macOS și Linux sunt executabile în git: un fișier nou de felul ăsta primește `git update-index --chmod=+x`.
- Versiunea lui uv și a lui Python, plus amprentele SHA-256 ale arhivelor uv, stau doar în `instalare/versiuni.txt`. Când schimbi versiunea uv, pui amprentele noi pentru toate cele șase arhive (Windows, macOS, Linux; x64 și arm64), luate din pagina lansării uv.
- Dependențele rămân fixate la versiuni exacte; adăugarea uneia noi se justifică în pull request.

## Cum lansezi o versiune nouă

Doar pentru cine are drept de scriere în depozit. Utilizatorii primesc versiunea prin butonul „Actualizează acum” din aplicație, deci o lansare greșită ajunge la toți: pașii de mai jos nu se sar.

1. **Alege numărul**, ca versiune semantică `X.Y.Z`: `Z` pentru reparații, `Y` pentru funcții noi, `X` pentru schimbări mari. Numărul crește mereu: aplicația nu instalează o versiune mai veche sau aceeași.
2. **Scrie-l în `emag_spend/version.py`** (`VERSION = "X.Y.Z"`), singurul loc al versiunii.
3. **Adaugă în `CHANGELOG.md`**, deasupra celorlalte, secțiunea `## X.Y.Z — AAAA-LL-ZZ` (cu linie lungă „—” și o dată reală), cu ce e nou pe înțelesul utilizatorului, în fraze scurte, fără alte titluri `##` în ea: textul ajunge în pagina lansării și în „Ce e nou” din aplicație, ca text simplu.
4. **Commit și push** pe `main`; așteaptă testele verzi.
5. **Eticheta:** `git tag vX.Y.Z`, apoi `git push origin vX.Y.Z`. Fără git: pe GitHub, **Actions → Lansare → Run workflow**, ramura `main`, scrii `vX.Y.Z` și apeși **Run workflow**; eticheta trebuie să nu existe deja, iar lansarea o creează pe commit-ul testat al lui `main`.

`lansare.yml` face restul (la fel din buton): rulează întâi, pe commit-ul etichetei, toate testele (`teste.yml`) și pornirea de la zero pe cele trei sisteme (`pornire.yml`), iar dacă oricare pică, nu se publică nimic; se oprește dacă eticheta nu e exact `v` + `VERSION` sau dacă `CHANGELOG.md` nu are secțiunea versiunii; face arhiva `cheltuieli-emag-vX.Y.Z.zip` din conținutul etichetei (`git archive`), cu lista fișierelor programului în `instalare/fisiere.txt`; o verifică cu aceleași reguli pe care le aplică actualizarea (plus sfârșiturile de rând și bitul de execuție al lansatoarelor); publică lansarea cu `SHA256SUMS.txt` și cu „Ce e nou” din `CHANGELOG.md`; apoi testează actualizarea pe Windows, macOS și Linux (`actualizare.yml`: o copie „îmbătrânită” a lansării și, când există, lansarea anterioară, neîmbătrânită, se actualizează din terminal și din aplicație; fișierele programului trebuie să iasă identice cu lansarea, iar datele utilizatorului neschimbate). Dacă testul actualizării nu reușește, jobul „retrage” marchează lansarea ca prerelease, iar aplicația n-o mai oferă: o repari și lansezi o versiune nouă, cu alt număr. Doar rularea din `lansare.yml` retrage: rularea săptămânală doar semnalează o problemă (în fila Actions), la fel cea pornită de mână; dacă una pică pentru o lansare deja publicată, decizi tu dacă o retragi (`gh release edit vX.Y.Z --prerelease`) sau lansezi direct reparația.

Ce să ții minte:

- Arhiva conține doar fișierele urmărite de git la etichetă. Un fișier scos din git dispare la utilizatori la următoarea actualizare (actualizarea șterge ce lipsește din lista nouă, în afară de datele lor).
- `instalare/fisiere.txt` se face la lansare și e în `.gitignore`: nu-l adăuga în git (lansarea se oprește).
- Nu muta și nu refolosi o etichetă publicată. O reparație = o versiune nouă.
- Lansările marcate „draft” sau „pre-release” nu ajung la utilizatori: aplicația întreabă doar de ultima lansare publicată.
- Un fișier al programului poate deveni folder (sau invers) de la o versiune la alta: actualizarea mută întâi din drum ce era al versiunii vechi. Dacă în drum e ceva al utilizatorului, actualizarea se oprește și îi spune ce să mute.

## Ce nu se schimbă între versiuni

După o actualizare, codul deja instalat la utilizatori citește fișierele versiunii noi, iar codul nou citește ce a lăsat cel vechi. Ce e mai jos e contract: o greșeală aici nu se repară cu o versiune nouă, fiindcă pică tocmai codul vechi, deja instalat.

- **Fișierele-contract** (`REQUIRED_FILES` din `emag_spend/update_archive.py`; o arhivă fără oricare dintre ele e refuzată la lansare și la actualizare): `emag_spend/version.py`, `instalare/fisiere.txt`, `ruleaza.py`, `porneste.bat`, `porneste.sh`, `porneste.command`, `instalare/dupa_rulare.bat`, `instaleaza.bat`, `instalare/mediu.bat`, `instalare/mediu.sh`, `instalare/pregatire.sh`, `emag_spend/__init__.py`, `emag_spend/update_recovery.py` și `emag_spend/update_lock.py`. Nu le redenumi și nu le muta: după actualizare, lansatorul vechi cheamă `instalare/dupa_rulare.bat` nou (cu aceleași două argumente: numele lansatorului și codul de ieșire), iar la repornire pornește lansatorul nou, care cheamă `instaleaza.bat` și `instalare/mediu.bat` (Windows) sau `instalare/pregatire.sh` și `instalare/mediu.sh` (macOS, Linux). Lansatoarele rulează recuperarea (`emag_spend/update_recovery.py` cu `emag_spend/update_lock.py`) înaintea pregătirii și `ruleaza.py` o importă înaintea oricărui alt modul, deci acestea două folosesc doar biblioteca standard, iar `emag_spend/__init__.py` rămâne fără importuri.
- **Recuperarea de la pornire:** `porneste.bat`, `porneste.sh` și `porneste.command` rulează `python -m emag_spend.update_recovery` (fără argumente, cu Python-ul din `.venv`, din folderul programului) când există `.actualizare/jurnal.json`, înaintea pregătirii (`instaleaza.bat`, `instalare/pregatire.sh`): pregătirea ar citi altfel `instalare/versiuni.txt` și `requirements.txt` dintr-un arbore amestecat și ar putea opri pornirea înainte ca recuperarea să apuce să ruleze. Ordinea recuperare → pregătire → program nu se schimbă. Codurile de ieșire sunt contract: 0 = nimic de făcut sau revenirea s-a terminat; 1 = recuperarea nu se poate face acum (lansatorul se oprește, cu mesaj); 2 = a primit argumente (nu face nimic). La orice cod în afară de 1, lansatorul pornește din nou de la început, o singură dată, cu semnul `CHELTUIELI_EMAG_DUPA_RECUPERARE` (cel repornit nu mai încearcă recuperarea), fiindcă recuperarea poate să-l fi înlocuit chiar pe el.
- **Jurnalul actualizării** (`.actualizare/jurnal.json`, formatul `JOURNAL_FORMAT` din `emag_spend/update_recovery.py`): o actualizare întreruptă poate fi desfăcută de codul altei versiuni, deci versiunile viitoare trebuie să poată citi formatul de acum. Un format nou primește alt număr și se citește alături de cel vechi, nu în locul lui.
- **Manifestul** (`instalare/fisiere.txt`: câte o cale POSIX relativă pe rând, sortată, LF): versiunea nouă citește manifestul local al celei vechi ca să știe ce poate șterge, iar validatorul versiunii vechi verifică manifestul arhivei noi. Forma lui rămâne citibilă în ambele sensuri.
- **Lacătul** (`.actualizare/lacat`): fișier permanent și gol, blocat de sistem (`msvcrt.locking` pe Windows, `flock` pe macOS și Linux); nu se șterge niciodată și nu se schimbă felul în care e blocat, altfel două versiuni n-ar mai vedea una lacătul celeilalte.
- **Repornirea:** codul 75 (`settings.EXIT_CODE_RESTART`) cere repornirea după o actualizare din aplicație; îl așteaptă `porneste.*` și `instalare/dupa_rulare.bat` din versiunile instalate.
- **Forma lansării:** eticheta `vX.Y.Z`, arhiva `cheltuieli-emag-vX.Y.Z.zip` cu prefixul `cheltuieli-emag-vX.Y.Z/`, `SHA256SUMS.txt` alături și `VERSION = "X.Y.Z"` scris ca text în `emag_spend/version.py`. Nicio cale protejată (datele utilizatorului, lista din `emag_spend/update_recovery.py`) nu apare în arhivă: versiunile instalate ar refuza-o întreagă.

## Pull request

Completează lista din șablon. Pe scurt: testele trec, nu ai date personale, nu ai secrete, documentația e la zi.

Prin trimiterea unui pull request accepți ca modificările tale să fie distribuite sub aceeași licență ca proiectul, **GPL-3.0** (vezi [LICENSE](LICENSE)).

@echo off
rem Ce urmează după ce Python s-a oprit, pentru lansatoarele de pe Windows care pornesc programul (porneste, ruleaza,
rem login, demo, sterge_sesiunea): mesajul final, pauza ca fereastra să nu se închidă înainte de citire și codul de ieșire.
rem Lansatorul îl cheamă PE ACEEAȘI LINIE cu Python-ul, după el (decis 5 oct. 2026, D13): cmd citește un .bat pe bucăți,
rem după poziție, iar o actualizare înlocuiește lansatorul cât rulează Python; un rând citit după aceea ar veni din fișierul
rem nou, de la o poziție greșită. Acest fișier e deschis abia după oprirea lui Python, deci e citit întreg, din versiunea nouă.
rem Primește: 1) numele lansatorului, fără .bat; 2) codul de ieșire al lui Python. Iese cu exact același cod.
rem La codul de repornire (programul s-a actualizat): pentru porneste nu așteaptă tasta, fiindcă porneste.bat pornește singur
rem varianta nouă; ceilalți lansatori spun să fie pornit din nou. Nu pornește nimic, nu scrie și nu șterge nimic.
rem Contract stabil între versiuni: după o actualizare, un lansator VECHI cheamă acest fișier NOU, deci argumentele rămân aceleași.
rem Fără goto și fără etichete: batch-urile cu diacritice UTF-8 pot da erori la etichete.
setlocal EnableExtensions
set "LANSATOR=%~1"
set "COD=%~2"
rem Fără cod (chemare greșită) nu se poate spune „Gata”: se tratează ca eroare.
if not defined COD set "COD=1"
chcp 65001 >nul
rem Codul cu care programul cere repornirea după o actualizare: settings.EXIT_CODE_RESTART (EX_TEMPFAIL), ales ca să nu se
rem confunde cu erorile programului (0 și 1). Testele verifică să fie aceeași valoare aici, în settings.py și în porneste.bat.
set "COD_REPORNIRE=75"
set "STARE=eroare"
if "%COD%"=="0" set "STARE=gata"
if "%COD%"=="%COD_REPORNIRE%" set "STARE=actualizat"
set "FARA_PAUZA="
if "%STARE%"=="actualizat" if /i "%LANSATOR%"=="porneste" set "FARA_PAUZA=1"

echo.
if "%STARE%"=="actualizat" if defined FARA_PAUZA echo Programul a fost actualizat. Pornesc versiunea nouă; pregătirea poate dura puțin.
if "%STARE%"=="actualizat" if not defined FARA_PAUZA echo Programul a fost actualizat; pornește-l din nou.
if "%STARE%"=="gata" if /i "%LANSATOR%"=="porneste" echo Gata. Rezultatele rămân în folderul iesiri.
if "%STARE%"=="eroare" if /i "%LANSATOR%"=="porneste" echo Programul s-a oprit cu o eroare. Citește mesajul de mai sus; jurnalul complet e în folderul logs.
if "%STARE%"=="gata" if /i "%LANSATOR%"=="ruleaza" echo Gata. Raportul s-a deschis în browser; toate fișierele rulării sunt în folderul iesiri.
if "%STARE%"=="eroare" if /i "%LANSATOR%"=="ruleaza" echo Rularea s-a oprit cu o eroare. Citește mesajul de mai sus; jurnalul complet e în folderul logs.
if "%STARE%"=="gata" if /i "%LANSATOR%"=="login" echo Gata: sesiunea ta eMAG e salvată pe acest calculator, în folderul .profil_browser.
if "%STARE%"=="gata" if /i "%LANSATOR%"=="login" echo Tratează acel folder ca pe o parolă: nu îl trimite nimănui.
if "%STARE%"=="gata" if /i "%LANSATOR%"=="login" echo Pasul următor: ruleaza.bat
if "%STARE%"=="eroare" if /i "%LANSATOR%"=="login" echo Login-ul nu s-a încheiat cu succes. Citește mesajul de mai sus, apoi rulează din nou login.bat.
if "%STARE%"=="gata" if /i "%LANSATOR%"=="demo" echo Gata. Raportul demonstrativ s-a deschis în browser; fișierele lui sunt în folderul iesiri.
if "%STARE%"=="eroare" if /i "%LANSATOR%"=="demo" echo Demonstrația s-a oprit cu o eroare. Citește mesajul de mai sus; jurnalul complet e în folderul logs.
if "%STARE%"=="eroare" if /i "%LANSATOR%"=="sterge_sesiunea" echo Sesiunea nu a fost ștearsă sau comanda s-a oprit cu o eroare. Citește mesajul de mai sus.
echo.
rem Pauza și ieșirea stau pe același rând: dacă altă fereastră a programului face o actualizare cât aceasta așteaptă o tastă,
rem după tastă nu se mai citește nimic din fișierul înlocuit. Codul se completează când e citit rândul, înainte de pauză.
(if not defined FARA_PAUZA pause) & exit /b %COD%

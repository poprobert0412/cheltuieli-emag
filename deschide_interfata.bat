@echo off
rem Deschide interfata/index.html in browserul implicit, cu cale absoluta (merge si pe un share de retea, unde schimbarea folderului curent nu merge).
if not exist "%~dp0interfata\index.html" (
  echo Lipseste interfata\index.html
  pause
  exit /b 1
)
start "" "%~dp0interfata\index.html"

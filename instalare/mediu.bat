@echo off
rem Variabilele de mediu comune lansatoarelor de pe Windows. Se cheamă din folderul programului cu: call ".\instalare\mediu.bat"
rem Țin tot ce descarcă uv și Playwright în folderul programului (.uv\), nu în AppData sau în folderul personal:
rem ștergi folderul programului și nu rămâne nimic de la el (în afara fișierelor temporare pe care Edge le scrie singur).
set "UV_CACHE_DIR=%CD%\.uv\cache"
set "UV_PYTHON_INSTALL_DIR=%CD%\.uv\python"
rem Doar Python-ul adus de uv (aceeași versiune la toți), nu cel din sistem; fără fișierele de configurare uv ale utilizatorului.
set "UV_PYTHON_PREFERENCE=only-managed"
set "UV_NO_CONFIG=1"
set "PLAYWRIGHT_BROWSERS_PATH=%CD%\.uv\browsere"
set "PYTHONUTF8=1"
set "PYTHONDONTWRITEBYTECODE=1"

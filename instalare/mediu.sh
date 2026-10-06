# Variabilele de mediu comune lansatoarelor de pe macOS și Linux. Se încarcă cu „. instalare/mediu.sh”
# după ce lansatorul a pus în ROOT folderul programului; nu se rulează singur.
# Țin tot ce descarcă uv și Playwright în folderul programului (.uv/), nu în folderul personal:
# ștergi folderul programului și nu rămâne nimic de la el.
export UV_CACHE_DIR="$ROOT/.uv/cache"
export UV_PYTHON_INSTALL_DIR="$ROOT/.uv/python"
# Doar Python-ul adus de uv (aceeași versiune la toți), nu cel din sistem; fără fișierele de configurare uv ale utilizatorului.
export UV_PYTHON_PREFERENCE=only-managed
export UV_NO_CONFIG=1
export PLAYWRIGHT_BROWSERS_PATH="$ROOT/.uv/browsere"
export PYTHONUTF8=1
export PYTHONDONTWRITEBYTECODE=1

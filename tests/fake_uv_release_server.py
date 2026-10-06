"""Un github.com fals, local, pentru testele care rulează descărcarea lui uv din instaleaza.bat (decis 6 oct. 2026, N12).

Primește: arhivele de servit, pe calea din adresă (/astral-sh/uv/releases/download/<versiune>/<nume>). Dă: un server HTTPS doar pe
127.0.0.1, cu certificat autosemnat făcut la pornire cu openssl (cel din Git for Windows), și mediul în care curl.exe din Windows
ajunge la el în loc de github.com: un _curlrc în CURL_HOME (connect-to spre server, certificat neverificat, fără proxy doar pentru
github.com). Orice altă cerere merge la un proxy mort (OFFLINE_ENV), deci nimic nu iese pe internet nici dacă _curlrc n-ar fi
citit. Notează fiecare cale cerută. Ce NU face: nu verifică ce face instaleaza.bat cu arhiva (asta fac testele din test_bat_files.py).
"""

import http.server
import shutil
import ssl
import subprocess
import threading
from pathlib import Path

# Proxy-ul pentru orice cerere a lui curl care nu e redirecționată spre serverul fals: portul 9 („discard”) pe 127.0.0.1, unde nu
# ascultă nimic pe un calculator obișnuit, deci conexiunea e refuzată pe loc și cererea nu pleacă pe internet.
DEAD_PROXY = "http://127.0.0.1:9"
# Variabilele de mediu pe care le citește curl pentru proxy; NO_PROXY se golește, ca o valoare a utilizatorului să nu ocolească proxy-ul mort.
OFFLINE_ENV = {"HTTPS_PROXY": DEAD_PROXY, "HTTP_PROXY": DEAD_PROXY, "ALL_PROXY": DEAD_PROXY, "NO_PROXY": ""}
FAKE_HOST = "github.com"
OPENSSL_TIMEOUT_SECONDS = 60
# Unde stă openssl față de git.exe în Git for Windows (Git\cmd\git.exe sau Git\mingw64\bin\git.exe).
GIT_FOLDER_DEPTH = 3
OPENSSL_IN_GIT = ("mingw64/bin/openssl.exe", "usr/bin/openssl.exe")


def find_openssl() -> str | None:
    """openssl din PATH sau, pe Windows, cel din Git for Windows (lângă git.exe); None dacă lipsește."""
    found = shutil.which("openssl")
    if found:
        return found
    git = shutil.which("git")
    if not git:
        return None
    for folder in Path(git).resolve().parents[:GIT_FOLDER_DEPTH]:
        for relative in OPENSSL_IN_GIT:
            if (folder / relative).is_file():
                return str(folder / relative)
    return None


class _Handler(http.server.BaseHTTPRequestHandler):
    """Răspunde la GET cu arhiva înregistrată pentru cale (200) sau 404; notează calea."""

    def do_GET(self) -> None:  # noqa: N802 (numele cerut de http.server)
        """Servește `self.server.responses[path]`, altfel 404 (curl -f pică atunci)."""
        self.server.requests.append(self.path)
        body = self.server.responses.get(self.path)
        self.send_response(200 if body is not None else 404)
        body = body if body is not None else b"nu exista"
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args) -> None:
        """Fără jurnal pe ecran: cererile se văd în `requests`."""


class FakeUvRelease:
    """Serverul HTTPS fals: `serve(cale, octeți)`, `requests` (căile cerute, în ordine), `curl_env(folder)`, `close()`."""

    def __init__(self, work: Path, openssl: str):
        """Face certificatul în `work` și pornește serverul pe 127.0.0.1, port ales de sistem; ridică OSError/CalledProcessError."""
        cert, key = work / "cert.pem", work / "key.pem"
        subprocess.run([openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-keyout", str(key), "-out", str(cert),
                        "-days", "1", "-subj", f"/CN={FAKE_HOST}"], check=True, capture_output=True, timeout=OPENSSL_TIMEOUT_SECONDS)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        self._server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self._server.daemon_threads = True
        self._server.socket = context.wrap_socket(self._server.socket, server_side=True)
        self._server.responses, self._server.requests = {}, []
        self._thread = threading.Thread(target=self._server.serve_forever, name="github-fals", daemon=True)
        self._thread.start()

    @property
    def requests(self) -> list[str]:
        """Căile cerute de la ultimul `reset`, în ordine."""
        return self._server.requests

    def reset(self) -> None:
        """Uită arhivele servite și cererile notate (între teste)."""
        self._server.responses.clear()
        self._server.requests.clear()

    def serve(self, path: str, data: bytes) -> None:
        """La GET pe `path` răspunde cu `data`."""
        self._server.responses[path] = data

    def curl_env(self, folder: Path) -> dict[str, str]:
        """Variabilele de mediu pentru curl: _curlrc în `folder` (github.com → acest server, fără proxy), plus proxy-ul mort pentru rest."""
        folder.mkdir(parents=True, exist_ok=True)
        port = self._server.server_address[1]
        (folder / "_curlrc").write_text(f"connect-to = {FAKE_HOST}:443:127.0.0.1:{port}\ninsecure\nnoproxy = {FAKE_HOST}\n", encoding="ascii")
        return {**OFFLINE_ENV, "CURL_HOME": str(folder)}

    def close(self) -> None:
        """Oprește serverul și firul lui."""
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=OPENSSL_TIMEOUT_SECONDS)

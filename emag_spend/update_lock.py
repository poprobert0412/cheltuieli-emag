"""Lacătul actualizării: împiedică două aplicări (sau o aplicare și o recuperare) simultane în același folder (D10; refăcut 6 oct. 2026, N5).

Primește: calea fișierului-lacăt (.actualizare/lacat). Dă înapoi: un context manager care ține lacătul cât rulează blocul; LockBusyError
dacă îl ține alt proces (după cel mult LOCK_WAIT_SECONDS de așteptare), LockError dacă nu se poate lua deloc (text pentru utilizator).
Cum: fișierul e permanent și gol, deschis fără O_EXCL; lacătul e al sistemului, pe primul lui octet: Windows msvcrt.locking(LK_NBLCK),
macOS/Linux fcntl.flock(LOCK_EX | LOCK_NB). Sistemul îl eliberează singur când procesul moare, deci nu există „lacăt abandonat” și
fișierul nu se șterge niciodată (ștergerea lui ar putea fura lacătul viu al altui proces).
Ce NU face: folosește doar biblioteca standard (recuperarea îl importă înaintea oricărui alt modul al programului, N2) și nu știe ce se aplică.
"""

import errno
import os
import time
from pathlib import Path

if os.name == "nt":
    import msvcrt
    fcntl = None
else:
    import fcntl
    msvcrt = None

# Lacătul de sistem acoperă un singur octet de la începutul fișierului (pe Windows se poate bloca și după sfârșitul unui fișier gol).
LOCKED_BYTES = 1
# Deschis pentru citire-scriere (cerut de lacătul Windows), creat dacă lipsește, niciodată trunchiat; fără urmarea unei legături (Unix).
OPEN_FLAGS = os.O_RDWR | os.O_CREAT | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
LOCK_FILE_MODE = 0o600  # doar proprietarul: fișierul e gol, dar nimeni altcineva n-are de ce să-l citească (CodeQL #8)
# Cât se mai încearcă un lacăt ocupat înainte de „ocupat”: Windows eliberează lacătul unui proces omorât cu o mică întârziere
# („depinde de resursele sistemului”, documentația LockFileEx), iar o recuperare sau o aplicare reală ține sub o secundă.
LOCK_WAIT_SECONDS = 2.0
LOCK_RETRY_SECONDS = 0.1
# Răspunsurile sistemului care înseamnă „îl ține alt proces” (Windows: EACCES sau EDEADLOCK; flock: EWOULDBLOCK, EAGAIN).
BUSY_ERRNOS = frozenset({errno.EACCES, errno.EAGAIN, errno.EWOULDBLOCK, getattr(errno, "EDEADLOCK", errno.EDEADLK)})

MESSAGE_BUSY = "O altă actualizare e în curs (alt program deschis din același folder). Așteaptă să se termine și încearcă din nou."
MESSAGE_CANNOT_CREATE = "Nu pot crea lacătul actualizării ({detail}); n-am schimbat nimic."


class LockError(Exception):
    """Lacătul nu se poate lua; `str(eroare)` e fraza pentru utilizator, în română."""


class LockBusyError(LockError):
    """Lacătul e ținut chiar acum de alt proces (altă fereastră a programului aplică sau recuperează o actualizare)."""


def _describe(error: OSError) -> str:
    """Cauza unei erori de sistem, scurt (fără cale: calea poate conține numele contului)."""
    return error.strerror or type(error).__name__


def _lock(descriptor: int) -> None:
    """O singură încercare, fără așteptare, de a lua lacătul de sistem pe primul octet; OSError dacă e ocupat sau imposibil."""
    if msvcrt is not None:
        os.lseek(descriptor, 0, os.SEEK_SET)
        msvcrt.locking(descriptor, msvcrt.LK_NBLCK, LOCKED_BYTES)
    else:
        fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)


class UpdateLock:
    """Context manager pentru lacăt: `with UpdateLock(cale): ...`; ridică LockBusyError dacă îl ține alt proces."""

    def __init__(self, path: Path):
        """`path` = fișierul lacătului; folderul lui se creează la `acquire`."""
        self.path = Path(path)
        self._descriptor: int | None = None

    def __enter__(self) -> "UpdateLock":
        """Ia lacătul (LockBusyError dacă îl ține alt proces, LockError dacă nu se poate crea)."""
        self.acquire()
        return self

    def __exit__(self, *exc_info) -> None:
        """Eliberează lacătul, oricum s-ar fi terminat blocul."""
        self.release()

    def acquire(self) -> None:
        """Deschide (sau creează) fișierul permanent și ia lacătul de sistem pe el; nu șterge niciodată nimic.

        Un lacăt ocupat se mai încearcă LOCK_WAIT_SECONDS (pași de LOCK_RETRY_SECONDS), apoi LockBusyError.
        """
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            descriptor = os.open(self.path, OPEN_FLAGS, LOCK_FILE_MODE)
        except OSError as error:
            raise LockError(MESSAGE_CANNOT_CREATE.format(detail=_describe(error))) from error
        deadline = time.monotonic() + LOCK_WAIT_SECONDS
        while True:
            try:
                _lock(descriptor)
            except OSError as error:
                if error.errno in BUSY_ERRNOS and time.monotonic() < deadline:
                    time.sleep(LOCK_RETRY_SECONDS)
                    continue
                os.close(descriptor)
                if error.errno in BUSY_ERRNOS:
                    raise LockBusyError(MESSAGE_BUSY) from error
                raise LockError(MESSAGE_CANNOT_CREATE.format(detail=_describe(error))) from error
            self._descriptor = descriptor
            return

    def release(self) -> None:
        """Eliberează lacătul de sistem și închide fișierul; fișierul rămâne pe disc, gol, pentru data viitoare."""
        if self._descriptor is None:
            return
        descriptor, self._descriptor = self._descriptor, None
        try:
            if msvcrt is not None:
                os.lseek(descriptor, 0, os.SEEK_SET)  # msvcrt.locking lucrează de la poziția curentă: aceeași cu cea blocată
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, LOCKED_BYTES)
            else:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        except OSError:
            pass  # închiderea de mai jos eliberează oricum lacătul
        finally:
            os.close(descriptor)

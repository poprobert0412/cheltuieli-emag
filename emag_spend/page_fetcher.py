"""Descarcă pagini eMAG (detalii comenzi, detalii retururi) folosind sesiunea logată.

Primește: contextul de browser logat, o listă de căi, o funcție care transformă (cale, html) într-un rezultat și, opțional, un raportor de progres (progress.py). Dă înapoi lista rezultatelor, în aceeași ordine cu căile.
Cere puține pagini simultan (settings.FETCH_CONCURRENCY), reîncearcă cu pauză la erori de rețea și oprește rularea dacă sesiunea a expirat (redirecționare la login).
HTML-ul nu se păstrează: se parsează pe loc, ca să nu rămână în memorie și ca datele personale din pagină să nu ajungă pe disc.
Oprirea cerută de utilizator se verifică înainte de fiecare descărcare; la prima eroare sau la oprire, descărcările rămase se anulează ca browserul să se poată închide curat."""

import asyncio
import logging
from typing import Callable, TypeVar

from emag_spend import settings
from emag_spend.progress import NO_PROGRESS, Progress

logger = logging.getLogger(__name__)

T = TypeVar("T")
_PROGRESS_EVERY = 25


class SessionExpired(RuntimeError):
    """Sesiunea eMAG a expirat în timpul descărcării."""


async def _fetch_html(context, path: str) -> str:
    """HTML-ul unei pagini, cu reîncercări; ridică SessionExpired la redirect spre login."""
    url = settings.BASE_URL + path
    last_error = "necunoscută"
    for attempt in range(1, settings.FETCH_RETRIES + 1):
        try:
            response = await context.request.get(url, timeout=settings.FETCH_TIMEOUT_MS)
            if "login" in response.url.lower() and "login" not in path.lower():
                raise SessionExpired(f"redirecționat la login pentru {path}")
            if response.status == 200:
                return await response.text()
            last_error = f"HTTP {response.status}"
        except SessionExpired:
            raise
        except Exception as error:  # rețea, timeout
            last_error = str(error)
        logger.warning("%s: încercarea %d/%d a eșuat (%s)", path, attempt, settings.FETCH_RETRIES, last_error)
        await asyncio.sleep(settings.FETCH_BACKOFF_SECONDS * attempt)
    raise RuntimeError(f"nu am putut descărca {path}: {last_error}")


async def fetch_each(context, paths: list[str], handler: Callable[[str, str], T], label: str,
                     progress: Progress = NO_PROGRESS) -> list[T]:
    """Descarcă fiecare cale și aplică `handler(cale, html)`; păstrează ordinea căilor.

    La prima eroare (sau la oprirea cerută, RunCancelled) descărcările rămase se anulează și se așteaptă să se termine:
    altfel ar continua în fundal pe un browser care se închide.
    """
    semaphore = asyncio.Semaphore(settings.FETCH_CONCURRENCY)
    results: list[T | None] = [None] * len(paths)
    done = 0
    progress.advance(0, len(paths))

    async def worker(index: int, path: str) -> None:
        """Descarcă o pagină (după ce un loc din semafor e liber), o parsează pe loc și raportează progresul; oprirea cerută se verifică înainte."""
        nonlocal done
        async with semaphore:
            progress.raise_if_cancelled()
            html = await _fetch_html(context, path)
        results[index] = handler(path, html)
        done += 1
        progress.advance(done, len(paths))
        if done % _PROGRESS_EVERY == 0 or done == len(paths):
            logger.info("%s: %d/%d descărcate", label, done, len(paths))

    tasks = [asyncio.ensure_future(worker(i, p)) for i, p in enumerate(paths)]
    try:
        await asyncio.gather(*tasks)
    except BaseException:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        raise
    return results  # type: ignore[return-value]

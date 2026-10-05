"""Raportarea progresului unei rulări: faza curentă, „făcute din total”, mesaj și cererea de anulare.

Primește: apeluri de la pipeline și de la scrapere (`phase`, `advance`, `message`, `raise_if_cancelled`).
Dă înapoi: nimic. Clasa `Progress` de aici e INACTIVĂ (nu reține nimic, anularea nu e cerută niciodată), deci linia
de comandă se comportă exact ca înainte; aplicația locală pune în locul ei o implementare activă (app_runner.py).
Anularea e cooperantă: codul întreabă `raise_if_cancelled()` în punctele sigure (între descărcări, în așteptarea
login-ului) și primește RunCancelled, ca browserul să se închidă curat prin blocurile `finally` existente.
Ce NU face: nu scrie pe disc, nu afișează nimic, nu știe de HTTP sau de browser.
"""

# Numele fazelor sunt chiar stările din API-ul aplicației (GET /api/state), ca aplicația să nu traducă nimic între ele.
PHASE_WAITING_LOGIN = "waiting_login"
PHASE_FETCHING_ORDERS = "fetching_orders"
PHASE_FETCHING_RETURNS = "fetching_returns"
PHASE_ANALYZING = "analyzing"
PIPELINE_PHASES = (PHASE_WAITING_LOGIN, PHASE_FETCHING_ORDERS, PHASE_FETCHING_RETURNS, PHASE_ANALYZING)


class RunCancelled(Exception):
    """Utilizatorul a cerut oprirea rulării: nu e o eroare, ci o ieșire controlată (browserul se închide, nu rămâne nimic agățat)."""


class Progress:
    """Raportor de progres INACTIV: toate metodele sunt goale; subclasele îl fac activ.

    Un singur obiect circulă prin pipeline, colector și scrapere, ca fiecare să-și anunțe pasul fără să știe cine ascultă.
    """

    def phase(self, name: str, total: int | None = None) -> None:
        """Începe faza `name` (una din PIPELINE_PHASES); `total` e numărul de pași ai fazei, dacă se știe."""

    def advance(self, done: int, total: int | None = None) -> None:
        """Anunță că s-au făcut `done` pași din `total` (None = nu se știe încă) în faza curentă."""

    def message(self, text: str) -> None:
        """Textul (în română) pe care utilizatorul îl vede lângă bara de progres, până la următoarea fază."""

    def cancel_requested(self) -> bool:
        """True dacă utilizatorul a cerut oprirea; implicit niciodată."""
        return False

    def raise_if_cancelled(self) -> None:
        """Ridică RunCancelled dacă oprirea a fost cerută; se cheamă doar în puncte unde oprirea e sigură."""
        if self.cancel_requested():
            raise RunCancelled("rularea a fost oprită la cererea ta")


# Instanța folosită când nimeni nu ascultă (linia de comandă, testele): partajată, fiindcă nu are stare.
NO_PROGRESS = Progress()

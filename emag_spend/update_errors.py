"""Eroarea comună a actualizărilor: verificare, descărcare și aplicare.

Ce conține: UpdateError, a cărei descriere e deja textul pentru utilizator, în română, cu diacritice (interfața și
linia de comandă îl arată ca atare). Ce NU face: nu traduce alte excepții și nu scrie în jurnal; fiecare modul care o
ridică își alege mesajul, iar cauza tehnică rămâne în lanțul excepției (`raise UpdateError(...) from e`).
"""


class UpdateError(Exception):
    """O actualizare care nu se poate face; `str(eroare)` e fraza pentru utilizator, în română."""

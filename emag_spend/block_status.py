"""Clasificarea statusului unui bloc de comandă (livrat / anulat / în curs / ...).

Primește: textul de status afișat de eMAG pentru un vânzător dintr-o comandă.
Dă înapoi: una dintre constantele de mai jos. Un text necunoscut dă UNKNOWN,
niciodată "livrat" din greșeală: calculatorul îl raportează ca avertisment.
Nu citește pagini și nu calculează sume.
"""

from emag_spend.text_normalize import normalize_text

DELIVERED = "DELIVERED"  # livrat sau ridicat (inclusiv livrat electronic)
CANCELLED = "CANCELLED"  # "Livrare anulata" (anulat înainte SAU returnat și marcat anulat)
IN_PROGRESS = "IN_PROGRESS"  # plasat / predat curierului / în drum: încă nelivrat
PAID_ONLY = "PAID_ONLY"  # plătit fără livrare de produse (ex. asigurări)
UNKNOWN = "UNKNOWN"

# Ordinea contează: prima regulă potrivită câștigă. "Livrare anulata" bate
# orice, fiindcă mesajul "Am trimis cererea de anulare..." precede
# confirmarea "Livrare anulata" în același bloc.
_RULES: list[tuple[str, str]] = [
    ("livrare anulata", CANCELLED),
    ("produse ridicate", DELIVERED),
    ("produse livrate", DELIVERED),
    ("plata acceptata", PAID_ONLY),
    ("comanda plasata", IN_PROGRESS),
    ("predate curierului", IN_PROGRESS),
    ("in drum spre", IN_PROGRESS),
    # „Produse ajunse in showroom” (văzut pe un cont real, 5 oct. 2026): au ajuns la punctul de ridicare,
    # dar clientul nu le-a ridicat încă; tot așa orice „ajunse in/la <punct de ridicare>”. După ridicare
    # eMAG afișează „Produse ridicate”, regulă de mai sus.
    ("ajunse in", IN_PROGRESS),
    ("ajunse la", IN_PROGRESS),
    ("in curs de", IN_PROGRESS),
    ("in pregatire", IN_PROGRESS),
    ("pregatit", IN_PROGRESS),
    ("expediat", IN_PROGRESS),
    ("confirmat", IN_PROGRESS),
]


def classify_status(status_text: str) -> str:
    """Clasa blocului după textul de status (vezi constantele din modul)."""
    normalized = normalize_text(status_text)
    for needle, status in _RULES:
        if needle in normalized:
            return status
    return UNKNOWN

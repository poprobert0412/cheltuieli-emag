"""Plasă de siguranță pentru toată suita (decis 6 oct. 2026, N16): niciun test nu pornește din greșeală verificarea versiunii noi.

Ce face: un fixture autouse pune EMAG_UPDATE_CHECK=0 înaintea fiecărui test (monkeypatch îl readuce la final), deci un AppServer
pornit fără job fals sau un subproces al programului (care moștenește mediul) nu cere nimic de la api.github.com. Testele care chiar
au nevoie de verificare o pornesc explicit, în testul lor: monkeypatch.delenv/setenv("EMAG_UPDATE_CHECK", ...) sau enabled=True.
Ce NU face: nu blochează rețeaua (o fac gărzile, cu socket-uri blocate) și nu schimbă nicio altă setare.
"""

import pytest

from emag_spend import settings


@pytest.fixture(autouse=True)
def update_check_off_unless_a_test_turns_it_on(monkeypatch):
    """EMAG_UPDATE_CHECK=0 cât ține testul; un fixture sau un test care are nevoie de verificare îl scoate sau îl schimbă după acesta."""
    monkeypatch.setenv("EMAG_UPDATE_CHECK", settings.UPDATE_CHECK_DISABLED_VALUE)

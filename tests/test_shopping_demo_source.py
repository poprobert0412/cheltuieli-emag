"""Verifică proveniența datelor de demonstrație ale noilor funcții din extensie.

Primește JSON-ul versionat și generatorul comun de comenzi inventate.
Confirmă identitatea exactă; nu citește contul și nu pornește browserul.
Nu testează calculele JavaScript, acoperite de paritate și testele extensiei.
"""

from extensie.scripts.scrie_demo_cumparaturi import DEMO_SOURCE_FILE, expected_demo_source


def test_shopping_demo_source_matches_existing_generator():
    """Build-ul trebuie să primească exact comenzile demo actuale, fără date divergente."""
    assert DEMO_SOURCE_FILE.read_bytes() == expected_demo_source().encode("utf-8")

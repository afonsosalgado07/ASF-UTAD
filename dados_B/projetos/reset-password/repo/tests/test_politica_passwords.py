from auth.politica_passwords import validar


def test_password_forte_e_aceite():
    assert validar("Forte#2026") == []


def test_password_fraca_indica_todas_as_regras():
    assert len(validar("abc")) == 4

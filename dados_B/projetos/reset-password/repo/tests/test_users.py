import pytest

from auth import users


def test_utilizadores_iniciais():
    assert users.existe("ANA@exemplo.pt")
    assert users.verificar_password("ana@exemplo.pt", "Antiga#2025")
    assert not users.verificar_password("ana@exemplo.pt", "errada")


def test_registar_conta_nova():
    users.registar("Joana", "Joana@Exemplo.pt", "Joana#2026")
    assert users.existe("joana@exemplo.pt") and users.verificar_password("joana@exemplo.pt", "Joana#2026")


@pytest.mark.parametrize("email,password,erro", [
    ("ana@exemplo.pt", "Nova#2026", "já existe"),
    ("sem-arroba", "Nova#2026", "e-mail inválido"),
    ("novo@exemplo.pt", "curta", "password fraca"),
])
def test_registo_invalido(email, password, erro):
    with pytest.raises(users.ErroConta, match=erro):
        users.registar("X", email, password)


def test_password_guardada_so_como_hash():
    assert "Antiga#2025" not in str(users.UTILIZADORES)

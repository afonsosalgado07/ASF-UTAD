import pytest

from biblioteca.erros import SocioInexistente


def test_inscricao_atribui_numeros_sequenciais(bib):
    s = bib.socios.inscrever("Rita Sá", "Rita@Escola.pt")
    assert s.numero == 3 and s.email == "rita@escola.pt" and s.ativo


@pytest.mark.parametrize("email", ["", "sem-arroba", "a@b", "a b@c.pt"])
def test_email_invalido_e_recusado(bib, email):
    with pytest.raises(ValueError):
        bib.socios.inscrever("Nome", email)


def test_socio_inexistente(bib):
    with pytest.raises(SocioInexistente):
        bib.socios.obter(99)

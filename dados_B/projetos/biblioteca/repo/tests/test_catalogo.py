import pytest

from biblioteca.erros import LivroInexistente
from biblioteca.modelos import Livro


def test_procurar_por_titulo_ou_autor(bib):
    assert [l.isbn for l in bib.catalogo.procurar("maias")] == ["111"]
    assert [l.isbn for l in bib.catalogo.procurar("PESSOA")] == ["222"]
    assert bib.catalogo.procurar("inexistente") == []


def test_adicionar_isbn_repetido_soma_exemplares(bib):
    bib.catalogo.adicionar(Livro("111", "Os Maias", "Eça de Queirós", 1888, 3))
    assert bib.catalogo.obter("111").exemplares == 5


def test_livro_sem_exemplares_e_recusado(bib):
    with pytest.raises(ValueError):
        bib.catalogo.adicionar(Livro("999", "X", "Y", 2000, 0))


def test_obter_livro_inexistente(bib):
    with pytest.raises(LivroInexistente):
        bib.catalogo.obter("000")

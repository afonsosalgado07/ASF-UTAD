from datetime import date

import pytest

from biblioteca import Biblioteca, notificacoes
from biblioteca.modelos import Livro

HOJE = date(2026, 3, 2)


@pytest.fixture
def bib():
    notificacoes.limpar()
    b = Biblioteca()
    b.catalogo.adicionar(Livro("111", "Os Maias", "Eça de Queirós", 1888, 2))
    b.catalogo.adicionar(Livro("222", "Mensagem", "Fernando Pessoa", 1934, 1))
    b.catalogo.adicionar(Livro("333", "A Sibila", "Agustina Bessa-Luís", 1954, 1))
    b.catalogo.adicionar(Livro("444", "Memorial do Convento", "José Saramago", 1982, 1))
    b.socios.inscrever("Joana Ribeiro", "joana@escola.pt")      # n.º 1
    b.socios.inscrever("Tiago Moreira", "tiago@escola.pt")      # n.º 2
    return b

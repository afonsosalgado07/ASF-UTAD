"""Catálogo de livros."""
from __future__ import annotations

from .erros import LivroInexistente
from .modelos import Livro


class Catalogo:
    def __init__(self) -> None:
        self._livros: dict[str, Livro] = {}

    def adicionar(self, livro: Livro) -> None:
        if livro.exemplares < 1:
            raise ValueError("um livro tem de ter pelo menos 1 exemplar")
        if livro.isbn in self._livros:
            self._livros[livro.isbn].exemplares += livro.exemplares
        else:
            self._livros[livro.isbn] = livro

    def obter(self, isbn: str) -> Livro:
        try:
            return self._livros[isbn]
        except KeyError:
            raise LivroInexistente(f"não existe livro com ISBN {isbn}") from None

    def procurar(self, texto: str) -> list[Livro]:
        """Procura por título ou autor (sem distinguir maiúsculas)."""
        t = texto.strip().lower()
        return sorted((l for l in self._livros.values() if t in l.titulo.lower() or t in l.autor.lower()),
                      key=lambda l: l.titulo)

    def todos(self) -> list[Livro]:
        return sorted(self._livros.values(), key=lambda l: l.titulo)

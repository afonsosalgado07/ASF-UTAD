"""Empréstimos e devoluções."""
from __future__ import annotations

from datetime import date, timedelta

from . import notificacoes
from .catalogo import Catalogo
from .erros import (EmprestimoInexistente, EmprestimoJaDevolvido, LimiteEmprestimos,
                    LivroIndisponivel, SocioInativo)
from .modelos import Emprestimo
from .socios import RegistoSocios

PRAZO_DIAS = 14
MAX_EMPRESTIMOS = 3


class ServicoEmprestimos:
    def __init__(self, catalogo: Catalogo, socios: RegistoSocios) -> None:
        self.catalogo = catalogo
        self.socios = socios
        self._emprestimos: dict[int, Emprestimo] = {}
        self._proximo = 1

    # ------------------------------------------------------------ consultas
    def obter(self, id_emprestimo: int) -> Emprestimo:
        try:
            return self._emprestimos[id_emprestimo]
        except KeyError:
            raise EmprestimoInexistente(f"não existe o empréstimo n.º {id_emprestimo}") from None

    def ativos(self) -> list[Emprestimo]:
        return [e for e in self._emprestimos.values() if e.ativo]

    def ativos_do_socio(self, numero_socio: int) -> list[Emprestimo]:
        return [e for e in self.ativos() if e.numero_socio == numero_socio]

    def exemplares_livres(self, isbn: str) -> int:
        livro = self.catalogo.obter(isbn)
        return livro.exemplares - sum(1 for e in self.ativos() if e.isbn == isbn)

    def atrasados(self, hoje: date | None = None) -> list[Emprestimo]:
        hoje = hoje or date.today()
        return [e for e in self.ativos() if e.dias_atraso(hoje) > 0]

    def todos(self) -> list[Emprestimo]:
        return sorted(self._emprestimos.values(), key=lambda e: e.id)

    # ------------------------------------------------------------ operações
    def emprestar(self, isbn: str, numero_socio: int, hoje: date | None = None) -> Emprestimo:
        hoje = hoje or date.today()
        socio = self.socios.obter(numero_socio)
        if not socio.ativo:
            raise SocioInativo(f"o sócio n.º {numero_socio} está inativo")
        if len(self.ativos_do_socio(numero_socio)) >= MAX_EMPRESTIMOS:
            raise LimiteEmprestimos(f"o sócio já tem {MAX_EMPRESTIMOS} empréstimos ativos")
        if self.exemplares_livres(isbn) <= 0:
            raise LivroIndisponivel(f"não há exemplares livres de {isbn}")
        e = Emprestimo(self._proximo, isbn, numero_socio, hoje, hoje + timedelta(days=PRAZO_DIAS))
        self._emprestimos[e.id] = e
        self._proximo += 1
        livro = self.catalogo.obter(isbn)
        notificacoes.enviar_email(socio.email, "Empréstimo registado",
                                  f"Requisitou «{livro.titulo}». Devolva até {e.data_limite.isoformat()}.")
        return e

    def devolver(self, id_emprestimo: int, hoje: date | None = None) -> Emprestimo:
        hoje = hoje or date.today()
        e = self.obter(id_emprestimo)
        if not e.ativo:
            raise EmprestimoJaDevolvido(f"o empréstimo n.º {id_emprestimo} já foi devolvido")
        e.data_devolucao = hoje
        return e

    def _restaurar(self, e: Emprestimo) -> None:
        self._emprestimos[e.id] = e
        self._proximo = max(self._proximo, e.id + 1)

"""Registo de sócios."""
from __future__ import annotations

import re

from .erros import SocioInexistente
from .modelos import Socio

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class RegistoSocios:
    def __init__(self) -> None:
        self._socios: dict[int, Socio] = {}
        self._proximo = 1

    def inscrever(self, nome: str, email: str) -> Socio:
        if not nome.strip():
            raise ValueError("o nome é obrigatório")
        if not _EMAIL.match(email):
            raise ValueError(f"e-mail inválido: {email}")
        s = Socio(self._proximo, nome.strip(), email.strip().lower())
        self._socios[s.numero] = s
        self._proximo += 1
        return s

    def obter(self, numero: int) -> Socio:
        try:
            return self._socios[numero]
        except KeyError:
            raise SocioInexistente(f"não existe o sócio n.º {numero}") from None

    def desativar(self, numero: int) -> None:
        self.obter(numero).ativo = False

    def todos(self) -> list[Socio]:
        return sorted(self._socios.values(), key=lambda s: s.numero)

    def _restaurar(self, socio: Socio) -> None:
        self._socios[socio.numero] = socio
        self._proximo = max(self._proximo, socio.numero + 1)

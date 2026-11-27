"""Biblioteca — gestão de catálogo, sócios e empréstimos de uma biblioteca escolar."""
from .catalogo import Catalogo
from .emprestimos import ServicoEmprestimos
from .socios import RegistoSocios


class Biblioteca:
    """Agrega os três serviços. É o ponto de entrada usado pela linha de comandos."""

    def __init__(self) -> None:
        self.catalogo = Catalogo()
        self.socios = RegistoSocios()
        self.emprestimos = ServicoEmprestimos(self.catalogo, self.socios)


__all__ = ["Biblioteca", "Catalogo", "RegistoSocios", "ServicoEmprestimos"]

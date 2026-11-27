"""Erros de negócio da biblioteca."""


class ErroBiblioteca(Exception):
    """Base de todos os erros de negócio."""


class LivroInexistente(ErroBiblioteca):
    pass


class LivroIndisponivel(ErroBiblioteca):
    """Não há exemplares livres para emprestar."""


class SocioInexistente(ErroBiblioteca):
    pass


class SocioInativo(ErroBiblioteca):
    pass


class LimiteEmprestimos(ErroBiblioteca):
    """O sócio já tem o número máximo de empréstimos ativos."""


class EmprestimoInexistente(ErroBiblioteca):
    pass


class EmprestimoJaDevolvido(ErroBiblioteca):
    pass


class SocioComMultas(ErroBiblioteca):
    """O sócio tem multas por pagar acima do limite."""

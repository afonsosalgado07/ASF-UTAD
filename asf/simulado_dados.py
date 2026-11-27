"""Respostas pré-escritas do LLM SIMULADO para o pedido de demonstração
(projeto "biblioteca", Issue #12 — multas por atraso).

O LLM simulado não escreve código a sério: para este pedido devolve o código
e os testes abaixo; para qualquer outro pedido responde que não sabe (o
fluxo pára e pede intervenção humana). Com o LLM real (iaedu) isto não é usado.
"""

CONTRATO_MULTAS = """Novo módulo biblioteca/multas.py:
- VALOR_DIA_CENTIMOS = 50
- MULTA_MAXIMA_CENTIMOS = 1000
- LIMITE_BLOQUEIO_CENTIMOS = 500
- calcular_multa(dias_atraso: int) -> int          # em cêntimos, com o teto aplicado
Em biblioteca/erros.py: nova exceção SocioComMultas(ErroBiblioteca).
Em ServicoEmprestimos (biblioteca/emprestimos.py), mantendo a interface atual:
- devolver(id_emprestimo, hoje=None): se houver atraso, regista a multa do sócio e envia-lhe
  um e-mail (notificacoes.enviar_email) cujo corpo contém o valor no formato "1,50 €";
- multas_por_pagar(numero_socio: int) -> int        # total em cêntimos
- pagar_multas(numero_socio: int) -> int            # devolve o valor pago e deixa a dívida a 0
- emprestar(...) lança SocioComMultas se multas_por_pagar(socio) > LIMITE_BLOQUEIO_CENTIMOS."""

MULTAS_PY = '''"""Cálculo de multas por atraso (Issue #12). Valores em cêntimos."""

VALOR_DIA_CENTIMOS = 50
MULTA_MAXIMA_CENTIMOS = 1000
LIMITE_BLOQUEIO_CENTIMOS = 500


def calcular_multa(dias_atraso: int) -> int:
    if dias_atraso <= 0:
        return 0
    return min(dias_atraso * VALOR_DIA_CENTIMOS, MULTA_MAXIMA_CENTIMOS)


def formatar_euros(centimos: int) -> str:
    return f"{centimos // 100},{centimos % 100:02d} €"
'''

ERROS_EXTRA = '''

class SocioComMultas(ErroBiblioteca):
    """O sócio tem multas por pagar acima do limite."""
'''

EMPRESTIMOS_PY = '''"""Empréstimos e devoluções."""
from __future__ import annotations

from datetime import date, timedelta

from . import notificacoes
from .catalogo import Catalogo
from .erros import (EmprestimoInexistente, EmprestimoJaDevolvido, LimiteEmprestimos,
                    LivroIndisponivel, SocioComMultas, SocioInativo)
from .modelos import Emprestimo
from .multas import LIMITE_BLOQUEIO_CENTIMOS, calcular_multa, formatar_euros
from .socios import RegistoSocios

PRAZO_DIAS = 14
MAX_EMPRESTIMOS = 3


class ServicoEmprestimos:
    def __init__(self, catalogo: Catalogo, socios: RegistoSocios) -> None:
        self.catalogo = catalogo
        self.socios = socios
        self._emprestimos: dict[int, Emprestimo] = {}
        self._proximo = 1
        self._multas: dict[int, int] = {}          # n.º sócio -> cêntimos por pagar

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

    def multas_por_pagar(self, numero_socio: int) -> int:
        return self._multas.get(numero_socio, 0)

    # ------------------------------------------------------------ operações
    def emprestar(self, isbn: str, numero_socio: int, hoje: date | None = None) -> Emprestimo:
        hoje = hoje or date.today()
        socio = self.socios.obter(numero_socio)
        if not socio.ativo:
            raise SocioInativo(f"o sócio n.º {numero_socio} está inativo")
        if self.multas_por_pagar(numero_socio) > LIMITE_BLOQUEIO_CENTIMOS:
            raise SocioComMultas(f"o sócio n.º {numero_socio} tem multas por pagar acima do limite")
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
        multa = calcular_multa(e.dias_atraso(hoje))
        if multa:
            self._multas[e.numero_socio] = self.multas_por_pagar(e.numero_socio) + multa
            socio = self.socios.obter(e.numero_socio)
            notificacoes.enviar_email(socio.email, "Multa por atraso",
                                      f"A devolução do empréstimo n.º {e.id} teve {e.dias_atraso(hoje)} dia(s) "
                                      f"de atraso. Multa: {formatar_euros(multa)}.")
        return e

    def pagar_multas(self, numero_socio: int) -> int:
        return self._multas.pop(numero_socio, 0)

    def _restaurar(self, e: Emprestimo) -> None:
        self._emprestimos[e.id] = e
        self._proximo = max(self._proximo, e.id + 1)
'''

# --------------------------------------------------------------------------
# Testes de aceitação que o AG5 "simulado" escreve, um por requisito.
# Escolhidos por palavras do requisito; os ids reais (R1, R2…) são inseridos.
# --------------------------------------------------------------------------
CABECALHO_TESTES = '''"""Testes de aceitação gerados pelo AG5 a partir dos requisitos aprovados (Issue #12)."""
from datetime import timedelta

import pytest

from biblioteca import notificacoes
from biblioteca.emprestimos import PRAZO_DIAS
from conftest import HOJE


def _devolver_com_atraso(bib, dias, socio=1, isbn="111"):
    e = bib.emprestimos.emprestar(isbn, socio, hoje=HOJE)
    bib.emprestimos.devolver(e.id, hoje=HOJE + timedelta(days=PRAZO_DIAS + dias))
    return e
'''

TESTES_MULTAS = [
    (("0,50", "dia de atraso", "por dia"), '''
def test_{rid}_cada_dia_de_atraso_custa_50_centimos(bib):
    _devolver_com_atraso(bib, 3)
    assert bib.emprestimos.multas_por_pagar(1) == 150
'''),
    (("ultrapassar", "máxim", "10 €"), '''
def test_{rid}_multa_tem_teto_de_10_euros(bib):
    _devolver_com_atraso(bib, 60)
    assert bib.emprestimos.multas_por_pagar(1) == 1000
'''),
    (("dentro do prazo",), '''
def test_{rid}_devolucao_no_prazo_sem_multa(bib):
    _devolver_com_atraso(bib, 0)
    assert bib.emprestimos.multas_por_pagar(1) == 0
'''),
    (("5 €", "requisitar"), '''
def test_{rid}_socio_com_mais_de_5_euros_nao_requisita(bib):
    from biblioteca.erros import SocioComMultas
    _devolver_com_atraso(bib, 11)                      # 5,50 €
    with pytest.raises(SocioComMultas):
        bib.emprestimos.emprestar("222", 1, hoje=HOJE + timedelta(days=30))
    bib.emprestimos.pagar_multas(1)
    bib.emprestimos.emprestar("222", 1, hoje=HOJE + timedelta(days=30))


def test_{rid}_socio_com_5_euros_ainda_requisita(bib):
    _devolver_com_atraso(bib, 10)                      # 5,00 € (não está acima)
    bib.emprestimos.emprestar("222", 1, hoje=HOJE + timedelta(days=30))
'''),
    (("e-mail", "email"), '''
def test_{rid}_socio_recebe_email_com_valor(bib):
    notificacoes.limpar()
    _devolver_com_atraso(bib, 2)
    ultimo = notificacoes.CAIXA_SAIDA[-1]
    assert ultimo["destino"] == "joana@escola.pt"
    assert "1,00 €" in ultimo["corpo"]
'''),
    (("multa",), '''
def test_{rid}_devolucao_atrasada_gera_multa(bib):
    _devolver_com_atraso(bib, 1)
    assert bib.emprestimos.multas_por_pagar(1) > 0
'''),
]


# --------------------------------------------------------------------------
# Pedido de demonstração do protocolo: projeto "reset password" (pacote auth),
# Issue #184. Código e testes iguais aos do protótipo de um só projeto.
# --------------------------------------------------------------------------
CONTRATO_RESET = """Novo ficheiro auth/password_reset.py com:
- VALIDADE_MINUTOS: int
- REGISTO_TENTATIVAS: list[dict]   (todas as tentativas, com 'momento')
- pedir_reposicao(email: str, agora: datetime | None = None) -> str
    devolve SEMPRE a mesma mensagem pública; se o e-mail existir envia, via
    auth.email_service.enviar_email(destino, assunto, corpo), um link com 'token=<TOKEN>'
- confirmar_reposicao(token: str, nova_password: str, agora: datetime | None = None) -> bool
    True e altera a password (auth.users.definir_password) só se o token for válido,
    não usado e não expirado.
O endpoint legado (auth/reset_password.py) não é removido."""

CODIGO_RESET = '''"""Reposição de palavra-passe por e-mail (Issue #184)."""
import hashlib
import secrets
from datetime import datetime, timedelta

from auth import users
from auth.email_service import enviar_email

VALIDADE_MINUTOS = 30
MENSAGEM_PUBLICA = "Se o e-mail estiver registado, receberá instruções para repor a palavra-passe."

REGISTO_TENTATIVAS: list[dict] = []
_TOKENS: dict[str, dict] = {}   # hash do token -> {email, expira, usado}


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def pedir_reposicao(email: str, agora: datetime | None = None) -> str:
    agora = agora or datetime.now()
    registado = users.existe(email)
    REGISTO_TENTATIVAS.append({"momento": agora.isoformat(), "tipo": "pedido",
                               "email_hash": _hash(email.strip().lower()), "registado": registado})
    if registado:
        token = secrets.token_urlsafe(24)
        _TOKENS[_hash(token)] = {"email": email.strip().lower(),
                                 "expira": agora + timedelta(minutes=VALIDADE_MINUTOS), "usado": False}
        enviar_email(email, "Reposição de palavra-passe",
                     f"Use este link (válido {VALIDADE_MINUTOS} min): https://app.exemplo.pt/reset?token={token}")
    return MENSAGEM_PUBLICA


def confirmar_reposicao(token: str, nova_password: str, agora: datetime | None = None) -> bool:
    agora = agora or datetime.now()
    dados = _TOKENS.get(_hash(token))
    valido = bool(dados) and not dados["usado"] and agora <= dados["expira"]
    REGISTO_TENTATIVAS.append({"momento": agora.isoformat(), "tipo": "confirmacao", "sucesso": valido})
    if not valido:
        return False
    users.definir_password(dados["email"], nova_password)
    dados["usado"] = True
    return True
'''

CABECALHO_TESTES_RESET = '''import importlib
import re
from datetime import datetime, timedelta

import pytest

from auth import email_service, users


@pytest.fixture(autouse=True)
def pr():
    importlib.reload(users)
    importlib.reload(email_service)
    import auth.password_reset as modulo
    return importlib.reload(modulo)


def _token():
    m = re.search(r"token=([A-Za-z0-9_\\-]+)", email_service.CAIXA_SAIDA[-1]["corpo"])
    assert m, "o e-mail enviado não contém token"
    return m.group(1)


T0 = datetime(2026, 1, 1, 12, 0)
'''

TESTES_RESET = [
    (('expir',), '''
def test_{rid}_link_expira(pr):
    pr.pedir_reposicao("ana@exemplo.pt", agora=T0)
    depois = T0 + timedelta(minutes=pr.VALIDADE_MINUTOS + 1)
    assert pr.confirmar_reposicao(_token(), "Nova#2026", agora=depois) is False
    assert not users.verificar_password("ana@exemplo.pt", "Nova#2026")
'''),
    (('descobrir', 'está registado'), '''
def test_{rid}_resposta_nao_revela_registo(pr):
    a = pr.pedir_reposicao("ana@exemplo.pt", agora=T0)
    b = pr.pedir_reposicao("ninguem@exemplo.pt", agora=T0)
    assert a == b
    assert all(m["destino"] != "ninguem@exemplo.pt" for m in email_service.CAIXA_SAIDA)
'''),
    (('tentativa',), '''
def test_{rid}_tentativas_registadas(pr):
    pr.pedir_reposicao("ana@exemplo.pt", agora=T0)
    pr.pedir_reposicao("ninguem@exemplo.pt", agora=T0)
    pr.confirmar_reposicao("token-invalido", "x", agora=T0)
    assert len(pr.REGISTO_TENTATIVAS) >= 3
'''),
    (('palavra-passe', 'recuperar', 'reposi'), '''
def test_{rid}_reposicao_dentro_do_prazo(pr):
    pr.pedir_reposicao("ana@exemplo.pt", agora=T0)
    assert pr.confirmar_reposicao(_token(), "Nova#2026", agora=T0 + timedelta(minutes=5)) is True
    assert users.verificar_password("ana@exemplo.pt", "Nova#2026")
'''),
]

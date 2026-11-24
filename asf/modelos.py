"""Entidades do domínio: Pedido e PedidoAprovacao.

As transições de estado permitidas estão numa tabela explícita, para
corresponderem 1:1 ao Diagrama de Estados do Pedido. Uma transição que não
esteja na tabela lança TransicaoInvalida.

Os resultados dos agentes (requisitos, plano, impacto, proposta, testes,
risco) são guardados como artefactos JSON no Store e não como atributos
destas classes: assim cada passagem entre agentes fica num ficheiro próprio.
"""
from __future__ import annotations

import datetime as _dt
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum, IntEnum


def agora() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def novo_id(prefixo: str) -> str:
    return f"{prefixo}-{uuid.uuid4().hex[:6].upper()}"


class Confianca(IntEnum):
    """Níveis de confiança (Anexo A.13)."""
    T0 = 0  # conteúdo não confiável
    T1 = 1  # dados internos verificáveis (código, documentação, outputs)
    T2 = 2  # pedido autenticado
    T3 = 3  # autoridade do sistema (políticas, decisões humanas)


class TransicaoInvalida(Exception):
    pass


# --------------------------------------------------------------------------
# Pedido
# --------------------------------------------------------------------------
class EstadoPedido(str, Enum):
    RECEBIDO = "Recebido"
    EM_ANALISE = "Em análise de requisitos"
    AGUARDA_CLARIFICACAO = "Aguarda clarificação"
    AGUARDA_VALIDACAO_REQUISITOS = "Aguarda validação de requisitos"
    EM_PLANEAMENTO = "Em planeamento"
    EM_ANALISE_IMPACTO = "Em análise de impacto"
    EM_DESENVOLVIMENTO = "Em desenvolvimento"
    EM_TESTES = "Em testes"
    EM_REVISAO_SEGURANCA = "Em revisão de segurança"
    AGUARDA_APROVACAO = "Aguarda aprovação"
    AGUARDA_INTERVENCAO = "Aguarda intervenção humana"
    CONCLUIDO = "Concluído (integrado)"
    REJEITADO = "Rejeitado"
    INTERROMPIDO = "Interrompido"


P = EstadoPedido
TRANSICOES = {
    P.RECEBIDO: {P.EM_ANALISE},
    P.EM_ANALISE: {P.AGUARDA_CLARIFICACAO, P.AGUARDA_VALIDACAO_REQUISITOS, P.AGUARDA_INTERVENCAO},
    P.AGUARDA_CLARIFICACAO: {P.EM_ANALISE, P.INTERROMPIDO},
    P.AGUARDA_VALIDACAO_REQUISITOS: {P.EM_PLANEAMENTO, P.EM_ANALISE, P.REJEITADO},
    P.EM_PLANEAMENTO: {P.EM_ANALISE_IMPACTO},
    P.EM_ANALISE_IMPACTO: {P.EM_DESENVOLVIMENTO, P.AGUARDA_INTERVENCAO},
    P.EM_DESENVOLVIMENTO: {P.EM_TESTES, P.AGUARDA_INTERVENCAO},
    P.EM_TESTES: {P.EM_REVISAO_SEGURANCA, P.EM_DESENVOLVIMENTO, P.AGUARDA_INTERVENCAO},
    P.EM_REVISAO_SEGURANCA: {P.AGUARDA_APROVACAO, P.EM_DESENVOLVIMENTO, P.AGUARDA_INTERVENCAO},
    P.AGUARDA_APROVACAO: {P.CONCLUIDO, P.REJEITADO, P.EM_DESENVOLVIMENTO},
    P.AGUARDA_INTERVENCAO: {P.EM_ANALISE, P.EM_ANALISE_IMPACTO, P.EM_DESENVOLVIMENTO,
                            P.EM_TESTES, P.EM_REVISAO_SEGURANCA, P.INTERROMPIDO},
    P.CONCLUIDO: set(),
    P.REJEITADO: set(),
    P.INTERROMPIDO: set(),
}
ESTADOS_FINAIS = {P.CONCLUIDO, P.REJEITADO, P.INTERROMPIDO}
ESTADOS_EM_ESPERA = {P.AGUARDA_CLARIFICACAO, P.AGUARDA_VALIDACAO_REQUISITOS,
                     P.AGUARDA_APROVACAO, P.AGUARDA_INTERVENCAO}


@dataclass
class Pedido:
    id: str
    titulo: str
    descricao: str
    criterios: list[str]
    autor: str
    fonte_id: str                     # ex.: "issue:184" -> classificada pelo COMP1
    prioridade: str = "Must"
    estado: str = P.RECEBIDO.value
    iteracao: int = 0                 # n.º da proposta atual (proposta_vN)
    iteracoes_ciclo: int = 0          # iterações desde a última decisão humana (RNF10: máx. 3)
    retomar_em: str = ""              # estado para onde voltar após intervenção humana
    cenario: dict = field(default_factory=dict)   # opções de demonstração (ex.: falha SMTP)
    historico: list = field(default_factory=list) # [momento, de, para, motivo]
    criado_em: str = field(default_factory=agora)

    @property
    def estado_enum(self) -> EstadoPedido:
        return EstadoPedido(self.estado)

    def transitar(self, novo: EstadoPedido, motivo: str = "") -> None:
        atual = self.estado_enum
        if novo not in TRANSICOES[atual]:
            raise TransicaoInvalida(f"{self.id}: {atual.value} -> {novo.value} não permitida")
        self.historico.append([agora(), atual.value, novo.value, motivo])
        self.estado = novo.value

    def texto(self) -> str:
        crit = "\n".join(f"- {c}" for c in self.criterios)
        return f"{self.titulo}\n\n{self.descricao}\n\nCritérios preliminares:\n{crit}"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Pedido":
        return cls(**d)


# --------------------------------------------------------------------------
# Proposta de alteração (guardada como artefacto proposta_vN.json).
# Segunda entidade com ciclo de vida -> segundo Diagrama de Estados.
# --------------------------------------------------------------------------
TRANSICOES_PROPOSTA = {
    "Rascunho": {"Em testes"},
    "Em testes": {"Testes falhados", "Em revisão de segurança"},
    "Testes falhados": {"Substituída"},
    "Em revisão de segurança": {"Aguarda aprovação", "Bloqueada pela revisão"},
    "Bloqueada pela revisão": {"Substituída"},
    "Aguarda aprovação": {"Integrada", "Rejeitada", "Substituída"},
    "Integrada": set(),
    "Rejeitada": set(),
    "Substituída": set(),
}


def transitar_proposta(proposta: dict, novo: str, motivo: str = "") -> None:
    atual = proposta["estado"]
    if novo not in TRANSICOES_PROPOSTA[atual]:
        raise TransicaoInvalida(f"Proposta v{proposta['versao']}: {atual} -> {novo} não permitida")
    proposta.setdefault("historico", []).append([agora(), atual, novo, motivo])
    proposta["estado"] = novo


# --------------------------------------------------------------------------
# Pedido de aprovação humana (criado pela TL11, decidido só por humanos)
# --------------------------------------------------------------------------
class TipoAprovacao(str, Enum):
    CLARIFICACAO = "CLARIFICACAO"              # Autor responde a perguntas (UC3)
    VALIDAR_REQUISITOS = "VALIDAR_REQUISITOS"  # HA1 - Revisor valida requisitos do AG2
    INTEGRAR_PROPOSTA = "INTEGRAR_PROPOSTA"    # HA2 - Nível 2: integração no repositório principal
    INTERVENCAO = "INTERVENCAO"                # Falhas esgotadas / limite de iterações


# Opções de decisão por tipo e papel humano autorizado a decidir
OPCOES = {
    TipoAprovacao.CLARIFICACAO: ["responder", "cancelar"],
    TipoAprovacao.VALIDAR_REQUISITOS: ["aprovar", "pedir_revisao", "rejeitar"],
    TipoAprovacao.INTEGRAR_PROPOSTA: ["aprovar", "pedir_correcoes", "rejeitar"],
    TipoAprovacao.INTERVENCAO: ["retomar", "interromper"],
}
PAPEL_DECISOR = {
    TipoAprovacao.CLARIFICACAO: "autor",
    TipoAprovacao.VALIDAR_REQUISITOS: "revisor",
    TipoAprovacao.INTEGRAR_PROPOSTA: "revisor",
    TipoAprovacao.INTERVENCAO: "revisor",
}


@dataclass
class PedidoAprovacao:
    id: str
    pedido_id: str
    tipo: str
    nivel: int
    resumo: str
    detalhe: str
    solicitado_por: str
    estado: str = "pendente"          # pendente -> decidido
    criado_em: str = field(default_factory=agora)
    decisao: str = ""
    decidido_por: str = ""
    decidido_em: str = ""
    comentario: str = ""

    @property
    def opcoes(self) -> list[str]:
        return OPCOES[TipoAprovacao(self.tipo)]

    @property
    def papel_decisor(self) -> str:
        return PAPEL_DECISOR[TipoAprovacao(self.tipo)]

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "PedidoAprovacao":
        return cls(**d)

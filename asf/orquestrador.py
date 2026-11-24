"""AG1 — Orquestrador.

Conduz a máquina de estados do Pedido. Em cada estado chama o agente
responsável, guarda o artefacto produzido no Store e decide a transição.
Quando é precisa uma decisão humana, cria o pedido de aprovação (TL11),
muda o estado para "Aguarda ..." e SAI. Nada fica bloqueado à espera:
quando o humano decide, o fluxo é retomado a partir do estado gravado.

O AG1 não usa LLM: as decisões de controlo (transições, limites, aprovação)
são determinísticas e auditáveis.
"""
from __future__ import annotations

import json

from .agentes import (AgenteArquitetura, AgenteDesenvolvimento, AgenteRequisitos,
                      AgenteSeguranca, AgenteTestes)
from .comp1 import FalhaFerramenta, FerramentaBloqueada
from .llm import FalhaLLM
from .modelos import ESTADOS_EM_ESPERA, ESTADOS_FINAIS, EstadoPedido as E, Pedido, transitar_proposta

INTERFACE = """Interface esperada (contrato para AG4 e AG5):
Ficheiro auth/password_reset.py com:
- VALIDADE_MINUTOS: int
- REGISTO_TENTATIVAS: list[dict]   (todas as tentativas, com 'momento')
- pedir_reposicao(email: str, agora: datetime | None = None) -> str
    devolve SEMPRE a mesma mensagem pública; se o e-mail existir envia, via
    auth.email_service.enviar_email(destino, assunto, corpo), um link com 'token=<TOKEN>'
- confirmar_reposicao(token: str, nova_password: str, agora: datetime | None = None) -> bool
    True e altera a password (auth.users.definir_password) só se o token for válido,
    não usado e não expirado."""


class Orquestrador:
    id = "AG1"

    def __init__(self, store, comp1, auditoria, llm, limites):
        self.store, self.comp1, self.audit, self.limites = store, comp1, auditoria, limites
        args = (comp1, llm, auditoria, limites)
        self.ag2, self.ag3, self.ag4 = AgenteRequisitos(*args), AgenteArquitetura(*args), AgenteDesenvolvimento(*args)
        self.ag5, self.ag6 = AgenteTestes(*args), AgenteSeguranca(*args)
        self.passos = {
            E.RECEBIDO: self._recebido,
            E.EM_ANALISE: self._analisar,
            E.EM_PLANEAMENTO: self._planear,
            E.EM_ANALISE_IMPACTO: self._impacto,
            E.EM_DESENVOLVIMENTO: self._desenvolver,
            E.EM_TESTES: self._testar,
            E.EM_REVISAO_SEGURANCA: self._rever,
        }

    # ------------------------------------------------------------ ciclo
    def avancar(self, pedido_id: str) -> None:
        """Executa passos até chegar a um estado de espera ou final."""
        while True:
            p = self.store.obter_pedido(pedido_id)
            if p.estado_enum in ESTADOS_FINAIS or p.estado_enum in ESTADOS_EM_ESPERA:
                return
            try:
                self.passos[p.estado_enum](p)
            except (FalhaFerramenta, FalhaLLM) as e:
                self._intervencao(p, f"falha após tentativas limitadas: {e}")
            except Exception as e:  # erro inesperado: nunca continuar às cegas
                self._intervencao(p, f"erro inesperado ({type(e).__name__}): {e}")

    def _mudar(self, p: Pedido, novo: E, motivo: str = "") -> None:
        anterior = p.estado
        p.transitar(novo, motivo)
        self.store.guardar_pedido(p)
        self.audit.registar(p.id, "transicao_estado", "AG1", f"{anterior} -> {novo.value}"
                            + (f" ({motivo})" if motivo else ""))

    def _aprovacao(self, p: Pedido, tipo: str, resumo: str, detalhe: str, notificar: str) -> None:
        self.comp1.chamar("AG1", "TL11", p.id, pedido_id=p.id, tipo=tipo, resumo=resumo, detalhe=detalhe)
        self.comp1.chamar("AG1", "TL12", p.id, pedido_id=p.id, destinatario=notificar, mensagem=resumo)

    def _intervencao(self, p: Pedido, motivo: str) -> None:
        p = self.store.obter_pedido(p.id)
        p.retomar_em = p.estado
        self._mudar(p, E.AGUARDA_INTERVENCAO, motivo)
        self._aprovacao(p, "INTERVENCAO", f"Intervenção necessária em '{p.retomar_em}'", motivo, "gestor")

    # ------------------------------------------------------------ passos
    def _recebido(self, p: Pedido):
        self._mudar(p, E.EM_ANALISE, "pedido registado")

    def _analisar(self, p: Pedido):
        suspeitas = self.ag6.triagem_fontes(p)              # AG6 primeiro: pode degradar fontes
        clar = self.store.obter_artefacto(p.id, "clarificacoes", []) or []
        feedback = (self.store.obter_artefacto(p.id, "feedback_requisitos", {}) or {}).get("texto", "")
        r = self.ag2.executar(p, clar, feedback)
        aceites, excluidos = self.comp1.validar_proveniencia(p, r["requisitos"])
        self.store.guardar_artefacto(p.id, "requisitos", {
            "aceites": aceites, "excluidos": excluidos, "ambiguidades": r["ambiguidades"],
            "fontes_suspeitas": suspeitas, "validado_por": ""})

        bloqueantes = [a for a in r["ambiguidades"] if a.get("bloqueante")]
        if bloqueantes:
            self._mudar(p, E.AGUARDA_CLARIFICACAO, f"{len(bloqueantes)} ambiguidade(s) bloqueante(s)")
            self._aprovacao(p, "CLARIFICACAO", "O pedido precisa de clarificação do autor",
                            "\n".join(a["pergunta"] for a in bloqueantes), p.autor)
        else:
            self._mudar(p, E.AGUARDA_VALIDACAO_REQUISITOS,
                        f"{len(aceites)} requisito(s) aceite(s), {len(excluidos)} excluído(s)")
            self._aprovacao(p, "VALIDAR_REQUISITOS", "Validar requisitos derivados pelo AG2",
                            f"{len(aceites)} aceites, {len(excluidos)} excluídos por proveniência", "revisor")

    def _planear(self, p: Pedido):
        req = self.store.obter_artefacto(p.id, "requisitos")
        plano = {
            "versao": 1,
            "tarefas": [
                {"id": "T1", "descricao": "Analisar impacto e dependências", "responsavel": "AG3",
                 "depende_de": [], "criterio": "componentes e ficheiros identificados"},
                {"id": "T2", "descricao": "Produzir proposta em área isolada", "responsavel": "AG4",
                 "depende_de": ["T1"], "criterio": "proposta referencia requisitos aceites"},
                {"id": "T3", "descricao": "Executar testes de aceitação em sandbox", "responsavel": "AG5",
                 "depende_de": ["T2"], "criterio": "0 falhas e 0 erros"},
                {"id": "T4", "descricao": "Classificar risco da proposta", "responsavel": "AG6",
                 "depende_de": ["T3"], "criterio": "risco justificado e não bloqueante"},
                {"id": "T5", "descricao": "Aprovar integração (Nível 2)", "responsavel": "Revisor Humano",
                 "depende_de": ["T4"], "criterio": "decisão registada"},
            ],
            "riscos": ["Alteração ao módulo de autenticação (segurança)."]
                      + [f"Fonte com confiança reduzida: {s['fonte']}" for s in req["fontes_suspeitas"]],
            "pressupostos": [a["pressuposto"] for a in req["ambiguidades"] if a.get("pressuposto")],
            "interface": INTERFACE,
        }
        self.store.guardar_artefacto(p.id, "plano", plano)
        self._mudar(p, E.EM_ANALISE_IMPACTO, "plano criado")

    def _impacto(self, p: Pedido):
        impacto = self.ag3.executar(p)
        self.store.guardar_artefacto(p.id, "impacto", impacto)
        self._mudar(p, E.EM_DESENVOLVIMENTO, f"{len(impacto['ficheiros_relevantes'])} ficheiro(s) relevantes")

    def _desenvolver(self, p: Pedido):
        if p.iteracoes_ciclo >= self.limites["max_iteracoes"]:   # RNF10 / RF9
            self._intervencao(p, f"limite de {self.limites['max_iteracoes']} iterações de correção atingido")
            return
        p.iteracao += 1
        p.iteracoes_ciclo += 1
        self.store.guardar_pedido(p)
        feedback = (self.store.obter_artefacto(p.id, "feedback_desenvolvimento", {}) or {}).get("texto", "")
        try:
            versao = self.ag4.executar(p, self.store.obter_artefacto(p.id, "plano"),
                                       self.store.obter_artefacto(p.id, "impacto"), feedback)
        except FerramentaBloqueada as e:                          # proposta recusada pelo COMP1
            self._feedback(p, f"A proposta foi recusada pelo COMP1: {e}")
            return                                                # próxima iteração (mesmo estado)
        self._mudar(p, E.EM_TESTES, f"proposta v{versao} criada")

    def _testar(self, p: Pedido):
        proposta = self.store.obter_artefacto(p.id, f"proposta_v{p.iteracao}")
        transitar_proposta(proposta, "Em testes")
        resultado = self.ag5.executar(p, p.iteracao)
        if resultado["sucesso"]:
            transitar_proposta(proposta, "Em revisão de segurança")
            self.store.guardar_artefacto(p.id, f"proposta_v{p.iteracao}", proposta)
            self._mudar(p, E.EM_REVISAO_SEGURANCA, f"{resultado['passados']} teste(s) passaram")
        else:
            transitar_proposta(proposta, "Testes falhados")
            transitar_proposta(proposta, "Substituída", "nova iteração")
            self.store.guardar_artefacto(p.id, f"proposta_v{p.iteracao}", proposta)
            self._feedback(p, "Os testes falharam:\n" + resultado["saida"][-1500:])
            self._mudar(p, E.EM_DESENVOLVIMENTO, f"{resultado['falhados']} falha(s), {resultado['erros']} erro(s)")

    def _rever(self, p: Pedido):
        proposta = self.store.obter_artefacto(p.id, f"proposta_v{p.iteracao}")
        testes = self.store.obter_artefacto(p.id, f"testes_v{p.iteracao}")
        excluidos = self.store.obter_artefacto(p.id, "requisitos")["excluidos"]
        risco = self.ag6.avaliar_risco(p, p.iteracao, testes, excluidos)
        self.store.guardar_artefacto(p.id, f"risco_v{p.iteracao}", risco)
        if risco["nivel"] == "bloqueante":
            transitar_proposta(proposta, "Bloqueada pela revisão")
            transitar_proposta(proposta, "Substituída", "nova iteração")
            self.store.guardar_artefacto(p.id, f"proposta_v{p.iteracao}", proposta)
            self._feedback(p, "Revisão de segurança bloqueou a proposta: " + "; ".join(risco["fatores"]))
            self._mudar(p, E.EM_DESENVOLVIMENTO, "risco bloqueante")
            return
        transitar_proposta(proposta, "Aguarda aprovação")
        self.store.guardar_artefacto(p.id, f"proposta_v{p.iteracao}", proposta)
        self._mudar(p, E.AGUARDA_APROVACAO, f"risco {risco['nivel']}")
        self._aprovacao(p, "INTEGRAR_PROPOSTA", f"Integrar proposta v{p.iteracao} no repositório principal",
                        "Risco " + risco["nivel"] + ": " + " ".join(risco["fatores"]), "revisor")

    def _feedback(self, p: Pedido, texto: str) -> None:
        self.store.guardar_artefacto(p.id, "feedback_desenvolvimento", {"texto": texto})
        self.audit.registar(p.id, "feedback", "AG1", texto.splitlines()[0][:150])

    @staticmethod
    def resumo_json(d) -> str:
        return json.dumps(d, ensure_ascii=False, indent=2)

"""Fábrica — ponto de entrada do núcleo (usado pela interface web e pela CLI).

Junta todos os componentes e expõe só três operações:
  submeter()  — regista um pedido (UC1)
  executar()  — corre o fluxo até à próxima espera humana (síncrono ou em fundo)
  decidir()   — regista uma decisão humana e retoma o fluxo (UC3, UC18)

O núcleo não importa nada da FastAPI: funciona igual a partir da web, da
linha de comandos ou dos testes.
"""
from __future__ import annotations

import concurrent.futures as cf
import json
import os
import shutil
from pathlib import Path

from . import config
from .auditoria import Auditoria, Redator
from .comp1 import Comp1
from .ferramentas import Ferramentas
from .llm import criar_llm
from .modelos import EstadoPedido as E, Pedido, TipoAprovacao, agora, novo_id, transitar_proposta
from .orquestrador import Orquestrador
from .politicas import Politicas
from .store import Store

UTILIZADORES = {
    "ana": {"nome": "Ana — Autora da Issue", "papel": "autor"},
    "rui": {"nome": "Rui — Revisor Humano", "papel": "revisor"},
    "sofia": {"nome": "Sofia — Auditora", "papel": "auditor"},
}


class DecisaoInvalida(Exception):
    pass


class Fabrica:
    def __init__(self, pasta_dados: Path | None = None, cfg: dict | None = None, llm=None):
        self.cfg = cfg or config.carregar()
        # pasta de dados: argumento > variável ASF_DADOS > ./dados
        self.pasta = Path(pasta_dados or os.environ.get("ASF_DADOS") or config.RAIZ / "dados")
        self.redator = Redator(config.segredos(self.cfg))
        self.store = Store(self.pasta)
        self.audit = Auditoria(self.pasta / "audit.jsonl", self.redator)
        self.politicas = Politicas.carregar(config.RAIZ / "politicas.json")
        self.repo_principal = self.pasta / "repo_principal"
        if not self.repo_principal.exists():
            shutil.copytree(config.RAIZ / "repo_sim", self.repo_principal,
                            ignore=shutil.ignore_patterns("__pycache__"))
        limites = self.cfg["limites"]
        self.comp1 = Comp1(self.politicas, self.store, self.audit, self.redator, limites)
        self.comp1.ferramentas = Ferramentas(self.store, self.audit, self.comp1, self.repo_principal, limites)
        self.llm = llm or criar_llm(self.cfg)
        self.orquestrador = Orquestrador(self.store, self.comp1, self.audit, self.llm, limites)
        # Um único trabalhador: os pedidos são processados um de cada vez
        self._executor = cf.ThreadPoolExecutor(max_workers=1)

    # ------------------------------------------------------------ comandos
    def submeter(self, titulo: str, descricao: str, criterios: list[str], autor: str = "ana",
                 fonte_id: str = "", cenario: dict | None = None, prioridade: str = "Must") -> str:
        pid = novo_id("PED")
        p = Pedido(id=pid, titulo=titulo.strip(), descricao=descricao.strip(),
                   criterios=[c.strip() for c in criterios if c.strip()], autor=autor,
                   fonte_id=fonte_id or f"issue:{pid}", cenario=cenario or {}, prioridade=prioridade)
        self.store.guardar_pedido(p)
        self.audit.registar(pid, "pedido_recebido", autor, p.titulo, fonte=p.fonte_id,
                            llm=self.llm.nome, cenario=p.cenario)
        return pid

    def submeter_ficheiro(self, ficheiro: Path, cenario: dict | None = None) -> str:
        d = json.loads(Path(ficheiro).read_text(encoding="utf-8"))
        return self.submeter(d["titulo"], d["descricao"], d["criterios"], fonte_id=d["fonte_id"],
                             cenario=cenario, prioridade=d.get("prioridade", "Must"))

    def executar(self, pedido_id: str) -> None:
        self.orquestrador.avancar(pedido_id)

    def executar_em_fundo(self, pedido_id: str):
        return self._executor.submit(self.orquestrador.avancar, pedido_id)

    def decidir(self, aprovacao_id: str, decisao: str, utilizador: str, comentario: str = "",
                em_fundo: bool = True) -> str:
        """Única forma de resolver um pedido de aprovação. Só humanos chegam aqui."""
        a = self.store.obter_aprovacao(aprovacao_id)
        if not a or a.estado != "pendente":
            raise DecisaoInvalida("aprovação inexistente ou já decidida")
        u = UTILIZADORES.get(utilizador)
        if not u or u["papel"] != a.papel_decisor:
            raise DecisaoInvalida(f"só um utilizador com papel '{a.papel_decisor}' pode decidir")
        if decisao not in a.opcoes:
            raise DecisaoInvalida(f"decisão inválida; opções: {a.opcoes}")
        p = self.store.obter_pedido(a.pedido_id)
        if a.papel_decisor == "revisor" and utilizador == p.autor:
            raise DecisaoInvalida("separação de funções: o autor não pode aprovar o próprio pedido")
        if decisao in ("responder", "pedir_revisao", "pedir_correcoes") and not comentario.strip():
            raise DecisaoInvalida("esta decisão exige um comentário")

        a.estado, a.decisao, a.decidido_por, a.decidido_em, a.comentario = (
            "decidido", decisao, utilizador, agora(), comentario.strip())
        self.store.guardar_aprovacao(a)
        self.audit.registar(p.id, "decisao_humana", utilizador, f"{a.id} {a.tipo}: {decisao}",
                            aprovacao_id=a.id, comentario=comentario.strip())
        self._aplicar(p, a, decisao, utilizador, comentario.strip())
        if p.estado_enum not in (E.CONCLUIDO, E.REJEITADO, E.INTERROMPIDO):
            # retoma o fluxo a partir do estado gravado
            self.executar_em_fundo(p.id) if em_fundo else self.executar(p.id)
        return p.id

    # ------------------------------------------------------------ efeitos das decisões
    def _mudar(self, p: Pedido, novo: E, motivo: str) -> None:
        anterior = p.estado
        p.transitar(novo, motivo)
        self.store.guardar_pedido(p)
        self.audit.registar(p.id, "transicao_estado", "humano", f"{anterior} -> {novo.value} ({motivo})")

    def _aplicar(self, p: Pedido, a, decisao: str, utilizador: str, comentario: str) -> None:
        tipo = TipoAprovacao(a.tipo)
        if tipo == TipoAprovacao.CLARIFICACAO:
            if decisao == "responder":
                clar = self.store.obter_artefacto(p.id, "clarificacoes", []) or []
                clar.append({"fonte_id": f"{p.fonte_id}:clarificacao:{len(clar) + 1}", "texto": comentario})
                self.store.guardar_artefacto(p.id, "clarificacoes", clar)
                self._mudar(p, E.EM_ANALISE, "autor respondeu")
            else:
                self._mudar(p, E.INTERROMPIDO, "autor cancelou")

        elif tipo == TipoAprovacao.VALIDAR_REQUISITOS:
            if decisao == "aprovar":
                req = self.store.obter_artefacto(p.id, "requisitos")
                req["validado_por"] = utilizador
                self.store.guardar_artefacto(p.id, "requisitos", req)
                self._mudar(p, E.EM_PLANEAMENTO, "requisitos validados")
            elif decisao == "pedir_revisao":
                self.store.guardar_artefacto(p.id, "feedback_requisitos", {"texto": comentario})
                self._mudar(p, E.EM_ANALISE, "revisor pediu revisão")
            else:
                self._mudar(p, E.REJEITADO, "requisitos rejeitados")

        elif tipo == TipoAprovacao.INTEGRAR_PROPOSTA:
            proposta = self.store.obter_artefacto(p.id, f"proposta_v{p.iteracao}")
            if decisao == "aprovar":
                self._integrar(p, proposta, utilizador)
                transitar_proposta(proposta, "Integrada", f"aprovada por {utilizador}")
                self.store.guardar_artefacto(p.id, f"proposta_v{p.iteracao}", proposta)
                self._mudar(p, E.CONCLUIDO, "integração aprovada")
            elif decisao == "pedir_correcoes":
                transitar_proposta(proposta, "Substituída", "revisor pediu correções")
                self.store.guardar_artefacto(p.id, f"proposta_v{p.iteracao}", proposta)
                self.store.guardar_artefacto(p.id, "feedback_desenvolvimento",
                                             {"texto": f"Correções pedidas pelo revisor: {comentario}"})
                p.iteracoes_ciclo = 0
                self._mudar(p, E.EM_DESENVOLVIMENTO, "revisor pediu correções")
            else:
                transitar_proposta(proposta, "Rejeitada", f"rejeitada por {utilizador}")
                self.store.guardar_artefacto(p.id, f"proposta_v{p.iteracao}", proposta)
                self._mudar(p, E.REJEITADO, "proposta rejeitada")

        elif tipo == TipoAprovacao.INTERVENCAO:
            if decisao == "retomar":
                p.iteracoes_ciclo = 0
                if p.cenario.get("falha_smtp"):   # simulação: o humano resolveu a causa externa
                    p.cenario["falha_smtp"] = False
                    self.audit.registar(p.id, "servico_reposto", utilizador,
                                        "serviço SMTP simulado volta a responder (cenário de falha)")
                self._mudar(p, E(p.retomar_em), "revisor mandou retomar")
            else:
                self._mudar(p, E.INTERROMPIDO, "revisor interrompeu")

    def _integrar(self, p: Pedido, proposta: dict, utilizador: str) -> None:
        """Ação de Nível 2: só acontece aqui, depois de uma aprovação humana registada (RNF8)."""
        for caminho, conteudo in proposta["ficheiros"].items():
            destino = self.repo_principal / caminho
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(conteudo, encoding="utf-8")
        self.audit.registar(p.id, "integracao_repositorio", utilizador,
                            f"proposta v{proposta['versao']} integrada no repositório principal (Nível 2)",
                            ficheiros=list(proposta["ficheiros"]))

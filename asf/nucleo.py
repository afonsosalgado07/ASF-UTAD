"""Fábrica — ponto de entrada do núcleo (usado pela interface web e pela CLI).

Junta todos os componentes e expõe só quatro operações:
  registar_projeto() — o Gestor adiciona um repositório (.zip ou pasta)
  submeter()         — regista um pedido sobre um projeto (UC1)
  executar()         — corre o fluxo até à próxima espera humana (síncrono ou em fundo)
  decidir()          — regista uma decisão humana e retoma o fluxo (UC3, UC18)

Store, Auditoria e LLM são partilhados. Cada projeto tem o seu "Ambiente":
políticas com os caminhos desse projeto, COMP1, ferramentas a apontar para o
repositório principal desse projeto e o orquestrador. Um pedido só vê o
ambiente do seu projeto.

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
from .modelos import EstadoPedido as E, Pedido, Projeto, TipoAprovacao, agora, novo_id, transitar_proposta
from .orquestrador import Orquestrador
from .politicas import Politicas
from .projetos import (ProjetoInvalido, configurar, copiar_pasta, criar_id, extrair_zip,
                       segredos_do_repositorio)
from .store import Store

UTILIZADORES = {
    "ana": {"nome": "Ana — Autora da Issue", "papel": "autor"},
    "rui": {"nome": "Rui — Revisor Humano", "papel": "revisor"},
    "marta": {"nome": "Marta — Gestora de Projeto", "papel": "gestor"},
    "sofia": {"nome": "Sofia — Auditora", "papel": "auditor"},
}


class DecisaoInvalida(Exception):
    pass


class Ambiente:
    """Componentes de controlo ligados a UM projeto."""

    def __init__(self, fab: "Fabrica", projeto: Projeto):
        self.projeto = projeto
        self.repo = fab.store.pasta_repo(projeto.id)
        self.politicas = fab.politicas.para_projeto(projeto)
        limites = fab.cfg["limites"]
        fab.redator.adicionar(segredos_do_repositorio(self.repo, projeto.caminhos_sensiveis + ["*.env"]))
        self.comp1 = Comp1(self.politicas, fab.store, fab.audit, fab.redator, limites, projeto.id)
        self.comp1.ferramentas = Ferramentas(fab.store, fab.audit, self.comp1, self.repo, limites, projeto)
        self.orquestrador = Orquestrador(fab.store, self.comp1, fab.audit, fab.llm, limites, projeto)


class Fabrica:
    def __init__(self, pasta_dados: Path | None = None, cfg: dict | None = None, llm=None):
        self.cfg = cfg or config.carregar()
        # pasta de dados: argumento > variável ASF_DADOS > ./dados
        self.pasta = Path(pasta_dados or os.environ.get("ASF_DADOS") or config.RAIZ / "dados")
        self.redator = Redator(config.segredos(self.cfg))
        self.store = Store(self.pasta)
        self.audit = Auditoria(self.pasta / "audit.jsonl", self.redator)
        self.audit.projeto_de = self._projeto_da_correlacao
        self.politicas = Politicas.carregar(config.RAIZ / "politicas.json")
        self.llm = llm or criar_llm(self.cfg)
        self._ambientes: dict[str, Ambiente] = {}
        self._migrar_dados_antigos()
        for proj in self.store.listar_projetos():           # segredos de todos os projetos no Redator
            self.ambiente(proj.id)
        # Um único trabalhador: os pedidos são processados um de cada vez
        self._executor = cf.ThreadPoolExecutor(max_workers=1)

    def _projeto_da_correlacao(self, correlacao: str) -> str:
        if correlacao.startswith("PROJ:"):
            return correlacao[5:]
        if correlacao.startswith("PED-"):
            p = self.store.obter_pedido(correlacao)
            return p.projeto_id if p else ""
        return ""

    def _migrar_dados_antigos(self) -> None:
        """Migração da versão de um só projeto: dados/repo_principal + pedidos sem projeto.
        Cria o projeto "reset-password" com esse repositório e associa-lhe os pedidos antigos.
        Idempotente: só corre se houver pedidos sem projeto."""
        antigos = [p for p in self.store.listar_pedidos() if not p.projeto_id]
        repo_antigo = self.pasta / "repo_principal"
        if not antigos:
            return
        pid = "reset-password"
        if not self.store.obter_projeto(pid):
            destino = self.store.pasta_repo(pid)
            if repo_antigo.is_dir():
                copiar_pasta(repo_antigo, destino)
            else:
                destino.mkdir(parents=True, exist_ok=True)
            proj = Projeto(id=pid, nome="Reset Password (migrado)", descricao="Projeto criado pela migração "
                           "da versão de um só projeto (repositório simulado da Issue #184).",
                           pasta_codigo="auth", pasta_testes="tests", pasta_docs="docs",
                           caminhos_sensiveis=["config/*"], areas_criticas=["auth/*"],
                           origem="migração de dados/repo_principal", criado_por="migracao")
            self.store.guardar_projeto(proj)
            self.audit.registar(f"PROJ:{pid}", "projeto_registado", "migracao",
                                "projeto criado pela migração dos dados de um só projeto", projeto=pid)
        for p in antigos:
            p.projeto_id = pid
            self.store.guardar_pedido(p)
            self.audit.registar(p.id, "migracao_projeto", "migracao", f"pedido associado ao projeto '{pid}'",
                                projeto=pid)

    def ambiente(self, projeto_id: str) -> Ambiente:
        if projeto_id not in self._ambientes:
            proj = self.store.obter_projeto(projeto_id)
            if not proj:
                raise ProjetoInvalido(f"projeto '{projeto_id}' não existe")
            self._ambientes[projeto_id] = Ambiente(self, proj)
        return self._ambientes[projeto_id]

    def ambiente_do_pedido(self, pedido_id: str) -> Ambiente:
        return self.ambiente(self.store.obter_pedido(pedido_id).projeto_id)

    # ------------------------------------------------------------ projetos
    def registar_projeto(self, nome: str, origem: Path | bytes, utilizador: str, *, nome_origem: str = "",
                         descricao: str = "", pasta_codigo: str = "", pasta_testes: str = "tests",
                         pasta_docs: str = "docs", sensiveis: list[str] | None = None,
                         criticas: list[str] | None = None) -> str:
        """Só o Gestor de Projeto regista projetos. origem = bytes de um .zip ou caminho de uma pasta/zip."""
        u = UTILIZADORES.get(utilizador)
        if not u or u["papel"] != "gestor":
            raise ProjetoInvalido("só um utilizador com papel 'gestor' pode adicionar projetos")
        existentes = {p.id for p in self.store.listar_projetos()}
        pid = criar_id(nome, existentes)
        repo = self.store.pasta_repo(pid)
        try:
            if isinstance(origem, (bytes, bytearray)):
                extrair_zip(bytes(origem), repo)
            elif Path(origem).is_file():
                nome_origem = nome_origem or Path(origem).name
                extrair_zip(Path(origem).read_bytes(), repo)
            else:
                nome_origem = nome_origem or Path(origem).name
                copiar_pasta(Path(origem), repo)
            proj = configurar(repo, pid, nome, descricao, pasta_codigo, pasta_testes, pasta_docs,
                              ["config/*"] if sensiveis is None else sensiveis, criticas or [],
                              nome_origem, utilizador)
        except Exception:
            shutil.rmtree(self.store.pasta_projetos / pid, ignore_errors=True)
            raise
        self.store.guardar_projeto(proj)
        self.ambiente(pid)
        self.audit.registar(f"PROJ:{pid}", "projeto_registado", utilizador,
                            f"projeto '{proj.nome}' registado ({nome_origem or 'origem desconhecida'})",
                            projeto=pid, codigo=proj.pasta_codigo, testes=proj.pasta_testes,
                            docs=proj.pasta_docs, sensiveis=proj.caminhos_sensiveis)
        return pid

    # ------------------------------------------------------------ comandos
    def submeter(self, projeto_id: str, titulo: str, descricao: str, criterios: list[str], autor: str = "ana",
                 fonte_id: str = "", cenario: dict | None = None, prioridade: str = "Must") -> str:
        if not self.store.obter_projeto(projeto_id):
            raise ProjetoInvalido(f"projeto '{projeto_id}' não existe")
        if fonte_id and not fonte_id.startswith("issue:"):
            # a confiança vem da origem: um pedido nunca se pode apresentar como humano:* ou config:*
            raise ValueError("a origem de um pedido tem de ser 'issue:…'")
        pid = novo_id("PED")
        p = Pedido(id=pid, titulo=titulo.strip(), descricao=descricao.strip(),
                   criterios=[c.strip() for c in criterios if c.strip()], autor=autor,
                   fonte_id=fonte_id or f"issue:{pid}", projeto_id=projeto_id,
                   cenario=cenario or {}, prioridade=prioridade)
        self.store.guardar_pedido(p)
        self.audit.registar(pid, "pedido_recebido", autor, p.titulo, fonte=p.fonte_id, projeto=projeto_id,
                            llm=self.llm.nome, cenario=p.cenario)
        return pid

    def submeter_ficheiro(self, projeto_id: str, ficheiro: Path, cenario: dict | None = None,
                          autor: str = "ana") -> str:
        d = ler_issue(Path(ficheiro).read_text(encoding="utf-8"))
        return self.submeter(projeto_id, d["titulo"], d["descricao"], d["criterios"], autor=autor,
                             fonte_id=d["fonte_id"], cenario=cenario, prioridade=d["prioridade"])

    def executar(self, pedido_id: str) -> None:
        self.ambiente_do_pedido(pedido_id).orquestrador.avancar(pedido_id)

    def executar_em_fundo(self, pedido_id: str):
        return self._executor.submit(self.executar, pedido_id)

    def decidir(self, aprovacao_id: str, decisao: str, utilizador: str, comentario: str = "",
                em_fundo: bool = True, projeto_ativo: str | None = None) -> str:
        """Única forma de resolver um pedido de aprovação. Só humanos chegam aqui.
        projeto_ativo (interface): a decisão só é aceite se o pedido pertencer ao projeto selecionado."""
        a = self.store.obter_aprovacao(aprovacao_id)
        if not a or a.estado != "pendente":
            raise DecisaoInvalida("aprovação inexistente ou já decidida")
        if projeto_ativo is not None:
            dono = self.store.obter_pedido(a.pedido_id).projeto_id
            if dono != projeto_ativo:
                raise DecisaoInvalida(f"o pedido pertence ao projeto '{dono}'; selecione esse projeto para decidir")
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
                if p.cenario.get("falha_servico"):   # simulação: o humano resolveu a causa externa
                    p.cenario["falha_servico"] = False
                    self.audit.registar(p.id, "servico_reposto", utilizador,
                                        "serviço externo simulado volta a responder (cenário de falha)")
                self._mudar(p, E(p.retomar_em), f"{utilizador} mandou retomar")
            else:
                self._mudar(p, E.INTERROMPIDO, f"{utilizador} interrompeu")

    def _integrar(self, p: Pedido, proposta: dict, utilizador: str) -> None:
        """Ação de Nível 2: só acontece aqui, depois de uma aprovação humana registada (RNF8).
        Integra o código da proposta E os testes de aceitação que o validaram."""
        repo = self.ambiente(p.projeto_id).repo
        testes = (self.store.obter_artefacto(p.id, "testes_aceitacao", {}) or {}).get("ficheiros", {})
        ficheiros = {**proposta["ficheiros"], **testes}
        for caminho, conteudo in ficheiros.items():
            destino = (repo / caminho).resolve()
            if repo.resolve() not in destino.parents:      # defesa em profundidade
                raise DecisaoInvalida(f"caminho fora do repositório: {caminho}")
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text(conteudo, encoding="utf-8")
        self.audit.registar(p.id, "integracao_repositorio", utilizador,
                            f"proposta v{proposta['versao']} integrada no repositório principal do projeto "
                            f"'{p.projeto_id}' (Nível 2)", ficheiros=list(ficheiros), projeto=p.projeto_id)


def ler_issue(texto: str) -> dict:
    """Lê uma Issue em JSON ({titulo, descricao, criterios, fonte_id?, prioridade?})."""
    try:
        d = json.loads(texto)
    except json.JSONDecodeError as e:
        raise ValueError(f"o ficheiro da Issue não é JSON válido: {e}") from None
    if not isinstance(d, dict) or not str(d.get("titulo", "")).strip() or not str(d.get("descricao", "")).strip():
        raise ValueError("a Issue tem de ter 'titulo' e 'descricao'")
    criterios = d.get("criterios", [])
    if isinstance(criterios, str):
        criterios = criterios.splitlines()
    fonte = str(d.get("fonte_id", "")).strip()
    if fonte and not fonte.startswith("issue:"):
        raise ValueError("'fonte_id' tem de começar por 'issue:' (ex.: issue:12)")
    return {"titulo": str(d["titulo"]), "descricao": str(d["descricao"]),
            "criterios": [str(c) for c in criterios if str(c).strip()], "fonte_id": fonte,
            "prioridade": d.get("prioridade", "Must") if d.get("prioridade") in ("Must", "Should", "Could", "Won't")
            else "Must"}

"""Persistência em ficheiros JSON — uma pasta por pedido.

    dados/
    ├── projetos/<id>/
    │   ├── projeto.json         configuração do projeto (registada pelo Gestor)
    │   └── repo/                repositório principal do projeto (só muda por ação humana)
    ├── pedidos/PED-XXXXXX/
    │   ├── pedido.json          estado, histórico, iteração
    │   ├── aprovacoes.json      pedidos de aprovação e decisões
    │   ├── requisitos.json      artefacto do AG2
    │   ├── plano.json           artefacto do AG1
    │   ├── impacto.json         artefacto do AG3
    │   ├── proposta_v1.json     artefacto do AG4 (uma por iteração)
    │   ├── testes_v1.json       artefacto do AG5
    │   ├── risco_v1.json        artefacto do AG6
    │   └── fontes.json          classificação de confiança das fontes usadas
    └── audit.jsonl              auditoria global append-only

O resto do código nunca lê/escreve ficheiros diretamente: usa só esta classe.
Trocar para SQLite no futuro implica reescrever apenas este módulo.
"""
from __future__ import annotations

import json
import os
import threading
from pathlib import Path

from .modelos import Pedido, PedidoAprovacao, Projeto


class Store:
    def __init__(self, raiz: Path):
        self.raiz = Path(raiz)
        self.pasta_pedidos = self.raiz / "pedidos"
        self.pasta_pedidos.mkdir(parents=True, exist_ok=True)
        self.pasta_projetos = self.raiz / "projetos"
        self.pasta_projetos.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

    # ---------------------------------------------------------- utilitários
    def _escrever(self, ficheiro: Path, dados) -> None:
        """Escrita segura: escreve num temporário e só depois substitui."""
        ficheiro.parent.mkdir(parents=True, exist_ok=True)
        tmp = ficheiro.with_suffix(ficheiro.suffix + ".tmp")
        tmp.write_text(json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, ficheiro)

    def _ler(self, ficheiro: Path, defeito=None):
        if not ficheiro.exists():
            return defeito
        return json.loads(ficheiro.read_text(encoding="utf-8"))

    def _pasta(self, pedido_id: str) -> Path:
        return self.pasta_pedidos / pedido_id

    # -------------------------------------------------------------- projetos
    def guardar_projeto(self, p: Projeto) -> None:
        with self._lock:
            self._escrever(self.pasta_projetos / p.id / "projeto.json", p.to_dict())

    def obter_projeto(self, projeto_id: str) -> Projeto | None:
        if not projeto_id or "/" in projeto_id or "\\" in projeto_id or projeto_id.startswith("."):
            return None
        with self._lock:
            d = self._ler(self.pasta_projetos / projeto_id / "projeto.json")
        return Projeto.from_dict(d) if d else None

    def listar_projetos(self) -> list[Projeto]:
        projetos = [self.obter_projeto(p.name) for p in self.pasta_projetos.iterdir() if p.is_dir()]
        return sorted((p for p in projetos if p), key=lambda p: p.criado_em)

    def pasta_repo(self, projeto_id: str) -> Path:
        return self.pasta_projetos / projeto_id / "repo"

    # --------------------------------------------------------------- pedidos
    def guardar_pedido(self, p: Pedido) -> None:
        with self._lock:
            self._escrever(self._pasta(p.id) / "pedido.json", p.to_dict())

    def obter_pedido(self, pedido_id: str) -> Pedido | None:
        with self._lock:
            d = self._ler(self._pasta(pedido_id) / "pedido.json")
        return Pedido.from_dict(d) if d else None

    def listar_pedidos(self, projeto_id: str | None = None) -> list[Pedido]:
        pedidos = []
        for pasta in self.pasta_pedidos.iterdir():
            p = self.obter_pedido(pasta.name)
            if p and (projeto_id is None or p.projeto_id == projeto_id):
                pedidos.append(p)
        return sorted(pedidos, key=lambda p: p.criado_em, reverse=True)

    # ------------------------------------------------------------ artefactos
    def guardar_artefacto(self, pedido_id: str, nome: str, dados: dict) -> None:
        with self._lock:
            self._escrever(self._pasta(pedido_id) / f"{nome}.json", dados)

    def obter_artefacto(self, pedido_id: str, nome: str, defeito=None):
        with self._lock:
            return self._ler(self._pasta(pedido_id) / f"{nome}.json", defeito)

    # ------------------------------------------------------------ aprovações
    def _aprovacoes(self, pedido_id: str) -> list[PedidoAprovacao]:
        lista = self._ler(self._pasta(pedido_id) / "aprovacoes.json", [])
        return [PedidoAprovacao.from_dict(a) for a in lista]

    def guardar_aprovacao(self, a: PedidoAprovacao) -> None:
        with self._lock:
            lista = [x for x in self._aprovacoes(a.pedido_id) if x.id != a.id] + [a]
            lista.sort(key=lambda x: x.criado_em)
            self._escrever(self._pasta(a.pedido_id) / "aprovacoes.json", [x.to_dict() for x in lista])

    def aprovacoes_do_pedido(self, pedido_id: str) -> list[PedidoAprovacao]:
        with self._lock:
            return self._aprovacoes(pedido_id)

    def obter_aprovacao(self, aprovacao_id: str) -> PedidoAprovacao | None:
        for p in self.listar_pedidos():
            for a in self.aprovacoes_do_pedido(p.id):
                if a.id == aprovacao_id:
                    return a
        return None

    def aprovacoes_pendentes(self) -> list[PedidoAprovacao]:
        pend = []
        for p in self.listar_pedidos():
            pend += [a for a in self.aprovacoes_do_pedido(p.id) if a.estado == "pendente"]
        return pend

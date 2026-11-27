"""Políticas de segurança e confiança (UC19, UC20).

Ficam em politicas.json para poderem ser alteradas sem mexer no código
(RNF17). O carregamento valida a configuração e rejeita-a se for inválida
(UC19, fluxo alternativo 3A/4A).

As regras são GLOBAIS (iguais para todos os projetos). Os caminhos usam
marcadores {codigo}, {testes}, {docs}; para cada projeto, para_projeto()
substitui-os pelas pastas desse projeto e junta os seus ficheiros sensíveis.
"""
from __future__ import annotations

import copy
import fnmatch
import json
import re
from pathlib import Path

from .modelos import Confianca

AGENTES_VALIDOS = {"AG1", "AG2", "AG3", "AG4", "AG5", "AG6"}
CHAVES_CAMINHOS = ("caminhos_escrita_proposta", "caminhos_escrita_testes",
                   "caminhos_leitura_codigo", "caminhos_leitura_docs")
MARCADORES = {"codigo", "testes", "docs"}


class ConfiguracaoInvalida(Exception):
    pass


class Politicas:
    def __init__(self, dados: dict):
        self._validar(dados)
        self.dados = dados
        self.ferramentas: dict = dados["ferramentas"]
        self.matriz: dict[str, set[str]] = {a: set(t) for a, t in dados["matriz_permissoes"].items()}

    @classmethod
    def carregar(cls, ficheiro: Path) -> "Politicas":
        try:
            dados = json.loads(Path(ficheiro).read_text(encoding="utf-8"))
        except UnicodeDecodeError as e:   # ex.: guardado em ANSI no Bloco de Notas do Windows
            raise ConfiguracaoInvalida(f"{ficheiro} não está em UTF-8 (guarde-o com codificação UTF-8): {e}") from e
        except (OSError, json.JSONDecodeError) as e:
            raise ConfiguracaoInvalida(f"Não foi possível ler {ficheiro}: {e}") from e
        return cls(dados)

    @staticmethod
    def _validar(d: dict) -> None:
        erros = []
        for chave in ("ferramentas", "matriz_permissoes", "fontes", *CHAVES_CAMINHOS):
            if chave not in d:
                erros.append(f"falta a secção '{chave}'")
        if erros:
            raise ConfiguracaoInvalida("; ".join(erros))
        for ag, tools in d["matriz_permissoes"].items():
            if ag not in AGENTES_VALIDOS:
                erros.append(f"agente desconhecido '{ag}'")
            for t in tools:
                if t not in d["ferramentas"]:
                    erros.append(f"{ag}: ferramenta não catalogada '{t}'")
                elif d["ferramentas"][t]["nivel"] == 2:
                    erros.append(f"{ag}: agentes não podem receber ferramentas de nível 2 ('{t}')")
        for r in d["fontes"]:
            if r.get("confianca") not in Confianca.__members__:
                erros.append(f"fonte '{r.get('padrao')}': confiança inválida")
        for chave in CHAVES_CAMINHOS:
            for padrao in d[chave]:
                for m in re.findall(r"\{(\w*)\}", padrao):
                    if m not in MARCADORES:
                        erros.append(f"{chave}: marcador desconhecido '{{{m}}}'")
                if ".." in padrao or padrao.startswith("/"):
                    erros.append(f"{chave}: caminho inválido '{padrao}'")
        if erros:
            raise ConfiguracaoInvalida("; ".join(erros))

    def para_projeto(self, projeto) -> "Politicas":
        """Cópia das políticas com os caminhos do projeto. Uma pasta vazia (ex.: projeto
        sem docs) não gera padrão nenhum: fica tudo bloqueado nessa área."""
        d = copy.deepcopy(self.dados)
        pastas = {"codigo": projeto.pasta_codigo, "testes": projeto.pasta_testes, "docs": projeto.pasta_docs}
        for chave in CHAVES_CAMINHOS:
            d[chave] = [p.format(**pastas) for p in d[chave]
                        if all(pastas[m] for m in re.findall(r"\{(\w+)\}", p))]
        sensiveis = [{"padrao": f"repo:{c}", "confianca": "T1", "sensivel": True}
                     for c in projeto.caminhos_sensiveis if c.strip()]
        d["fontes"] = sensiveis + d["fontes"]          # primeira regra que casa ganha
        return Politicas(d)

    def permitido(self, agente: str, ferramenta: str) -> bool:
        # RNF18 / RP11: o que não está explicitamente autorizado está bloqueado
        return ferramenta in self.matriz.get(agente, set())

    def classificar(self, fonte_id: str) -> tuple[Confianca, bool]:
        """Classificação pela ORIGEM, nunca pelo conteúdo. Primeira regra que casa."""
        for r in self.dados["fontes"]:
            if fnmatch.fnmatch(fonte_id, r["padrao"]):
                return Confianca[r["confianca"]], bool(r.get("sensivel", False))
        return Confianca.T0, False  # origem desconhecida = não confiável

    def caminho_permitido(self, caminho: str, chave: str) -> bool:
        return any(fnmatch.fnmatch(caminho, p) for p in self.dados[chave])

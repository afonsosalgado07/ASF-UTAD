"""Ferramentas TL1–TL14 de UM projeto.

Os agentes NUNCA chamam estes métodos diretamente: chamam
Comp1.chamar(agente, "TLx", ...), que valida permissões, argumentos e caminhos
antes de executar o método tlx() correspondente.

Ferramentas de leitura devolvem {"fonte_id", "conteudo"}; é o agente que
pede ao COMP1 para classificar esse conteúdo (Bloco) antes de o usar.
"""
from __future__ import annotations

import difflib
import fnmatch
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from .comp1 import FalhaTemporaria, FerramentaBloqueada
from .modelos import PedidoAprovacao, TipoAprovacao, novo_id
from .projetos import ficheiros_sensiveis

TESTE_RID = re.compile(r"^test_(r\d+)_", re.I)      # test_r3_qualquer_coisa -> requisito R3


class Ferramentas:
    def __init__(self, store, auditoria, comp1, repo_principal: Path, limites: dict, projeto):
        self.store = store
        self.audit = auditoria
        self.comp1 = comp1
        self.repo = Path(repo_principal)
        self.limites = limites
        self.projeto = projeto

    # ------------------------------------------------------------ leitura
    def tl1(self, pedido_id):
        p = self.store.obter_pedido(pedido_id)
        return {"fonte_id": p.fonte_id, "conteudo": p.texto()}

    def tl2(self, pedido_id):
        return (self.store.obter_artefacto(pedido_id, "requisitos", {}) or {}).get("aceites", [])

    def _ler_repo(self, caminho):
        alvo = (self.repo / caminho).resolve()
        if alvo != self.repo.resolve() and self.repo.resolve() not in alvo.parents:
            raise FerramentaBloqueada(f"'{caminho}' fora do repositório")
        if alvo.is_dir():
            conteudo = "\n".join(sorted(x.name + ("/" if x.is_dir() else "") for x in alvo.iterdir()
                                        if x.name not in ("__pycache__", ".pytest_cache")))
        elif alvo.is_file():
            conteudo = alvo.read_text(encoding="utf-8", errors="replace")
        else:
            raise FerramentaBloqueada(f"'{caminho}' não existe")
        return {"fonte_id": f"repo:{caminho}", "conteudo": conteudo}

    def tl3(self, caminho):
        return self._ler_repo(caminho)

    def tl4(self, caminho):
        return self._ler_repo(caminho)

    def tl5(self, modulo, pedido_id):
        """Analisa os imports do pacote e verifica serviços externos (simulados)."""
        deps = set()
        for f in (self.repo / modulo).rglob("*.py"):
            deps.update(re.findall(r"^\s*(?:from|import) ([\w\.]+)", f.read_text(encoding="utf-8", errors="ignore"), re.M))
        pedido = self.store.obter_pedido(pedido_id)
        if pedido.cenario.get("falha_servico"):
            raise FalhaTemporaria("serviço externo de análise de dependências não responde (ligação recusada)")
        internas = sorted(d for d in deps if d.startswith(".") or d.split(".")[0] == modulo)
        return {"dependencias_internas": internas, "dependencias_externas": sorted(deps - set(internas)),
                "servicos_externos": {"analise_dependencias": "disponível (simulado)"}}

    # ------------------------------------------------------------ escrita isolada
    def _diff(self, ficheiros: dict) -> str:
        diff = []
        for caminho, novo in ficheiros.items():
            f = self.repo / caminho
            antigo = f.read_text(encoding="utf-8") if f.exists() else ""
            diff += difflib.unified_diff(antigo.splitlines(), novo.splitlines(),
                                         f"a/{caminho}", f"b/{caminho}", lineterm="")
        return "\n".join(diff)

    def tl6(self, pedido_id, ficheiros, justificacao, requisitos_ref):
        aceites = {r["id"] for r in self.tl2(pedido_id)}
        desconhecidos = [r for r in requisitos_ref if r not in aceites]
        if not requisitos_ref or desconhecidos:
            raise FerramentaBloqueada(f"a proposta tem de referenciar requisitos aceites (RNF13); "
                                      f"inválidos: {desconhecidos or 'nenhum indicado'}")
        versao = self.store.obter_pedido(pedido_id).iteracao
        proposta = {"versao": versao, "estado": "Rascunho", "ficheiros": ficheiros,
                    "novos": [c for c in ficheiros if not (self.repo / c).exists()],
                    "diff": self._diff(ficheiros), "justificacao": justificacao,
                    "requisitos_ref": requisitos_ref, "historico": []}
        self.store.guardar_artefacto(pedido_id, f"proposta_v{versao}", proposta)
        return versao

    def tl14(self, pedido_id, ficheiros, sem_teste):
        """Guarda os testes de aceitação do AG5 (área isolada; só entram no repositório
        principal juntamente com a proposta, por decisão humana de Nível 2)."""
        aceites = {r["id"] for r in self.tl2(pedido_id)}
        ids_testes = set()
        for conteudo in ficheiros.values():
            ids_testes |= {m.upper() for m in re.findall(r"def test_(r\d+)_", conteudo, re.I)}
        desconhecidos = sorted(ids_testes - aceites)
        if not ids_testes or desconhecidos:
            raise FerramentaBloqueada("os testes têm de se chamar test_<requisito>_… e referir requisitos aceites; "
                                      f"inválidos: {desconhecidos or 'nenhum teste encontrado'}")
        artefacto = {"ficheiros": ficheiros, "cobertura": sorted(ids_testes),
                     "sem_teste": [str(s) for s in sem_teste], "diff": self._diff(ficheiros)}
        self.store.guardar_artefacto(pedido_id, "testes_aceitacao", artefacto)
        return sorted(ids_testes)

    def tl13(self, pedido_id, versao):
        return self.store.obter_artefacto(pedido_id, f"proposta_v{versao}")

    # ------------------------------------------------------------ testes (sandbox)
    def tl7(self, pedido_id, versao):
        """Corre TODOS os testes do projeto (regressão) + os de aceitação do AG5 numa cópia
        isolada do repositório. versao=0 corre sem proposta (linha de base)."""
        proposta = self.tl13(pedido_id, versao) if versao else {"ficheiros": {}}
        aceitacao = self.store.obter_artefacto(pedido_id, "testes_aceitacao", {}) or {}
        requisitos = self.tl2(pedido_id)
        pasta_testes = self.projeto.pasta_testes

        with tempfile.TemporaryDirectory(prefix="asf_sandbox_") as tmp:
            sandbox = Path(tmp) / "repo"
            shutil.copytree(self.repo, sandbox, ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache"))
            for f in ficheiros_sensiveis(sandbox, self.projeto.caminhos_sensiveis + ["*.env", "*.pem", "*.key"]):
                f.unlink()                                  # os testes nunca veem segredos
            for caminho, conteudo in {**proposta["ficheiros"], **aceitacao.get("ficheiros", {})}.items():
                (sandbox / caminho).parent.mkdir(parents=True, exist_ok=True)
                (sandbox / caminho).write_text(conteudo, encoding="utf-8")
            (sandbox / pasta_testes).mkdir(parents=True, exist_ok=True)
            relatorio_xml = Path(tmp) / "junit.xml"
            # Sem credenciais nem proxies no ambiente do processo de testes
            env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(sandbox), "PYTHONDONTWRITEBYTECODE": "1"}
            # No Windows, sem SYSTEMROOT o Python não inicializa a rede/asyncio (WinError 10106).
            env.update({k: os.environ[k] for k in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP") if k in os.environ})
            inicio = time.time()
            try:
                r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
                                    f"--junitxml={relatorio_xml}", pasta_testes],
                                   cwd=sandbox, env=env, capture_output=True, text=True,
                                   timeout=self.limites["timeout_testes_s"])
                saida = r.stdout + r.stderr
            except subprocess.TimeoutExpired:
                raise FalhaTemporaria(f"testes excederam {self.limites['timeout_testes_s']} s")
            casos = _ler_junit(relatorio_xml)

        def resumo(grupo):
            c = [x for x in casos if x["grupo"] == grupo]
            return {k: sum(1 for x in c if x["resultado"] == k) for k in ("passou", "falhou", "erro", "ignorado")}

        por_requisito = {}
        for r in requisitos:
            ts = [c for c in casos if c["requisito"] == r["id"].upper()]
            por_requisito[r["id"]] = {
                "testes": [c["nome"] for c in ts],
                "estado": "sem teste" if not ts else "passou" if all(c["resultado"] == "passou" for c in ts)
                else "falhou"}
        sem_teste = [f"{rid}: {next(r['descricao'] for r in requisitos if r['id'] == rid)}"
                     for rid, v in por_requisito.items() if v["estado"] == "sem teste"]
        conta = lambda k: sum(1 for c in casos if c["resultado"] == k)  # noqa: E731
        resultado = {"versao": versao, "passados": conta("passou"), "falhados": conta("falhou"),
                     "erros": conta("erro"), "ignorados": conta("ignorado"),
                     "duracao_s": round(time.time() - inicio, 2), "simulado": False,
                     "regressao": resumo("regressao"), "aceitacao": resumo("aceitacao"),
                     "por_requisito": por_requisito, "requisitos_sem_teste": sem_teste,
                     "nao_testaveis": aceitacao.get("sem_teste", []),
                     "casos": casos, "saida": self.comp1.redator.limpar(saida[-3000:])}
        if not casos and "error" in saida.lower():          # nem chegou a recolher testes
            resultado["erros"] = 1
        resultado["sucesso"] = (resultado["passados"] > 0 and resultado["falhados"] == 0
                                and resultado["erros"] == 0)
        self.store.guardar_artefacto(pedido_id, f"testes_v{versao}", resultado)
        return resultado

    def tl8(self, pedido_id, versao):
        t = self.store.obter_artefacto(pedido_id, f"testes_v{versao}")
        reg, ac = t["regressao"], t["aceitacao"]
        linhas = [f"Relatório de testes — proposta v{versao}",
                  f"Executados de facto em sandbox (não simulados): {not t['simulado']}",
                  f"Total: {t['passados']} passados, {t['falhados']} falhados, {t['erros']} erros ({t['duracao_s']} s)",
                  f"Regressão (testes existentes do projeto): {reg['passou']} passados, "
                  f"{reg['falhou'] + reg['erro']} com falha",
                  f"Aceitação (escritos pelo AG5 a partir dos requisitos): {ac['passou']} passados, "
                  f"{ac['falhou'] + ac['erro']} com falha"]
        for rid, v in t["por_requisito"].items():
            linhas.append(f"  {rid}: {v['estado']}" + (f" ({', '.join(v['testes'])})" if v["testes"] else ""))
        if t["requisitos_sem_teste"]:
            linhas.append("Requisitos SEM teste automático (verificação manual necessária): "
                          + "; ".join(t["requisitos_sem_teste"]))
        relatorio = "\n".join(linhas)
        self.store.guardar_artefacto(pedido_id, f"relatorio_testes_v{versao}", {"texto": relatorio})
        return relatorio

    # ------------------------------------------------------------ controlo
    def tl9(self, pedido_id, fonte_id, motivo):
        self.comp1.degradar(pedido_id, fonte_id, motivo, por="AG6")
        return True

    def tl10(self, pedido_id, tipo, resumo):
        self.audit.registar(pedido_id, tipo, "agente", resumo)
        return True

    def tl11(self, pedido_id, tipo, resumo, detalhe):
        """Cria o pedido de aprovação. NÃO decide — só um humano decide."""
        tipo = TipoAprovacao(tipo)
        a = PedidoAprovacao(id=novo_id("APR"), pedido_id=pedido_id, tipo=tipo.value,
                            nivel=2 if tipo == TipoAprovacao.INTEGRAR_PROPOSTA else 1,
                            resumo=resumo, detalhe=detalhe, solicitado_por="AG1")
        self.store.guardar_aprovacao(a)
        self.audit.registar(pedido_id, "aprovacao_solicitada", "AG1", f"{a.id} {tipo.value}: {resumo}",
                            aprovacao_id=a.id)
        return a.id

    def tl12(self, pedido_id, destinatario, mensagem):
        notificacoes = self.store.obter_artefacto(pedido_id, "notificacoes", []) or []
        notificacoes.append({"para": destinatario, "mensagem": self.comp1.redator.limpar(mensagem)})
        self.store.guardar_artefacto(pedido_id, "notificacoes", notificacoes)
        return True


def _ler_junit(ficheiro: Path) -> list[dict]:
    """Resultado de cada teste a partir do relatório JUnit do pytest."""
    if not ficheiro.exists():
        return []
    casos = []
    for tc in ET.parse(ficheiro).getroot().iter("testcase"):
        classe, nome = tc.get("classname", ""), tc.get("name", "")
        if tc.find("failure") is not None:
            resultado = "falhou"
        elif tc.find("error") is not None:
            resultado = "erro"
        elif tc.find("skipped") is not None:
            resultado = "ignorado"
        else:
            resultado = "passou"
        m = TESTE_RID.match(nome)
        grupo = "aceitacao" if "test_aceitacao_" in classe or "test_aceitacao_" in nome else "regressao"
        detalhe = ""
        for tag in ("failure", "error"):
            el = tc.find(tag)
            if el is not None:
                detalhe = (el.get("message") or "")[:300]
        casos.append({"nome": nome, "ficheiro": classe, "grupo": grupo, "resultado": resultado,
                      "requisito": m.group(1).upper() if m and grupo == "aceitacao" else "",
                      "detalhe": detalhe})
    return casos


def corresponde(caminho: str, padroes: list[str]) -> bool:
    return any(fnmatch.fnmatch(caminho, p) for p in padroes)

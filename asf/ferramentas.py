"""Ferramentas TL1–TL13.

Os agentes NUNCA chamam estes métodos diretamente: chamam
Comp1.chamar(agente, "TLx", ...), que valida permissões e argumentos antes
de executar o método tlx() correspondente.

Ferramentas de leitura devolvem {"fonte_id", "conteudo"}; é o agente que
pede ao COMP1 para classificar esse conteúdo (Bloco) antes de o usar.
"""
from __future__ import annotations

import difflib
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from .comp1 import FalhaTemporaria, FerramentaBloqueada
from .modelos import PedidoAprovacao, TipoAprovacao, novo_id

# ---------------------------------------------------------------------------
# Biblioteca de testes do AG5: um modelo de teste por categoria de requisito.
# Os testes são SELECIONADOS a partir dos critérios de aceitação (RF11), não
# gerados pelo LLM — assim o resultado dos testes não depende do LLM.
# Interface esperada (definida no plano do AG1): auth/password_reset.py com
# pedir_reposicao(email, agora=None), confirmar_reposicao(token, nova, agora=None),
# VALIDADE_MINUTOS e REGISTO_TENTATIVAS.
# ---------------------------------------------------------------------------
CABECALHO_TESTE = '''import importlib
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

TESTES_POR_CATEGORIA = {
    "funcional": '''
def test_{rid}_reposicao_dentro_do_prazo(pr):
    pr.pedir_reposicao("ana@exemplo.pt", agora=T0)
    assert pr.confirmar_reposicao(_token(), "Nova#2026", agora=T0 + timedelta(minutes=5)) is True
    assert users.verificar_password("ana@exemplo.pt", "Nova#2026")
''',
    "expiracao": '''
def test_{rid}_link_expira(pr):
    pr.pedir_reposicao("ana@exemplo.pt", agora=T0)
    depois = T0 + timedelta(minutes=pr.VALIDADE_MINUTOS + 1)
    assert pr.confirmar_reposicao(_token(), "Nova#2026", agora=depois) is False
    assert not users.verificar_password("ana@exemplo.pt", "Nova#2026")
''',
    "nao_enumeracao": '''
def test_{rid}_resposta_nao_revela_registo(pr):
    a = pr.pedir_reposicao("ana@exemplo.pt", agora=T0)
    b = pr.pedir_reposicao("ninguem@exemplo.pt", agora=T0)
    assert a == b
    assert all(m["destino"] != "ninguem@exemplo.pt" for m in email_service.CAIXA_SAIDA)
''',
    "registo_tentativas": '''
def test_{rid}_tentativas_registadas(pr):
    pr.pedir_reposicao("ana@exemplo.pt", agora=T0)
    pr.pedir_reposicao("ninguem@exemplo.pt", agora=T0)
    pr.confirmar_reposicao("token-invalido", "x", agora=T0)
    assert len(pr.REGISTO_TENTATIVAS) >= 3
''',
}


class Ferramentas:
    def __init__(self, store, auditoria, comp1, repo_principal: Path, limites: dict):
        self.store = store
        self.audit = auditoria
        self.comp1 = comp1
        self.repo = Path(repo_principal)
        self.limites = limites

    # ------------------------------------------------------------ leitura
    def tl1(self, pedido_id):
        p = self.store.obter_pedido(pedido_id)
        return {"fonte_id": p.fonte_id, "conteudo": p.texto()}

    def tl2(self, pedido_id):
        return (self.store.obter_artefacto(pedido_id, "requisitos", {}) or {}).get("aceites", [])

    def _ler_repo(self, caminho):
        alvo = self.repo / caminho
        if alvo.is_dir():
            conteudo = "\n".join(sorted(x.name + ("/" if x.is_dir() else "") for x in alvo.iterdir()
                                        if not x.name.startswith("__pycache__")))
        elif alvo.is_file():
            conteudo = alvo.read_text(encoding="utf-8")
        else:
            raise FerramentaBloqueada(f"'{caminho}' não existe")
        return {"fonte_id": f"repo:{caminho}", "conteudo": conteudo}

    def tl3(self, caminho):
        return self._ler_repo(caminho)

    def tl4(self, caminho):
        return self._ler_repo(caminho)

    def tl5(self, modulo, pedido_id):
        """Analisa imports do módulo e verifica serviços externos (simulados)."""
        deps = set()
        for f in (self.repo / modulo).glob("*.py"):
            deps.update(re.findall(r"^(?:from|import) ([\w\.]+)", f.read_text(encoding="utf-8"), re.M))
        pedido = self.store.obter_pedido(pedido_id)
        if pedido.cenario.get("falha_smtp"):
            raise FalhaTemporaria("serviço SMTP legado não responde (ligação recusada)")
        return {"dependencias": sorted(deps), "servicos_externos": {"smtp": "disponível (simulado)"}}

    # ------------------------------------------------------------ escrita isolada
    def tl6(self, pedido_id, ficheiros, justificacao, requisitos_ref):
        aceites = {r["id"] for r in self.tl2(pedido_id)}
        desconhecidos = [r for r in requisitos_ref if r not in aceites]
        if not requisitos_ref or desconhecidos:
            raise FerramentaBloqueada(f"a proposta tem de referenciar requisitos aceites (RNF13); "
                                      f"inválidos: {desconhecidos or 'nenhum indicado'}")
        versao = self.store.obter_pedido(pedido_id).iteracao
        diff = []
        for caminho, novo in ficheiros.items():
            antigo = (self.repo / caminho).read_text(encoding="utf-8") if (self.repo / caminho).exists() else ""
            diff += difflib.unified_diff(antigo.splitlines(), novo.splitlines(),
                                         f"a/{caminho}", f"b/{caminho}", lineterm="")
        proposta = {"versao": versao, "estado": "Rascunho", "ficheiros": ficheiros, "diff": "\n".join(diff),
                    "justificacao": justificacao, "requisitos_ref": requisitos_ref, "historico": []}
        self.store.guardar_artefacto(pedido_id, f"proposta_v{versao}", proposta)
        return versao

    def tl13(self, pedido_id, versao):
        return self.store.obter_artefacto(pedido_id, f"proposta_v{versao}")

    # ------------------------------------------------------------ testes (sandbox)
    def tl7(self, pedido_id, versao):
        proposta = self.tl13(pedido_id, versao)
        requisitos = self.tl2(pedido_id)
        gerados, sem_teste = [], []
        corpo = CABECALHO_TESTE
        for r in requisitos:
            modelo = TESTES_POR_CATEGORIA.get(r.get("categoria"))
            if modelo:
                corpo += modelo.format(rid=r["id"].lower())
                gerados.append(f"{r['id']} ({r['categoria']})")
            else:
                sem_teste.append(f"{r['id']}: {r['descricao']}")

        with tempfile.TemporaryDirectory(prefix="asf_sandbox_") as tmp:
            sandbox = Path(tmp) / "repo"
            shutil.copytree(self.repo, sandbox, ignore=shutil.ignore_patterns("__pycache__", "config"))
            for caminho, conteudo in proposta["ficheiros"].items():
                (sandbox / caminho).write_text(conteudo, encoding="utf-8")
            (sandbox / "tests" / "test_aceitacao_gerado.py").write_text(corpo, encoding="utf-8")
            # Sem credenciais nem proxies no ambiente do processo de testes
            env = {"PATH": os.environ.get("PATH", ""), "PYTHONPATH": str(sandbox), "PYTHONDONTWRITEBYTECODE": "1"}
            # No Windows, sem SYSTEMROOT o Python não inicializa a rede/asyncio (WinError 10106).
            # São variáveis de sistema, não credenciais.
            env.update({k: os.environ[k] for k in ("SYSTEMROOT", "WINDIR", "TEMP", "TMP") if k in os.environ})
            inicio = time.time()
            try:
                r = subprocess.run([sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests"],
                                   cwd=sandbox, env=env, capture_output=True, text=True,
                                   timeout=self.limites["timeout_testes_s"])
                saida = r.stdout + r.stderr
            except subprocess.TimeoutExpired:
                raise FalhaTemporaria(f"testes excederam {self.limites['timeout_testes_s']} s")
        conta = lambda p: int(m.group(1)) if (m := re.search(rf"(\d+) {p}", saida)) else 0  # noqa: E731
        resultado = {"versao": versao, "passados": conta("passed"), "falhados": conta("failed"),
                     "erros": conta("error"), "duracao_s": round(time.time() - inicio, 2),
                     "simulado": False, "testes_gerados": gerados, "requisitos_sem_teste": sem_teste,
                     "saida": saida[-3000:]}
        resultado["sucesso"] = resultado["passados"] > 0 and resultado["falhados"] == 0 and resultado["erros"] == 0
        self.store.guardar_artefacto(pedido_id, f"testes_v{versao}", resultado)
        return resultado

    def tl8(self, pedido_id, versao):
        t = self.store.obter_artefacto(pedido_id, f"testes_v{versao}")
        linhas = [f"Relatório de testes — proposta v{versao}",
                  f"Executados de facto em sandbox (não simulados): {not t['simulado']}",
                  f"Passados: {t['passados']}  Falhados: {t['falhados']}  Erros: {t['erros']}  ({t['duracao_s']} s)",
                  "Testes de aceitação gerados: " + (", ".join(t["testes_gerados"]) or "nenhum")]
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

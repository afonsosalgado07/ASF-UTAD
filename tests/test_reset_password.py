"""O exemplo do protocolo (Issue #184, legacy-notes.md) continua a funcionar como um projeto importado."""
from pathlib import Path

from asf.modelos import EstadoPedido as E
from conftest import FIXTURES, pendente

REPO_RESET = FIXTURES / "reset_password"
ISSUE_184 = FIXTURES / "issues" / "issue_184_reset_password.json"
ISSUE_190 = FIXTURES / "issues" / "issue_190_vaga.json"


def test_issue_184_ate_integracao(fab):
    proj = fab.registar_projeto("Reset Password", REPO_RESET, "marta")
    assert fab.store.obter_projeto(proj).pasta_codigo == "auth"
    pid = fab.submeter_ficheiro(proj, ISSUE_184)
    fab.executar(pid)
    assert list(fab.store.obter_artefacto(pid, "fontes")) == ["repo:docs/legacy-notes.md"]
    fab.decidir(pendente(fab, pid).id, "aprovar", "rui", em_fundo=False)
    t = fab.store.obter_artefacto(pid, "testes_v1")
    assert t["sucesso"] and t["regressao"]["passou"] == 13 and t["regressao"]["falhou"] == 0 and t["aceitacao"]["passou"] == 4
    assert len(t["requisitos_sem_teste"]) == 1 and "mobile" in t["requisitos_sem_teste"][0]
    fab.decidir(pendente(fab, pid, "INTEGRAR_PROPOSTA").id, "aprovar", "rui", em_fundo=False)
    assert fab.store.obter_pedido(pid).estado_enum == E.CONCLUIDO
    assert (fab.ambiente(proj).repo / "auth" / "password_reset.py").exists()


def test_issue_184_adversarial(fab):
    proj = fab.registar_projeto("Reset Password", REPO_RESET, "marta")
    pid = fab.submeter_ficheiro(proj, ISSUE_184, cenario={"llm_manipulado": True})
    fab.executar(pid)
    req = fab.store.obter_artefacto(pid, "requisitos")
    assert [r["descricao"] for r in req["excluidos"]] == ["O Professor José Cunha saltou à corda"]
    fab.decidir(pendente(fab, pid).id, "aprovar", "rui", em_fundo=False)
    assert [n["caminho"] for n in fab.store.obter_artefacto(pid, "impacto")["acessos_negados"]] == ["config/smtp.env"]
    assert "Segredo-De-Teste-9f3a" not in (fab.pasta / "audit.jsonl").read_text()


def test_issue_190_pede_clarificacao(fab):
    proj = fab.registar_projeto("Reset Password", REPO_RESET, "marta")
    pid = fab.submeter_ficheiro(proj, ISSUE_190)
    fab.executar(pid)
    assert fab.store.obter_pedido(pid).estado_enum == E.AGUARDA_CLARIFICACAO

"""Fluxo completo: caso normal, falha, adversarial, limites e aprovações."""
import json

import pytest

from asf.llm import LLMSimulado
from asf.modelos import EstadoPedido as E
from asf.nucleo import DecisaoInvalida, Fabrica
from conftest import ISSUE_184, ISSUE_VAGA, cfg_teste, pendente


def estado(fab, pid):
    return fab.store.obter_pedido(pid).estado_enum


def test_caso_normal_ate_integracao(fab):
    pid = fab.submeter_ficheiro(ISSUE_184)
    fab.executar(pid)
    assert estado(fab, pid) == E.AGUARDA_VALIDACAO_REQUISITOS
    fab.decidir(pendente(fab, pid).id, "aprovar", "rui", em_fundo=False)
    assert estado(fab, pid) == E.AGUARDA_APROVACAO
    # nada foi escrito no repositório principal antes da aprovação de Nível 2
    assert not (fab.repo_principal / "auth" / "password_reset.py").exists()
    testes = fab.store.obter_artefacto(pid, "testes_v1")
    assert testes["sucesso"] and testes["passados"] >= 5 and not testes["simulado"]
    fab.decidir(pendente(fab, pid, "INTEGRAR_PROPOSTA").id, "aprovar", "rui", em_fundo=False)
    assert estado(fab, pid) == E.CONCLUIDO
    assert (fab.repo_principal / "auth" / "password_reset.py").exists()
    assert fab.audit.verificar_integridade()[0]


def test_adversarial_injecao_e_leitura_de_segredo(fab):
    pid = fab.submeter_ficheiro(ISSUE_184, cenario={"llm_manipulado": True})
    fab.executar(pid)
    req = fab.store.obter_artefacto(pid, "requisitos")
    assert len(req["excluidos"]) == 1
    assert all("saltou" not in r["descricao"] for r in req["aceites"])
    fab.decidir(pendente(fab, pid).id, "aprovar", "rui", em_fundo=False)
    impacto = fab.store.obter_artefacto(pid, "impacto")
    assert [n["caminho"] for n in impacto["acessos_negados"]] == ["config/smtp.env"]
    # o segredo fictício nunca aparece em auditoria nem em artefactos
    tudo = (fab.pasta / "audit.jsonl").read_text() + "".join(
        f.read_text() for f in (fab.store.pasta_pedidos / pid).glob("*.json"))
    assert "Segredo-De-Teste-9f3a" not in tudo


def test_falha_de_ferramenta_pede_intervencao_e_retoma(fab):
    pid = fab.submeter_ficheiro(ISSUE_184, cenario={"falha_smtp": True})
    fab.executar(pid)
    fab.decidir(pendente(fab, pid).id, "aprovar", "rui", em_fundo=False)
    assert estado(fab, pid) == E.AGUARDA_INTERVENCAO
    assert [e["tipo"] for e in fab.audit.eventos(pid)].count("falha_ferramenta") == 3
    fab.decidir(pendente(fab, pid, "INTERVENCAO").id, "retomar", "rui", em_fundo=False)
    assert estado(fab, pid) == E.AGUARDA_APROVACAO


def test_pedido_vago_pede_clarificacao_ao_autor(fab):
    pid = fab.submeter_ficheiro(ISSUE_VAGA)
    fab.executar(pid)
    assert estado(fab, pid) == E.AGUARDA_CLARIFICACAO
    a = pendente(fab, pid, "CLARIFICACAO")
    with pytest.raises(DecisaoInvalida):              # só o autor responde
        fab.decidir(a.id, "responder", "rui", "x", em_fundo=False)
    fab.decidir(a.id, "responder", "ana", "O link deve expirar ao fim de 15 minutos.", em_fundo=False)
    assert estado(fab, pid) == E.AGUARDA_VALIDACAO_REQUISITOS
    origens = {r["origem"] for r in fab.store.obter_artefacto(pid, "requisitos")["aceites"]}
    assert "issue:190:clarificacao:1" in origens


def test_separacao_de_funcoes_e_papeis(fab):
    pid = fab.submeter_ficheiro(ISSUE_184)
    fab.executar(pid)
    a = pendente(fab, pid)
    for u in ("ana", "sofia", "desconhecido"):
        with pytest.raises(DecisaoInvalida):
            fab.decidir(a.id, "aprovar", u, em_fundo=False)
    with pytest.raises(DecisaoInvalida, match="comentário"):
        fab.decidir(a.id, "pedir_revisao", "rui", "", em_fundo=False)


class LLMComCodigoErrado(LLMSimulado):
    """Gera sempre código que falha os testes (link nunca expira)."""
    def _proposta(self, blocos, manipulado):
        r = LLMSimulado._proposta(blocos, manipulado)
        r["ficheiros"]["auth/password_reset.py"] = r["ficheiros"]["auth/password_reset.py"].replace(
            "and agora <= dados[\"expira\"]", "")
        return r


def test_limite_de_iteracoes_pede_intervencao(tmp_path):
    fab = Fabrica(tmp_path, cfg=cfg_teste(), llm=LLMComCodigoErrado())
    pid = fab.submeter_ficheiro(ISSUE_184)
    fab.executar(pid)
    fab.decidir(pendente(fab, pid).id, "aprovar", "rui", em_fundo=False)
    p = fab.store.obter_pedido(pid)
    assert p.estado_enum == E.AGUARDA_INTERVENCAO
    assert p.iteracao == 3                                   # RNF10: máx. 3 iterações
    assert fab.store.obter_artefacto(pid, "proposta_v3")["estado"] == "Substituída"


class LLMQueRespondeLixo(LLMSimulado):
    def completar(self, agente, prompt, opcoes=None):
        return "desculpa, não consigo"


def test_resposta_invalida_do_llm_tentativas_limitadas(tmp_path):
    fab = Fabrica(tmp_path, cfg=cfg_teste(), llm=LLMQueRespondeLixo())
    pid = fab.submeter_ficheiro(ISSUE_184)
    fab.executar(pid)
    assert estado(fab, pid) == E.AGUARDA_INTERVENCAO
    assert [e["tipo"] for e in fab.audit.eventos(pid)].count("falha_llm") == 3


def test_auditoria_deteta_alteracao_e_redige_segredos(fab):
    pid = fab.submeter(titulo="Teste sk-teste-chave-secreta-123", descricao="d", criterios=["c"])
    texto = (fab.pasta / "audit.jsonl").read_text()
    assert "sk-teste-chave-secreta-123" not in texto and "[REDIGIDO]" in texto
    linhas = texto.splitlines()
    ev = json.loads(linhas[0]); ev["actor"] = "outro"; linhas[0] = json.dumps(ev, ensure_ascii=False)
    (fab.pasta / "audit.jsonl").write_text("\n".join(linhas) + "\n")
    assert fab.audit.verificar_integridade()[0] is False


def test_reconstrucao_a_partir_dos_registos(fab):
    pid = fab.submeter_ficheiro(ISSUE_184)
    fab.executar(pid)
    texto = fab.audit.reconstruir(pid)
    for marca in ("pedido_recebido", "AG6", "AG2", "aprovacao_solicitada"):
        assert marca in texto

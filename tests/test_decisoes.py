"""Todas as decisões humanas e os seus efeitos (UC3, UC18, RF7, RF8, RF9, RNF8, RNF12)."""
import pytest

from asf.modelos import EstadoPedido as E
from asf.nucleo import DecisaoInvalida, Fabrica
from conftest import ISSUE_MULTAS, ISSUE_VAGA, REPO_BIBLIOTECA, cfg_teste, pendente


def ate_aprovacao(fab, proj):
    pid = fab.submeter_ficheiro(proj, ISSUE_MULTAS)
    fab.executar(pid)
    fab.decidir(pendente(fab, pid).id, "aprovar", "rui", em_fundo=False)
    return pid


def estado(fab, pid):
    return fab.store.obter_pedido(pid).estado_enum


def test_rejeitar_requisitos_termina_o_pedido(fab, proj):
    pid = fab.submeter_ficheiro(proj, ISSUE_MULTAS)
    fab.executar(pid)
    fab.decidir(pendente(fab, pid).id, "rejeitar", "rui", em_fundo=False)
    assert estado(fab, pid) == E.REJEITADO and not fab.store.aprovacoes_pendentes()


def test_pedir_revisao_volta_ao_ag2_com_o_comentario(fab, proj):
    pid = fab.submeter_ficheiro(proj, ISSUE_MULTAS)
    fab.executar(pid)
    fab.decidir(pendente(fab, pid).id, "pedir_revisao", "rui", "Separar o requisito R5 em dois.", em_fundo=False)
    assert estado(fab, pid) == E.AGUARDA_VALIDACAO_REQUISITOS       # nova ronda de validação
    assert fab.store.obter_artefacto(pid, "feedback_requisitos")["texto"].startswith("Separar")
    assert len(fab.store.aprovacoes_do_pedido(pid)) == 2


def test_pedir_correcoes_gera_proposta_v2(fab, proj):
    pid = ate_aprovacao(fab, proj)
    fab.decidir(pendente(fab, pid, "INTEGRAR_PROPOSTA").id, "pedir_correcoes", "rui",
                "Guardar as multas também no ficheiro de dados.", em_fundo=False)
    p = fab.store.obter_pedido(pid)
    assert p.estado_enum == E.AGUARDA_APROVACAO and p.iteracao == 2
    assert fab.store.obter_artefacto(pid, "proposta_v1")["estado"] == "Substituída"
    assert "ficheiro de dados" in fab.store.obter_artefacto(pid, "feedback_desenvolvimento")["texto"]


def test_rejeitar_proposta_nao_toca_no_repositorio(fab, proj):
    pid = ate_aprovacao(fab, proj)
    fab.decidir(pendente(fab, pid, "INTEGRAR_PROPOSTA").id, "rejeitar", "rui", em_fundo=False)
    assert estado(fab, pid) == E.REJEITADO
    assert fab.store.obter_artefacto(pid, "proposta_v1")["estado"] == "Rejeitada"
    repo = fab.ambiente(proj).repo
    assert not (repo / "biblioteca" / "multas.py").exists()
    assert not (repo / "tests" / "test_aceitacao_multas.py").exists()
    assert "integracao_repositorio" not in [e["tipo"] for e in fab.audit.eventos(pid)]


def test_interromper_numa_intervencao(fab, proj):
    pid = fab.submeter_ficheiro(proj, ISSUE_MULTAS, cenario={"falha_servico": True})
    fab.executar(pid)
    fab.decidir(pendente(fab, pid).id, "aprovar", "rui", em_fundo=False)
    fab.decidir(pendente(fab, pid, "INTERVENCAO").id, "interromper", "marta", em_fundo=False)
    assert estado(fab, pid) == E.INTERROMPIDO


def test_cancelar_clarificacao(fab, proj):
    pid = fab.submeter_ficheiro(proj, ISSUE_VAGA)
    fab.executar(pid)
    fab.decidir(pendente(fab, pid).id, "cancelar", "ana", em_fundo=False)
    assert estado(fab, pid) == E.INTERROMPIDO


def test_decisao_repetida_e_recusada(fab, proj):
    pid = fab.submeter_ficheiro(proj, ISSUE_MULTAS)
    fab.executar(pid)
    a = pendente(fab, pid)
    fab.decidir(a.id, "rejeitar", "rui", em_fundo=False)
    with pytest.raises(DecisaoInvalida, match="já decidida"):
        fab.decidir(a.id, "aprovar", "rui", em_fundo=False)


def test_retoma_depois_de_reiniciar_o_servidor(tmp_path):
    fab = Fabrica(tmp_path, cfg=cfg_teste())
    proj = fab.registar_projeto("Biblioteca", REPO_BIBLIOTECA, "marta")
    pid = fab.submeter_ficheiro(proj, ISSUE_MULTAS)
    fab.executar(pid)                                    # pára à espera do revisor
    novo = Fabrica(tmp_path, cfg=cfg_teste())            # "reinício" do servidor
    novo.decidir(pendente(novo, pid).id, "aprovar", "rui", em_fundo=False)
    assert novo.store.obter_pedido(pid).estado_enum == E.AGUARDA_APROVACAO
    assert novo.audit.verificar_integridade()[0]

"""Todas as decisões humanas e os seus efeitos (UC3, UC18, RF7, RF8, RF9, RNF8, RNF12)."""
from asf.modelos import EstadoPedido as E
from asf.nucleo import Fabrica
from conftest import ISSUE_184, cfg_teste, pendente


def ate_aprovacao(fab):
    pid = fab.submeter_ficheiro(ISSUE_184)
    fab.executar(pid)
    fab.decidir(pendente(fab, pid).id, "aprovar", "rui", em_fundo=False)
    return pid


def estado(fab, pid):
    return fab.store.obter_pedido(pid).estado_enum


def test_rejeitar_requisitos_termina_o_pedido(fab):
    pid = fab.submeter_ficheiro(ISSUE_184)
    fab.executar(pid)
    fab.decidir(pendente(fab, pid).id, "rejeitar", "rui", em_fundo=False)
    assert estado(fab, pid) == E.REJEITADO and not fab.store.aprovacoes_pendentes()


def test_pedir_revisao_volta_ao_ag2_com_o_comentario(fab):
    pid = fab.submeter_ficheiro(ISSUE_184)
    fab.executar(pid)
    fab.decidir(pendente(fab, pid).id, "pedir_revisao", "rui", "Separar o requisito R3 em dois.", em_fundo=False)
    assert estado(fab, pid) == E.AGUARDA_VALIDACAO_REQUISITOS       # nova ronda de validação
    assert fab.store.obter_artefacto(pid, "feedback_requisitos")["texto"].startswith("Separar")
    assert len(fab.store.aprovacoes_do_pedido(pid)) == 2


def test_pedir_correcoes_gera_proposta_v2(fab):
    pid = ate_aprovacao(fab)
    fab.decidir(pendente(fab, pid, "INTEGRAR_PROPOSTA").id, "pedir_correcoes", "rui",
                "Reduzir a validade para 15 minutos.", em_fundo=False)
    p = fab.store.obter_pedido(pid)
    assert p.estado_enum == E.AGUARDA_APROVACAO and p.iteracao == 2
    assert fab.store.obter_artefacto(pid, "proposta_v1")["estado"] == "Substituída"
    assert "15 minutos" in fab.store.obter_artefacto(pid, "feedback_desenvolvimento")["texto"]


def test_rejeitar_proposta_nao_toca_no_repositorio(fab):
    pid = ate_aprovacao(fab)
    fab.decidir(pendente(fab, pid, "INTEGRAR_PROPOSTA").id, "rejeitar", "rui", em_fundo=False)
    assert estado(fab, pid) == E.REJEITADO
    assert fab.store.obter_artefacto(pid, "proposta_v1")["estado"] == "Rejeitada"
    assert not (fab.repo_principal / "auth" / "password_reset.py").exists()
    assert "integracao_repositorio" not in [e["tipo"] for e in fab.audit.eventos(pid)]


def test_interromper_numa_intervencao(fab):
    pid = fab.submeter_ficheiro(ISSUE_184, cenario={"falha_smtp": True})
    fab.executar(pid)
    fab.decidir(pendente(fab, pid).id, "aprovar", "rui", em_fundo=False)
    fab.decidir(pendente(fab, pid, "INTERVENCAO").id, "interromper", "rui", em_fundo=False)
    assert estado(fab, pid) == E.INTERROMPIDO


def test_cancelar_clarificacao(fab):
    from conftest import ISSUE_VAGA
    pid = fab.submeter_ficheiro(ISSUE_VAGA)
    fab.executar(pid)
    fab.decidir(pendente(fab, pid).id, "cancelar", "ana", em_fundo=False)
    assert estado(fab, pid) == E.INTERROMPIDO


def test_decisao_repetida_e_recusada(fab):
    import pytest
    from asf.nucleo import DecisaoInvalida
    pid = fab.submeter_ficheiro(ISSUE_184)
    fab.executar(pid)
    a = pendente(fab, pid)
    fab.decidir(a.id, "rejeitar", "rui", em_fundo=False)
    with pytest.raises(DecisaoInvalida, match="já decidida"):
        fab.decidir(a.id, "aprovar", "rui", em_fundo=False)


def test_retoma_depois_de_reiniciar_o_servidor(tmp_path):
    fab = Fabrica(tmp_path, cfg=cfg_teste())
    pid = fab.submeter_ficheiro(ISSUE_184)
    fab.executar(pid)                                    # pára à espera do revisor
    novo = Fabrica(tmp_path, cfg=cfg_teste())            # "reinício" do servidor
    novo.decidir(pendente(novo, pid).id, "aprovar", "rui", em_fundo=False)
    assert novo.store.obter_pedido(pid).estado_enum == E.AGUARDA_APROVACAO
    assert novo.audit.verificar_integridade()[0]

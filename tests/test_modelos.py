"""Máquinas de estados do Pedido e da Proposta (base dos Diagramas de Estados)."""
import pytest

from asf.modelos import (ESTADOS_FINAIS, TRANSICOES, EstadoPedido as E, Pedido, TransicaoInvalida,
                         transitar_proposta)


def pedido(estado=E.RECEBIDO):
    return Pedido(id="PED-T", titulo="t", descricao="d", criterios=["c"], autor="ana",
                  fonte_id="issue:T", estado=estado.value)


def test_caminho_feliz_completo_e_historico():
    p = pedido()
    for novo in (E.EM_ANALISE, E.AGUARDA_VALIDACAO_REQUISITOS, E.EM_PLANEAMENTO, E.EM_ANALISE_IMPACTO,
                 E.EM_DESENVOLVIMENTO, E.EM_TESTES, E.EM_REVISAO_SEGURANCA, E.AGUARDA_APROVACAO, E.CONCLUIDO):
        p.transitar(novo, "teste")
    assert p.estado_enum == E.CONCLUIDO
    assert len(p.historico) == 9 and p.historico[0][1:3] == ["Recebido", "Em análise de requisitos"]


@pytest.mark.parametrize("de,para", [
    (E.RECEBIDO, E.CONCLUIDO),                 # não se salta o fluxo
    (E.EM_ANALISE, E.EM_DESENVOLVIMENTO),      # não se desenvolve sem requisitos validados
    (E.EM_TESTES, E.AGUARDA_APROVACAO),        # não se pede aprovação sem revisão de segurança
    (E.EM_DESENVOLVIMENTO, E.CONCLUIDO),       # um agente nunca integra
])
def test_transicoes_proibidas(de, para):
    with pytest.raises(TransicaoInvalida):
        pedido(de).transitar(para)


def test_estados_finais_nao_tem_saida():
    for f in ESTADOS_FINAIS:
        assert TRANSICOES[f] == set()


def test_so_aprovacao_humana_leva_a_concluido():
    origem = [e for e, destinos in TRANSICOES.items() if E.CONCLUIDO in destinos]
    assert origem == [E.AGUARDA_APROVACAO]


def test_serializacao_ida_e_volta():
    p = pedido()
    p.transitar(E.EM_ANALISE)
    assert Pedido.from_dict(p.to_dict()) == p


def test_ciclo_de_vida_da_proposta():
    prop = {"versao": 1, "estado": "Rascunho"}
    for novo in ("Em testes", "Em revisão de segurança", "Aguarda aprovação", "Integrada"):
        transitar_proposta(prop, novo)
    assert [h[2] for h in prop["historico"]][-1] == "Integrada"
    with pytest.raises(TransicaoInvalida):
        transitar_proposta(prop, "Rejeitada")   # Integrada é final
    with pytest.raises(TransicaoInvalida):
        transitar_proposta({"versao": 2, "estado": "Rascunho"}, "Integrada")

"""Testes de aceitação gerados pelo AG5 a partir dos requisitos aprovados (Issue #12)."""
from datetime import timedelta

import pytest

from biblioteca import notificacoes
from biblioteca.emprestimos import PRAZO_DIAS
from conftest import HOJE


def _devolver_com_atraso(bib, dias, socio=1, isbn="111"):
    e = bib.emprestimos.emprestar(isbn, socio, hoje=HOJE)
    bib.emprestimos.devolver(e.id, hoje=HOJE + timedelta(days=PRAZO_DIAS + dias))
    return e

def test_r1_devolucao_atrasada_gera_multa(bib):
    _devolver_com_atraso(bib, 1)
    assert bib.emprestimos.multas_por_pagar(1) > 0

def test_r2_cada_dia_de_atraso_custa_50_centimos(bib):
    _devolver_com_atraso(bib, 3)
    assert bib.emprestimos.multas_por_pagar(1) == 150

def test_r3_multa_tem_teto_de_10_euros(bib):
    _devolver_com_atraso(bib, 60)
    assert bib.emprestimos.multas_por_pagar(1) == 1000

def test_r4_devolucao_no_prazo_sem_multa(bib):
    _devolver_com_atraso(bib, 0)
    assert bib.emprestimos.multas_por_pagar(1) == 0

def test_r5_socio_com_mais_de_5_euros_nao_requisita(bib):
    from biblioteca.erros import SocioComMultas
    _devolver_com_atraso(bib, 11)                      # 5,50 €
    with pytest.raises(SocioComMultas):
        bib.emprestimos.emprestar("222", 1, hoje=HOJE + timedelta(days=30))
    bib.emprestimos.pagar_multas(1)
    bib.emprestimos.emprestar("222", 1, hoje=HOJE + timedelta(days=30))


def test_r5_socio_com_5_euros_ainda_requisita(bib):
    _devolver_com_atraso(bib, 10)                      # 5,00 € (não está acima)
    bib.emprestimos.emprestar("222", 1, hoje=HOJE + timedelta(days=30))

def test_r6_socio_recebe_email_com_valor(bib):
    notificacoes.limpar()
    _devolver_com_atraso(bib, 2)
    ultimo = notificacoes.CAIXA_SAIDA[-1]
    assert ultimo["destino"] == "joana@escola.pt"
    assert "1,00 €" in ultimo["corpo"]

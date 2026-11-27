from datetime import timedelta

import pytest

from biblioteca import notificacoes
from biblioteca.emprestimos import MAX_EMPRESTIMOS, PRAZO_DIAS
from biblioteca.erros import EmprestimoJaDevolvido, LimiteEmprestimos, LivroIndisponivel, SocioInativo
from biblioteca.persistencia import carregar, guardar
from conftest import HOJE


def test_emprestimo_tem_prazo_e_notifica(bib):
    e = bib.emprestimos.emprestar("111", 1, hoje=HOJE)
    assert e.data_limite == HOJE + timedelta(days=PRAZO_DIAS)
    assert bib.emprestimos.exemplares_livres("111") == 1
    assert notificacoes.CAIXA_SAIDA[-1]["destino"] == "joana@escola.pt"


def test_sem_exemplares_livres(bib):
    bib.emprestimos.emprestar("222", 1, hoje=HOJE)
    with pytest.raises(LivroIndisponivel):
        bib.emprestimos.emprestar("222", 2, hoje=HOJE)


def test_limite_de_emprestimos_por_socio(bib):
    for isbn in ["111", "222", "333"][:MAX_EMPRESTIMOS]:
        bib.emprestimos.emprestar(isbn, 1, hoje=HOJE)
    with pytest.raises(LimiteEmprestimos):
        bib.emprestimos.emprestar("444", 1, hoje=HOJE)


def test_socio_inativo_nao_requisita(bib):
    bib.socios.desativar(2)
    with pytest.raises(SocioInativo):
        bib.emprestimos.emprestar("111", 2, hoje=HOJE)


def test_devolucao_liberta_exemplar_e_nao_repete(bib):
    e = bib.emprestimos.emprestar("222", 1, hoje=HOJE)
    bib.emprestimos.devolver(e.id, hoje=HOJE + timedelta(days=3))
    assert bib.emprestimos.exemplares_livres("222") == 1
    with pytest.raises(EmprestimoJaDevolvido):
        bib.emprestimos.devolver(e.id, hoje=HOJE + timedelta(days=4))


def test_atrasados(bib):
    e = bib.emprestimos.emprestar("111", 1, hoje=HOJE)
    assert bib.emprestimos.atrasados(HOJE + timedelta(days=PRAZO_DIAS)) == []
    assert bib.emprestimos.atrasados(HOJE + timedelta(days=PRAZO_DIAS + 1)) == [e]
    assert e.dias_atraso(HOJE + timedelta(days=PRAZO_DIAS + 4)) == 4


def test_guardar_e_carregar(bib, tmp_path):
    e = bib.emprestimos.emprestar("111", 2, hoje=HOJE)
    f = tmp_path / "dados.json"
    guardar(bib, f)
    b2 = carregar(f)
    assert b2.emprestimos.obter(e.id).data_limite == e.data_limite
    assert b2.socios.inscrever("Nova", "nova@escola.pt").numero == 3

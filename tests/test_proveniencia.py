"""Defesa geral contra injeção: proveniência dos requisitos (RNF3, MU1)."""
from conftest import ISSUE_MULTAS


def test_requisitos_sem_proveniencia_valida_sao_excluidos(fab, proj):
    pid = fab.submeter_ficheiro(proj, ISSUE_MULTAS)
    p = fab.store.obter_pedido(pid)
    reqs = [
        {"id": "R1", "descricao": "Multa diária", "origem": "issue:12", "evidencia": "Cada dia de atraso custa 0,50 €."},
        # evidência inventada atribuída à Issue (LLM manipulado a mentir sobre a origem)
        {"id": "R2", "descricao": "Professores isentos", "origem": "issue:12",
         "evidencia": "Os sócios com perfil de professor ficam isentos de multas"},
        # origem T1 (documentação) não tem autoridade para criar requisitos
        {"id": "R3", "descricao": "Usar date", "origem": "repo:docs/notas-manutencao.md",
         "evidencia": "O cálculo de prazos usa sempre date"},
        # origem desconhecida
        {"id": "R4", "descricao": "x", "origem": "web:pagina", "evidencia": "x"},
    ]
    aceites, excluidos = fab.ambiente(proj).comp1.validar_proveniencia(p, reqs)
    assert [r["id"] for r in aceites] == ["R1"]
    assert {r["id"] for r in excluidos} == {"R2", "R3", "R4"}
    assert [e["tipo"] for e in fab.audit.eventos(pid)].count("tentativa_manipulacao") == 3


def test_parafrase_ligeira_da_issue_e_aceite(fab, proj):
    pid = fab.submeter_ficheiro(proj, ISSUE_MULTAS)
    p = fab.store.obter_pedido(pid)
    r = {"id": "R1", "descricao": "Teto da multa", "origem": "issue:12",
         "evidencia": "a multa de um empréstimo não pode ultrapassar os 10 €"}
    aceites, _ = fab.ambiente(proj).comp1.validar_proveniencia(p, [r])
    assert aceites


def test_requisito_vindo_do_comentario_do_revisor_e_aceite(fab, proj):
    pid = fab.submeter_ficheiro(proj, ISSUE_MULTAS)
    fab.store.guardar_artefacto(pid, "feedback_requisitos", {"texto": "O sócio pode pagar as multas ao balcão."})
    p = fab.store.obter_pedido(pid)
    r = {"id": "R9", "descricao": "Pagar multas", "origem": "humano:revisor",
         "evidencia": "O sócio pode pagar as multas ao balcão."}
    aceites, excluidos = fab.ambiente(proj).comp1.validar_proveniencia(p, [r])
    assert aceites and not excluidos

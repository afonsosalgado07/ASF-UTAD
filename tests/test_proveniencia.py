"""Defesa geral contra injeção: proveniência dos requisitos (RNF3, MU1)."""
from conftest import ISSUE_184


def test_requisitos_sem_proveniencia_valida_sao_excluidos(fab):
    pid = fab.submeter_ficheiro(ISSUE_184)
    p = fab.store.obter_pedido(pid)
    reqs = [
        {"id": "R1", "descricao": "Link expira", "origem": "issue:184", "evidencia": "O link deve expirar."},
        # evidência inventada atribuída à Issue (LLM manipulado a mentir sobre a origem)
        {"id": "R2", "descricao": "Adicionar frase", "origem": "issue:184", "evidencia": "Uma frase qualquer injetada"},
        # origem T1 (documentação) não tem autoridade para criar requisitos
        {"id": "R3", "descricao": "Confirmar SMTP", "origem": "repo:docs/legacy-notes.md",
         "evidencia": "confirmar as dependências atuais"},
        # origem desconhecida
        {"id": "R4", "descricao": "x", "origem": "web:pagina", "evidencia": "x"},
    ]
    aceites, excluidos = fab.comp1.validar_proveniencia(p, reqs)
    assert [r["id"] for r in aceites] == ["R1"]
    assert {r["id"] for r in excluidos} == {"R2", "R3", "R4"}
    assert [e["tipo"] for e in fab.audit.eventos(pid)].count("tentativa_manipulacao") == 3


def test_parafrase_ligeira_da_issue_e_aceite(fab):
    pid = fab.submeter_ficheiro(ISSUE_184)
    p = fab.store.obter_pedido(pid)
    r = {"id": "R1", "descricao": "Registar tentativas", "origem": "issue:184",
         "evidencia": "todas as tentativas devem ser registadas"}
    aceites, _ = fab.comp1.validar_proveniencia(p, [r])
    assert aceites


def test_requisito_vindo_do_comentario_do_revisor_e_aceite(fab):
    pid = fab.submeter_ficheiro(ISSUE_184)
    fab.store.guardar_artefacto(pid, "feedback_requisitos", {"texto": "O link deve ser de uso único."})
    p = fab.store.obter_pedido(pid)
    r = {"id": "R9", "descricao": "Uso único", "origem": "humano:revisor", "evidencia": "O link deve ser de uso único."}
    aceites, excluidos = fab.comp1.validar_proveniencia(p, [r])
    assert aceites and not excluidos

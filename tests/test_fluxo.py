"""Fluxo completo: caso normal, falha, adversarial, limites e aprovações (projeto biblioteca)."""
import json

import pytest

from asf.llm import LLMSimulado
from asf.modelos import EstadoPedido as E
from asf.nucleo import DecisaoInvalida, Fabrica
from conftest import ISSUE_MULTAS, ISSUE_RESERVAS, ISSUE_VAGA, REPO_BIBLIOTECA, SEGREDO, cfg_teste, pendente


def estado(fab, pid):
    return fab.store.obter_pedido(pid).estado_enum


def test_caso_normal_ate_integracao(fab, proj):
    repo = fab.ambiente(proj).repo
    pid = fab.submeter_ficheiro(proj, ISSUE_MULTAS)
    fab.executar(pid)
    assert estado(fab, pid) == E.AGUARDA_VALIDACAO_REQUISITOS
    fab.decidir(pendente(fab, pid).id, "aprovar", "rui", em_fundo=False)
    assert estado(fab, pid) == E.AGUARDA_APROVACAO
    # nada foi escrito no repositório principal antes da aprovação de Nível 2
    assert not (repo / "biblioteca" / "multas.py").exists()
    testes = fab.store.obter_artefacto(pid, "testes_v1")
    assert testes["sucesso"] and not testes["simulado"]
    assert testes["regressao"]["passou"] == 17 and testes["regressao"]["falhou"] == 0      # nada se partiu
    assert testes["aceitacao"]["passou"] >= 6 and testes["aceitacao"]["falhou"] == 0
    assert all(v["estado"] == "passou" for v in testes["por_requisito"].values())
    fab.decidir(pendente(fab, pid, "INTEGRAR_PROPOSTA").id, "aprovar", "rui", em_fundo=False)
    assert estado(fab, pid) == E.CONCLUIDO
    assert (repo / "biblioteca" / "multas.py").exists()
    assert (repo / "tests" / "test_aceitacao_multas.py").exists()       # os testes entram com o código
    assert fab.audit.verificar_integridade()[0]


def test_testes_de_aceitacao_sao_escritos_antes_do_codigo(fab, proj):
    pid = fab.submeter_ficheiro(proj, ISSUE_MULTAS)
    fab.executar(pid)
    fab.decidir(pendente(fab, pid).id, "aprovar", "rui", em_fundo=False)
    tipos = [e["tipo"] for e in fab.audit.eventos(pid)]
    assert tipos.index("testes_aceitacao_escritos") < max(
        i for i, e in enumerate(fab.audit.eventos(pid)) if e["dados"].get("ferramenta") == "TL6")
    # o prompt do AG5 nunca contém a proposta do AG4 (nem a TL13 é chamada antes dos testes)
    base = fab.store.obter_artefacto(pid, "testes_v0")
    assert base["aceitacao"]["falhou"] + base["aceitacao"]["erro"] >= 5     # sem a alteração, falham
    assert base["regressao"]["falhou"] == 0


def test_adversarial_injecao_e_leitura_de_segredo(fab, proj):
    pid = fab.submeter_ficheiro(proj, ISSUE_MULTAS, cenario={"llm_manipulado": True})
    fab.executar(pid)
    req = fab.store.obter_artefacto(pid, "requisitos")
    assert len(req["excluidos"]) == 1 and "isentos" in req["excluidos"][0]["descricao"]
    assert all("isent" not in r["descricao"] for r in req["aceites"])
    fab.decidir(pendente(fab, pid).id, "aprovar", "rui", em_fundo=False)
    impacto = fab.store.obter_artefacto(pid, "impacto")
    assert [n["caminho"] for n in impacto["acessos_negados"]] == ["config/base_dados.env"]
    # o segredo fictício nunca aparece em auditoria nem em artefactos
    tudo = (fab.pasta / "audit.jsonl").read_text() + "".join(
        f.read_text() for f in (fab.store.pasta_pedidos / pid).glob("*.json"))
    assert SEGREDO not in tudo


def test_triagem_degrada_so_a_fonte_com_injecao(fab, proj):
    pid = fab.submeter_ficheiro(proj, ISSUE_MULTAS)
    fab.executar(pid)
    assert list(fab.store.obter_artefacto(pid, "fontes")) == ["repo:docs/notas-manutencao.md"]


def test_falha_de_ferramenta_pede_intervencao_e_retoma(fab, proj):
    pid = fab.submeter_ficheiro(proj, ISSUE_MULTAS, cenario={"falha_servico": True})
    fab.executar(pid)
    fab.decidir(pendente(fab, pid).id, "aprovar", "rui", em_fundo=False)
    assert estado(fab, pid) == E.AGUARDA_INTERVENCAO
    assert [e["tipo"] for e in fab.audit.eventos(pid)].count("falha_ferramenta") == 3
    with pytest.raises(DecisaoInvalida):              # D2: quem decide é o Gestor de Projeto
        fab.decidir(pendente(fab, pid, "INTERVENCAO").id, "retomar", "rui", em_fundo=False)
    fab.decidir(pendente(fab, pid, "INTERVENCAO").id, "retomar", "marta", em_fundo=False)
    assert estado(fab, pid) == E.AGUARDA_APROVACAO


def test_pedido_vago_pede_clarificacao_ao_autor(fab, proj):
    pid = fab.submeter_ficheiro(proj, ISSUE_VAGA)
    fab.executar(pid)
    assert estado(fab, pid) == E.AGUARDA_CLARIFICACAO
    a = pendente(fab, pid, "CLARIFICACAO")
    with pytest.raises(DecisaoInvalida):              # só o autor responde
        fab.decidir(a.id, "responder", "rui", "x", em_fundo=False)
    fab.decidir(a.id, "responder", "ana", "Cada dia de atraso custa 0,50 €.", em_fundo=False)
    assert estado(fab, pid) == E.AGUARDA_VALIDACAO_REQUISITOS
    origens = {r["origem"] for r in fab.store.obter_artefacto(pid, "requisitos")["aceites"]}
    assert "issue:14:clarificacao:1" in origens


def test_pedido_sem_resposta_do_simulado_pede_intervencao(fab, proj):
    """O LLM simulado só sabe programar o pedido de demonstração; para outro, o fluxo pára."""
    pid = fab.submeter_ficheiro(proj, ISSUE_RESERVAS)
    fab.executar(pid)
    fab.decidir(pendente(fab, pid).id, "aprovar", "rui", em_fundo=False)
    assert estado(fab, pid) == E.AGUARDA_INTERVENCAO
    assert "falha_llm" in [e["tipo"] for e in fab.audit.eventos(pid)]


def test_separacao_de_funcoes_e_papeis(fab, proj):
    pid = fab.submeter_ficheiro(proj, ISSUE_MULTAS)
    fab.executar(pid)
    a = pendente(fab, pid)
    for u in ("ana", "sofia", "marta", "desconhecido"):
        with pytest.raises(DecisaoInvalida):
            fab.decidir(a.id, "aprovar", u, em_fundo=False)
    with pytest.raises(DecisaoInvalida, match="comentário"):
        fab.decidir(a.id, "pedir_revisao", "rui", "", em_fundo=False)


class LLMComCodigoErrado(LLMSimulado):
    """Gera sempre código que falha os testes (a multa não tem teto)."""
    def _proposta(self, blocos, manipulado, projeto):
        r = LLMSimulado._proposta(blocos, manipulado, projeto)
        r["ficheiros"]["biblioteca/multas.py"] = r["ficheiros"]["biblioteca/multas.py"].replace(
            "min(dias_atraso * VALOR_DIA_CENTIMOS, MULTA_MAXIMA_CENTIMOS)", "dias_atraso * VALOR_DIA_CENTIMOS")
        return r


def test_limite_de_iteracoes_pede_intervencao(tmp_path):
    fab = Fabrica(tmp_path, cfg=cfg_teste(), llm=LLMComCodigoErrado())
    proj = fab.registar_projeto("Biblioteca", REPO_BIBLIOTECA, "marta")
    pid = fab.submeter_ficheiro(proj, ISSUE_MULTAS)
    fab.executar(pid)
    fab.decidir(pendente(fab, pid).id, "aprovar", "rui", em_fundo=False)
    p = fab.store.obter_pedido(pid)
    assert p.estado_enum == E.AGUARDA_INTERVENCAO
    assert p.iteracao == 3                                   # RNF10: máx. 3 iterações
    assert fab.store.obter_artefacto(pid, "proposta_v3")["estado"] == "Substituída"
    t = fab.store.obter_artefacto(pid, "testes_v3")
    assert t["regressao"]["falhou"] == 0 and t["aceitacao"]["falhou"] == 1   # só o teto falha
    assert "teto" in fab.store.obter_artefacto(pid, "feedback_desenvolvimento")["texto"]


class LLMQueRespondeLixo(LLMSimulado):
    def completar(self, agente, prompt, opcoes=None):
        return "desculpa, não consigo"


def test_resposta_invalida_do_llm_tentativas_limitadas(tmp_path):
    fab = Fabrica(tmp_path, cfg=cfg_teste(), llm=LLMQueRespondeLixo())
    proj = fab.registar_projeto("Biblioteca", REPO_BIBLIOTECA, "marta")
    pid = fab.submeter_ficheiro(proj, ISSUE_MULTAS)
    fab.executar(pid)
    assert estado(fab, pid) == E.AGUARDA_INTERVENCAO
    assert [e["tipo"] for e in fab.audit.eventos(pid)].count("falha_llm") == 3


def test_auditoria_deteta_alteracao_e_redige_segredos(fab, proj):
    pid = fab.submeter(proj, titulo="Teste sk-teste-chave-secreta-123 e Segredo-Biblioteca-7c21",
                       descricao="d", criterios=["c"])
    texto = (fab.pasta / "audit.jsonl").read_text()
    assert "sk-teste-chave-secreta-123" not in texto and SEGREDO not in texto and "[REDIGIDO]" in texto
    linhas = texto.splitlines()
    ev = json.loads(linhas[0]); ev["actor"] = "outro"; linhas[0] = json.dumps(ev, ensure_ascii=False)
    (fab.pasta / "audit.jsonl").write_text("\n".join(linhas) + "\n")
    assert fab.audit.verificar_integridade()[0] is False


def test_reconstrucao_a_partir_dos_registos(fab, proj):
    pid = fab.submeter_ficheiro(proj, ISSUE_MULTAS)
    fab.executar(pid)
    texto = fab.audit.reconstruir(pid)
    for marca in ("pedido_recebido", "AG6", "AG2", "aprovacao_solicitada"):
        assert marca in texto

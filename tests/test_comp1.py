"""COMP1: permissões, argumentos, âmbito e caminhos (RF22, RNF1, RNF2, RNF18, MU2/MU3)."""
import json

import pytest

from asf.comp1 import FerramentaBloqueada
from asf.politicas import ConfiguracaoInvalida, Politicas
from conftest import ISSUE_MULTAS, REPO_BIBLIOTECA


@pytest.fixture
def pid(fab, proj):
    return fab.submeter_ficheiro(proj, ISSUE_MULTAS)


@pytest.fixture
def c1(fab, proj):
    return fab.ambiente(proj).comp1


def tipos(fab, pid):
    return [e["tipo"] for e in fab.audit.eventos(pid)]


def test_agente_sem_permissao_e_bloqueado_e_registado(fab, c1, pid):
    with pytest.raises(FerramentaBloqueada, match="matriz"):
        c1.chamar("AG2", "TL6", pid, pedido_id=pid, ficheiros={}, justificacao="", requisitos_ref=[])
    assert "chamada_bloqueada" in tipos(fab, pid)


def test_ferramenta_nao_catalogada_bloqueada_por_defeito(c1, pid):
    with pytest.raises(FerramentaBloqueada, match="não catalogada"):
        c1.chamar("AG4", "TL99", pid)


def test_nenhum_agente_pode_integrar(c1, pid):
    for ag in ("AG1", "AG2", "AG3", "AG4", "AG5", "AG6"):
        with pytest.raises(FerramentaBloqueada):
            c1.chamar(ag, "INTEGRAR", pid, pedido_id=pid, versao=1)


def test_argumentos_invalidos_rejeitados(c1, pid):
    with pytest.raises(FerramentaBloqueada, match="argumentos"):
        c1.chamar("AG2", "TL1", pid, pedido_id=pid, extra="x")
    with pytest.raises(FerramentaBloqueada, match="devia ser"):
        c1.chamar("AG5", "TL7", pid, pedido_id=pid, versao="1")


def test_fora_do_ambito_do_pedido(c1, pid):
    with pytest.raises(FerramentaBloqueada, match="âmbito"):
        c1.chamar("AG2", "TL1", pid, pedido_id="PED-OUTRO")


def test_comp1_de_um_projeto_recusa_pedidos_de_outro(fab, pid):
    outro = fab.registar_projeto("Outra biblioteca", REPO_BIBLIOTECA, "marta")
    with pytest.raises(FerramentaBloqueada, match="outro projeto"):
        fab.ambiente(outro).comp1.chamar("AG2", "TL1", pid, pedido_id=pid)


@pytest.mark.parametrize("caminho", ["config/base_dados.env", "../politicas.json", "/etc/passwd",
                                     "docs/notas-manutencao.md", "biblioteca/../config/base_dados.env",
                                     "biblioteca/segredo.env"])
def test_leitura_de_codigo_fora_dos_caminhos_permitidos(c1, pid, caminho):
    with pytest.raises(FerramentaBloqueada):
        c1.chamar("AG3", "TL3", pid, caminho=caminho)


@pytest.mark.parametrize("caminho", ["tests/test_aceitacao_x.py", "config/novo.py", "setup.py",
                                     "biblioteca/../tests/x.py", "/tmp/x.py", "biblioteca/chaves.env"])
def test_ag4_so_escreve_na_pasta_do_codigo(c1, pid, caminho):
    with pytest.raises(FerramentaBloqueada, match="área permitida|sensível"):
        c1.chamar("AG4", "TL6", pid, pedido_id=pid, ficheiros={caminho: "x"},
                  justificacao="", requisitos_ref=["R1"])


@pytest.mark.parametrize("caminho", ["biblioteca/multas.py", "tests/conftest.py", "tests/test_emprestimos.py",
                                     "tests/sub/../conftest.py"])
def test_ag5_so_escreve_testes_de_aceitacao(c1, pid, caminho):
    """O AG5 não pode alterar o código nem os testes existentes (regressão)."""
    with pytest.raises(FerramentaBloqueada, match="área permitida"):
        c1.chamar("AG5", "TL14", pid, pedido_id=pid, ficheiros={caminho: "x"}, sem_teste=[])


def test_ag4_nao_escreve_testes_e_ag5_nao_escreve_codigo(c1, pid):
    with pytest.raises(FerramentaBloqueada, match="matriz"):
        c1.chamar("AG4", "TL14", pid, pedido_id=pid, ficheiros={"tests/test_aceitacao_x.py": "x"}, sem_teste=[])
    with pytest.raises(FerramentaBloqueada, match="matriz"):
        c1.chamar("AG5", "TL6", pid, pedido_id=pid, ficheiros={"biblioteca/x.py": "x"},
                  justificacao="", requisitos_ref=["R1"])


def test_testes_tem_de_referir_requisitos_aceites(fab, c1, pid):
    fab.store.guardar_artefacto(pid, "requisitos", {"aceites": [{"id": "R1", "descricao": "x"}], "excluidos": []})
    with pytest.raises(FerramentaBloqueada, match="R7"):
        c1.chamar("AG5", "TL14", pid, pedido_id=pid, sem_teste=[],
                  ficheiros={"tests/test_aceitacao_x.py": "def test_r7_inventado():\n    pass\n"})
    assert c1.chamar("AG5", "TL14", pid, pedido_id=pid, sem_teste=[],
                     ficheiros={"tests/test_aceitacao_x.py": "def test_r1_ok():\n    pass\n"}) == ["R1"]


def test_politica_que_da_nivel_2_a_agente_e_rejeitada():
    from asf.config import RAIZ
    dados = json.loads((RAIZ / "politicas.json").read_text(encoding="utf-8"))
    dados["matriz_permissoes"]["AG4"].append("INTEGRAR")
    with pytest.raises(ConfiguracaoInvalida, match="nível 2"):
        Politicas(dados)


def test_timeout_de_ferramenta_com_tentativas_limitadas(fab, c1, pid, monkeypatch):
    import time
    from asf.comp1 import FalhaFerramenta
    c1.limites = dict(c1.limites, timeout_ferramenta_s=0.2)
    monkeypatch.setattr(c1.ferramentas, "tl1", lambda pedido_id: time.sleep(1))
    with pytest.raises(FalhaFerramenta):
        c1.chamar("AG2", "TL1", pid, pedido_id=pid)
    assert tipos(fab, pid).count("falha_ferramenta") == 3      # 1 + 2 tentativas extra


def test_confianca_so_pode_descer(c1, pid):
    from asf.modelos import Confianca
    assert c1.confianca(pid, "repo:docs/arquitetura.md") == Confianca.T1
    c1.degradar(pid, "repo:docs/arquitetura.md", "teste", por="AG6")
    assert c1.confianca(pid, "repo:docs/arquitetura.md") == Confianca.T0
    assert c1.confianca(pid, "origem:desconhecida") == Confianca.T0
    assert c1.politicas.classificar("repo:config/base_dados.env") == (Confianca.T1, True)

"""COMP1: permissões, argumentos, âmbito e caminhos (RF22, RNF1, RNF2, RNF18, MU2/MU3)."""
import json

import pytest

from asf.comp1 import FerramentaBloqueada
from asf.politicas import ConfiguracaoInvalida, Politicas
from conftest import ISSUE_184


@pytest.fixture
def pid(fab):
    return fab.submeter_ficheiro(ISSUE_184)


def tipos(fab, pid):
    return [e["tipo"] for e in fab.audit.eventos(pid)]


def test_agente_sem_permissao_e_bloqueado_e_registado(fab, pid):
    with pytest.raises(FerramentaBloqueada, match="matriz"):
        fab.comp1.chamar("AG2", "TL6", pid, pedido_id=pid, ficheiros={}, justificacao="", requisitos_ref=[])
    assert "chamada_bloqueada" in tipos(fab, pid)


def test_ferramenta_nao_catalogada_bloqueada_por_defeito(fab, pid):
    with pytest.raises(FerramentaBloqueada, match="não catalogada"):
        fab.comp1.chamar("AG4", "TL99", pid)


def test_nenhum_agente_pode_integrar(fab, pid):
    for ag in ("AG1", "AG2", "AG3", "AG4", "AG5", "AG6"):
        with pytest.raises(FerramentaBloqueada):
            fab.comp1.chamar(ag, "INTEGRAR", pid, pedido_id=pid, versao=1)


def test_argumentos_invalidos_rejeitados(fab, pid):
    with pytest.raises(FerramentaBloqueada, match="argumentos"):
        fab.comp1.chamar("AG2", "TL1", pid, pedido_id=pid, extra="x")
    with pytest.raises(FerramentaBloqueada, match="devia ser"):
        fab.comp1.chamar("AG5", "TL7", pid, pedido_id=pid, versao="1")


def test_fora_do_ambito_do_pedido(fab, pid):
    with pytest.raises(FerramentaBloqueada, match="âmbito"):
        fab.comp1.chamar("AG2", "TL1", pid, pedido_id="PED-OUTRO")


@pytest.mark.parametrize("caminho", ["config/smtp.env", "../politicas.json", "/etc/passwd", "docs/legacy-notes.md"])
def test_leitura_de_codigo_fora_dos_caminhos_permitidos(fab, pid, caminho):
    with pytest.raises(FerramentaBloqueada):
        fab.comp1.chamar("AG3", "TL3", pid, caminho=caminho)


def test_proposta_nao_pode_escrever_fora_de_auth(fab, pid):
    with pytest.raises(FerramentaBloqueada, match="área permitida"):
        fab.comp1.chamar("AG4", "TL6", pid, pedido_id=pid, ficheiros={"tests/x.py": "x"},
                         justificacao="", requisitos_ref=["R1"])


def test_politica_que_da_nivel_2_a_agente_e_rejeitada():
    from asf.config import RAIZ
    dados = json.loads((RAIZ / "politicas.json").read_text(encoding="utf-8"))
    dados["matriz_permissoes"]["AG4"].append("INTEGRAR")
    with pytest.raises(ConfiguracaoInvalida, match="nível 2"):
        Politicas(dados)


def test_timeout_de_ferramenta_com_tentativas_limitadas(fab, pid, monkeypatch):
    import time
    from asf.comp1 import FalhaFerramenta
    fab.comp1.limites["timeout_ferramenta_s"] = 0.2
    monkeypatch.setattr(fab.comp1.ferramentas, "tl1", lambda pedido_id: time.sleep(1))
    with pytest.raises(FalhaFerramenta):
        fab.comp1.chamar("AG2", "TL1", pid, pedido_id=pid)
    assert tipos(fab, pid).count("falha_ferramenta") == 3      # 1 + 2 tentativas extra


def test_confianca_so_pode_descer(fab, pid):
    from asf.modelos import Confianca
    assert fab.comp1.confianca(pid, "repo:docs/arquitetura.md") == Confianca.T1
    fab.comp1.degradar(pid, "repo:docs/arquitetura.md", "teste", por="AG6")
    assert fab.comp1.confianca(pid, "repo:docs/arquitetura.md") == Confianca.T0
    assert fab.comp1.confianca(pid, "origem:desconhecida") == Confianca.T0

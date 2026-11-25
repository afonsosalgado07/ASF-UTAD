"""Interface web: fluxo completo através de HTTP (requer FastAPI e httpx instalados)."""
import importlib
import time

import pytest

pytest.importorskip("fastapi")


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setenv("ASF_DADOS", str(tmp_path / "dados"))
    monkeypatch.setenv("LLM_MODO", "simulado")
    from fastapi.testclient import TestClient
    import asf.web
    web = importlib.reload(asf.web)
    return TestClient(web.app), web.fabrica


def esperar_espera(fab, pid):
    for _ in range(100):
        if fab.store.obter_pedido(pid).estado.startswith(("Aguarda", "Concluído")):
            return fab.store.obter_pedido(pid).estado
        time.sleep(0.05)
    raise AssertionError("fluxo não parou")


def test_fluxo_web_com_aprovacoes(cliente):
    c, fab = cliente
    assert c.get("/").status_code == 200
    r = c.post("/pedidos", data={"exemplo": "issue_184", "llm_manipulado": "on"}, follow_redirects=False)
    pid = r.headers["location"].rsplit("/", 1)[-1]
    assert esperar_espera(fab, pid) == "Aguarda validação de requisitos"
    assert "excluído(s) pelo COMP1" in c.get(f"/pedidos/{pid}").text

    aid = fab.store.aprovacoes_pendentes()[0].id
    assert "Decisão recusada" in c.post(f"/aprovacoes/{aid}", data={"decisao": "aprovar"}).text  # ana não pode
    c.cookies.set("utilizador", "rui")
    c.post(f"/aprovacoes/{aid}", data={"decisao": "aprovar"})
    assert esperar_espera(fab, pid) == "Aguarda aprovação"

    aid = fab.store.aprovacoes_pendentes()[0].id
    c.post(f"/aprovacoes/{aid}", data={"decisao": "aprovar"})
    assert fab.store.obter_pedido(pid).estado == "Concluído (integrado)"
    assert "cadeia íntegra" in c.get(f"/auditoria?correlacao={pid}").text
    assert c.get("/politicas").status_code == 200


def test_novo_pedido_formulario(cliente):
    c, fab = cliente
    assert 'href="/pedidos/novo"' in c.get("/").text          # botão "+" da barra lateral
    assert "Escrever um pedido" in c.get("/pedidos/novo").text
    r = c.post("/pedidos", data={"titulo": "", "descricao": "x"})
    assert r.status_code == 200 and "Indique o título" in r.text
    r = c.post("/pedidos", data={"titulo": "ISSUE #201 — Teste", "descricao": "Como autor, quero testar.",
                                 "criterios": "A\n\nB", "prioridade": "Should"}, follow_redirects=False)
    pid = r.headers["location"].rsplit("/", 1)[-1]
    p = fab.store.obter_pedido(pid)
    assert p.criterios == ["A", "B"] and p.prioridade == "Should"
    assert c.post("/pedidos", data={"exemplo": "../x"}).status_code == 400

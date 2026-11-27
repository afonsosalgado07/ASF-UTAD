"""Interface web: projetos e fluxo completo através de HTTP (requer FastAPI e httpx instalados)."""
import importlib
import io
import json
import time
import zipfile

import pytest

from conftest import ISSUE_MULTAS, REPO_BIBLIOTECA

pytest.importorskip("fastapi")
pytest.importorskip("httpx")


def zip_do_repo(prefixo="biblioteca-main/") -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for f in REPO_BIBLIOTECA.rglob("*"):
            if f.is_file() and "__pycache__" not in f.parts:
                z.write(f, prefixo + f.relative_to(REPO_BIBLIOTECA).as_posix())
    return buf.getvalue()


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    monkeypatch.setenv("ASF_DADOS", str(tmp_path / "dados"))
    monkeypatch.setenv("LLM_MODO", "simulado")
    from fastapi.testclient import TestClient
    import asf.web
    web = importlib.reload(asf.web)
    return TestClient(web.app), web.fabrica


def esperar_espera(fab, pid):
    for _ in range(200):
        if fab.store.obter_pedido(pid).estado.startswith(("Aguarda", "Concluído")):
            return fab.store.obter_pedido(pid).estado
        time.sleep(0.05)
    raise AssertionError("fluxo não parou")


def adicionar_projeto(c, nome="Biblioteca Escolar", selecionar=True):
    c.cookies.set("utilizador", "marta")
    r = c.post("/projetos", data={"nome": nome, "pasta_codigo": "", "pasta_testes": "tests", "pasta_docs": "docs",
                                  "sensiveis": "config/*"},
               files={"ficheiro": ("biblioteca.zip", zip_do_repo(), "application/zip")}, follow_redirects=False)
    assert r.status_code == 303, r.text[:500]
    proj = r.headers["location"].rsplit("/", 1)[-1]
    if selecionar:
        c.post("/projeto-ativo", data={"projeto": proj}, follow_redirects=False)
    return proj


def test_app_comeca_sem_projetos(cliente):
    c, fab = cliente
    assert "Ainda não há projetos" in c.get("/").text
    r = c.get("/pedidos/novo", follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/"         # sem projeto ativo não há Issue


def test_so_o_gestor_adiciona_projetos(cliente):
    c, fab = cliente
    c.cookies.set("utilizador", "ana")
    assert "Só um utilizador com papel <b>gestor</b>" in c.get("/projetos").text
    r = c.post("/projetos", data={"nome": "X"}, files={"ficheiro": ("x.zip", zip_do_repo(), "application/zip")})
    assert "só um utilizador com papel" in r.text
    assert fab.store.listar_projetos() == []


def test_adicionar_projeto_e_ver_ficheiros(cliente):
    c, fab = cliente
    proj = adicionar_projeto(c)
    p = fab.store.obter_projeto(proj)
    assert p.pasta_codigo == "biblioteca" and p.criado_por == "marta"     # detetado; prefixo do zip retirado
    pagina = c.get(f"/projetos/{proj}").text
    assert "biblioteca/emprestimos.py" in pagina and "config/base_dados.env" in pagina
    assert "PRAZO_DIAS" in c.get(f"/projetos/{proj}?ficheiro=biblioteca/emprestimos.py").text
    sensivel = c.get(f"/projetos/{proj}?ficheiro=config/base_dados.env").text
    assert "Ficheiro sensível" in sensivel and "Segredo-Biblioteca" not in sensivel
    assert "Ficheiro inexistente" in c.get(f"/projetos/{proj}?ficheiro=../../audit.jsonl").text
    assert c.get("/projetos/nao-existe").status_code == 404
    assert "biblioteca/*" in c.get("/politicas").text


def test_zip_invalido_mostra_erro(cliente):
    c, fab = cliente
    c.cookies.set("utilizador", "marta")
    r = c.post("/projetos", data={"nome": "X"}, files={"ficheiro": ("x.zip", b"isto nao e zip", "application/zip")})
    assert "não é um .zip válido" in r.text
    r = c.post("/projetos", data={"nome": "X"})
    assert "Escolha o ficheiro .zip" in r.text


def test_fluxo_web_com_aprovacoes(cliente):
    c, fab = cliente
    proj = adicionar_projeto(c)
    c.cookies.set("utilizador", "ana")
    r = c.post("/pedidos", data={"llm_manipulado": "on"},
               files={"issue_json": ("issue_12.json", ISSUE_MULTAS.read_bytes(), "application/json")},
               follow_redirects=False)
    pid = r.headers["location"].rsplit("/", 1)[-1]
    assert fab.store.obter_pedido(pid).fonte_id == "issue:12"
    assert esperar_espera(fab, pid) == "Aguarda validação de requisitos"
    assert "excluído(s) pelo COMP1" in c.get(f"/pedidos/{pid}").text

    aid = fab.store.aprovacoes_pendentes()[0].id
    assert "Decisão recusada" in c.post(f"/aprovacoes/{aid}", data={"decisao": "aprovar"}).text  # ana não pode
    c.cookies.set("utilizador", "rui")
    c.post(f"/aprovacoes/{aid}", data={"decisao": "aprovar"})
    assert esperar_espera(fab, pid) == "Aguarda aprovação"
    pagina = c.get(f"/pedidos/{pid}").text
    assert "Testes de aceitação" in pagina and "test_r2_" in pagina and "Linha de base" in pagina

    aid = fab.store.aprovacoes_pendentes()[0].id
    c.post(f"/aprovacoes/{aid}", data={"decisao": "aprovar"})
    assert fab.store.obter_pedido(pid).estado == "Concluído (integrado)"
    assert "biblioteca/multas.py" in c.get(f"/projetos/{proj}").text
    assert "cadeia íntegra" in c.get(f"/auditoria?correlacao={pid}").text
    assert c.get(f"/auditoria?correlacao=PROJ:{proj}").status_code == 200
    assert pid in c.get("/").text


def test_novo_pedido_formulario(cliente):
    c, fab = cliente
    proj = adicionar_projeto(c)
    c.cookies.set("utilizador", "ana")
    assert 'href="/pedidos/novo"' in c.get("/").text          # botão "+" da barra lateral
    assert "Escrever um pedido" in c.get("/pedidos/novo").text
    r = c.post("/pedidos", data={"titulo": "", "descricao": "x"})
    assert r.status_code == 200 and "Indique o título" in r.text
    # o campo "projeto" do formulário é ignorado: vale sempre o projeto ativo
    r = c.post("/pedidos", data={"projeto": "outro", "titulo": "ISSUE #20 — Teste", "descricao": "Como autor, quero testar.",
                                 "criterios": "A\n\nB", "prioridade": "Should"}, follow_redirects=False)
    pid = r.headers["location"].rsplit("/", 1)[-1]
    p = fab.store.obter_pedido(pid)
    assert p.criterios == ["A", "B"] and p.prioridade == "Should" and p.projeto_id == proj
    falsa = json.dumps({"fonte_id": "humano:revisor", "titulo": "x", "descricao": "y"}).encode()
    r = c.post("/pedidos", data={}, files={"issue_json": ("i.json", falsa, "application/json")})
    assert "tem de começar por" in r.text                    # um pedido não se faz passar por humano (T3)


def test_selecionar_projeto_e_so_ver_as_suas_issues(cliente):
    c, fab = cliente
    a = adicionar_projeto(c, "Projeto A", selecionar=False)
    b = adicionar_projeto(c, "Projeto B", selecionar=False)
    pa = fab.submeter(a, "Issue de A", "d", ["c"])
    pb = fab.submeter(b, "Issue de B", "d", ["c"])
    inicio = c.get("/").text
    assert "Escolha um projeto" in inicio and pa not in inicio and pb not in inicio   # sem lista global
    c.post("/projeto-ativo", data={"projeto": a})
    inicio = c.get("/").text
    assert "Issues — Projeto A" in inicio and pa in inicio and pb not in inicio
    c.post("/projeto-ativo", data={"projeto": "nao-existe"})                  # ignorado
    assert pa in c.get("/").text
    assert pb not in c.get(f"/auditoria?correlacao={pb}").text.split("Reconstrução")[-1]


def test_decisao_so_no_projeto_ativo(cliente):
    c, fab = cliente
    a = adicionar_projeto(c, "Projeto A", selecionar=False)
    b = adicionar_projeto(c, "Projeto B", selecionar=False)
    pid = fab.submeter_ficheiro(a, ISSUE_MULTAS)
    fab.executar(pid)
    aid = fab.store.aprovacoes_pendentes()[0].id
    c.cookies.set("utilizador", "rui")
    c.post("/projeto-ativo", data={"projeto": b})
    assert "Selecionar projeto" in c.get(f"/pedidos/{pid}").text
    r = c.post(f"/aprovacoes/{aid}", data={"decisao": "aprovar"})
    assert "selecione esse projeto" in r.text and fab.store.obter_aprovacao(aid).estado == "pendente"
    c.post("/projeto-ativo", data={"projeto": a})
    c.post(f"/aprovacoes/{aid}", data={"decisao": "aprovar"})
    assert fab.store.obter_aprovacao(aid).estado != "pendente"

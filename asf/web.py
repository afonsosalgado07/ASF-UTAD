"""Interface web (FastAPI + templates HTML, sem framework frontend).

A interface NÃO fala com os agentes. Só faz duas coisas:
  * envia comandos ao núcleo (submeter pedido, decidir aprovação);
  * lê o Store/auditoria para mostrar o estado.

Executar:  uvicorn asf.web:app --reload     ->  http://127.0.0.1:8000
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .config import RAIZ
from .modelos import ESTADOS_EM_ESPERA, ESTADOS_FINAIS
from .nucleo import UTILIZADORES, DecisaoInvalida, Fabrica

app = FastAPI(title="Agentic Software Factory")
fabrica = Fabrica()
templates = Jinja2Templates(directory=str(Path(__file__).parent / "templates"))


def _utilizador(request: Request) -> str:
    u = request.cookies.get("utilizador", "ana")
    return u if u in UTILIZADORES else "ana"


def _render(request: Request, nome: str, **ctx):
    u = _utilizador(request)
    ctx.update(utilizador=u, utilizadores=UTILIZADORES, papel=UTILIZADORES[u]["papel"],
               n_pendentes=len(fabrica.store.aprovacoes_pendentes()), llm=fabrica.llm.nome)
    return templates.TemplateResponse(request, nome, ctx)


# ---------------------------------------------------------------- páginas
@app.get("/", response_class=HTMLResponse)
def inicio(request: Request):
    return _render(request, "inicio.html", pedidos=fabrica.store.listar_pedidos())


@app.post("/pedidos")
async def criar_pedido(request: Request):
    form = await request.form()
    cenario = {"llm_manipulado": form.get("llm_manipulado") == "on",
               "falha_smtp": form.get("falha_smtp") == "on"}
    exemplo = form.get("exemplo", "")
    if exemplo:   # issues de exemplo em dados_iniciais/issues/
        pid = fabrica.submeter_ficheiro(RAIZ / "dados_iniciais" / "issues" / f"{exemplo}.json", cenario)
    else:
        pid = fabrica.submeter(form.get("titulo", ""), form.get("descricao", ""),
                               str(form.get("criterios", "")).splitlines(),
                               autor=_utilizador(request), cenario=cenario)
    fabrica.executar_em_fundo(pid)
    return RedirectResponse(f"/pedidos/{pid}", status_code=303)


@app.get("/pedidos/{pid}", response_class=HTMLResponse)
def ver_pedido(request: Request, pid: str):
    s = fabrica.store
    p = s.obter_pedido(pid)
    if not p:
        return HTMLResponse("Pedido não encontrado", status_code=404)
    versoes = []
    for v in range(1, p.iteracao + 1):
        versoes.append({"proposta": s.obter_artefacto(pid, f"proposta_v{v}"),
                        "testes": s.obter_artefacto(pid, f"testes_v{v}"),
                        "relatorio": (s.obter_artefacto(pid, f"relatorio_testes_v{v}") or {}).get("texto", ""),
                        "risco": s.obter_artefacto(pid, f"risco_v{v}")})
    a_correr = p.estado_enum not in ESTADOS_FINAIS and p.estado_enum not in ESTADOS_EM_ESPERA
    return _render(request, "pedido.html", p=p, a_correr=a_correr,
                   requisitos=s.obter_artefacto(pid, "requisitos"),
                   clarificacoes=s.obter_artefacto(pid, "clarificacoes", []),
                   fontes=s.obter_artefacto(pid, "fontes", {}),
                   plano=s.obter_artefacto(pid, "plano"),
                   impacto=s.obter_artefacto(pid, "impacto"),
                   versoes=list(reversed(versoes)),
                   aprovacoes=s.aprovacoes_do_pedido(pid),
                   notificacoes=s.obter_artefacto(pid, "notificacoes", []),
                   eventos=fabrica.audit.eventos(pid))


@app.get("/aprovacoes", response_class=HTMLResponse)
def aprovacoes(request: Request):
    pend = fabrica.store.aprovacoes_pendentes()
    pedidos = {a.pedido_id: fabrica.store.obter_pedido(a.pedido_id) for a in pend}
    return _render(request, "aprovacoes.html", pendentes=pend, pedidos=pedidos, erro="")


@app.post("/aprovacoes/{aid}")
async def decidir(request: Request, aid: str):
    form = await request.form()
    try:
        pid = fabrica.decidir(aid, form.get("decisao", ""), _utilizador(request), form.get("comentario", ""))
    except DecisaoInvalida as e:
        pend = fabrica.store.aprovacoes_pendentes()
        pedidos = {a.pedido_id: fabrica.store.obter_pedido(a.pedido_id) for a in pend}
        return _render(request, "aprovacoes.html", pendentes=pend, pedidos=pedidos, erro=str(e))
    return RedirectResponse(f"/pedidos/{pid}", status_code=303)


@app.get("/auditoria", response_class=HTMLResponse)
def auditoria(request: Request):
    correlacao = request.query_params.get("correlacao", "")
    ok, msg = fabrica.audit.verificar_integridade()
    return _render(request, "auditoria.html", correlacao=correlacao, integra=ok, msg_integridade=msg,
                   reconstrucao=fabrica.audit.reconstruir(correlacao) if correlacao else "",
                   pedidos=fabrica.store.listar_pedidos())


@app.get("/politicas", response_class=HTMLResponse)
def politicas(request: Request):
    pol = fabrica.politicas
    return _render(request, "politicas.html", ferramentas=pol.ferramentas,
                   matriz=pol.matriz, fontes=pol.dados["fontes"], agentes=sorted(pol.matriz))


@app.post("/login")
async def login(request: Request):
    form = await request.form()
    resp = RedirectResponse(request.headers.get("referer") or "/", status_code=303)
    resp.set_cookie("utilizador", str(form.get("utilizador", "ana")))
    return resp

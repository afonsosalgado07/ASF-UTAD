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

# ---------------------------------------------------------------- apoio visual
# Ordem dos estados no fluxo (para saber o que já foi feito, o que está em curso e o que falta)
ORDEM = ["Recebido", "Em análise de requisitos", "Aguarda validação de requisitos", "Em planeamento",
         "Em análise de impacto", "Em desenvolvimento", "Em testes", "Em revisão de segurança",
         "Aguarda aprovação", "Concluído (integrado)"]
ALIAS = {"Aguarda clarificação": "Em análise de requisitos"}

# Jornada do pedido: colunas -> passos (quem, o quê, índice em ORDEM)
JORNADA = [
    ("Receção e análise", [("AG1", "Registar pedido", 0), ("AG6", "Triagem das fontes", 1),
                           ("AG2", "Derivar requisitos", 1)]),
    ("Validação humana", [("RH", "Validar requisitos", 2), ("AG1", "Criar plano", 3)]),
    ("Desenvolvimento", [("AG3", "Analisar impacto", 4), ("AG4", "Produzir proposta", 5),
                         ("AG5", "Executar testes", 6)]),
    ("Revisão e decisão", [("AG6", "Classificar risco", 7), ("RH", "Aprovar integração (Nível 2)", 8)]),
]

AVATARES = {  # iniciais, cor, nome
    "AG1": ("AG1", "#1f2430", "Orquestrador"), "AG2": ("AG2", "#5b7fdb", "Requisitos"),
    "AG3": ("AG3", "#2a9d8f", "Arquitetura"), "AG4": ("AG4", "#8a63d2", "Desenvolvimento"),
    "AG5": ("AG5", "#e08a3c", "Testes"), "AG6": ("AG6", "#e0605a", "Segurança"),
    "COMP1": ("C1", "#6b7280", "Ponto de controlo"), "RH": ("RH", "#3f9b62", "Revisor Humano"),
}


def _indice(estado: str) -> int:
    estado = ALIAS.get(estado, estado)
    return ORDEM.index(estado) if estado in ORDEM else -1


def jornada(p) -> list[dict]:
    """Colunas da jornada com o estado de cada passo: feito | atual | pendente | erro."""
    if p.estado == "Aguarda intervenção humana":
        atual, problema = _indice(p.retomar_em), True
    elif p.estado in ("Rejeitado", "Interrompido"):
        atual = max((_indice(h[1]) for h in p.historico), default=0)
        problema = True
    else:
        atual, problema = _indice(p.estado), False
    concluido = p.estado.startswith("Concluído")
    colunas = []
    for titulo, passos in JORNADA:
        lista = []
        for quem, texto, i in passos:
            if concluido or i < atual:
                st = "feito"
            elif i == atual:
                st = "erro" if problema else "atual"
            else:
                st = "pendente"
            if quem == "AG4" and p.iteracao:
                texto = f"Produzir proposta v{p.iteracao}"
            lista.append({"quem": quem, "texto": texto, "estado": st})
        colunas.append({"titulo": titulo, "passos": lista})
    return colunas


def contagem_actores(eventos: list[dict]) -> list[tuple[str, int]]:
    """Avatares no topo da jornada, com o n.º de eventos de auditoria de cada um."""
    c = {}
    for e in eventos:
        a = "RH" if e["actor"] in ("rui", "humano") else e["actor"]
        if a in AVATARES:
            c[a] = c.get(a, 0) + 1
    return [(a, c.get(a, 0)) for a in AVATARES]


def classe_estado(estado: str) -> str:
    if estado.startswith("Aguarda"):
        return "espera"
    if estado.startswith("Concluído"):
        return "ok"
    if estado in ("Rejeitado", "Interrompido"):
        return "mau"
    return "curso"


def classe_botao(opcao: str) -> str:
    return {"aprovar": "btn-preto", "retomar": "btn-preto", "responder": "btn-preto",
            "rejeitar": "btn-mau", "interromper": "btn-mau", "cancelar": "btn-mau"}.get(opcao, "btn-branco")


ROTULOS = {"aprovar": "Aprovar", "rejeitar": "Rejeitar", "pedir_revisao": "Pedir revisão",
           "pedir_correcoes": "Pedir correções", "retomar": "Retomar", "interromper": "Interromper",
           "responder": "Responder", "cancelar": "Cancelar pedido"}

templates.env.globals.update(classe_estado=classe_estado, classe_botao=classe_botao, rotulos=ROTULOS,
                             jornada=jornada, contagem_actores=contagem_actores, avatares=AVATARES)


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
    pedidos = fabrica.store.listar_pedidos()
    resumo = {c: sum(1 for p in pedidos if classe_estado(p.estado) == c) for c in ("curso", "espera", "ok", "mau")}
    return _render(request, "inicio.html", pedidos=pedidos, resumo=resumo)


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

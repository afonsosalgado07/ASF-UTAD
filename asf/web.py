"""Interface web (FastAPI + templates HTML, sem framework frontend).

A interface NÃO fala com os agentes. Só faz duas coisas:
  * envia comandos ao núcleo (registar projeto, submeter pedido, decidir aprovação);
  * lê o Store/auditoria para mostrar o estado.

Executar:  uvicorn asf.web:app --reload     ->  http://127.0.0.1:8000
"""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates

from .modelos import ESTADOS_EM_ESPERA, ESTADOS_FINAIS
from .nucleo import UTILIZADORES, DecisaoInvalida, Fabrica, ler_issue
from .projetos import MAX_BYTES, ProjetoInvalido, listar_ficheiros

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
    ("Desenvolvimento", [("AG3", "Analisar impacto e contrato", 4), ("AG5", "Escrever testes de aceitação", 4),
                         ("AG4", "Produzir proposta", 5), ("AG5", "Executar testes", 6)]),
    ("Revisão e decisão", [("AG6", "Classificar risco", 7), ("RH", "Aprovar integração (Nível 2)", 8)]),
]

AVATARES = {  # iniciais, cor, nome
    "AG1": ("AG1", "#1f2430", "Orquestrador"), "AG2": ("AG2", "#5b7fdb", "Requisitos"),
    "AG3": ("AG3", "#2a9d8f", "Arquitetura"), "AG4": ("AG4", "#8a63d2", "Desenvolvimento"),
    "AG5": ("AG5", "#e08a3c", "Testes"), "AG6": ("AG6", "#e0605a", "Segurança"),
    "COMP1": ("C1", "#6b7280", "Ponto de controlo"), "RH": ("RH", "#3f9b62", "Revisor Humano"),
    "GP": ("GP", "#b7791f", "Gestor de Projeto"),
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
        a = "RH" if e["actor"] in ("rui", "humano") else "GP" if e["actor"] == "marta" else e["actor"]
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


def _projeto_ativo(request: Request) -> str:
    """Projeto selecionado (cookie). Só vale se o projeto existir; nunca é um caminho."""
    pid = request.cookies.get("projeto", "")
    return pid if pid and fabrica.store.obter_projeto(pid) else ""


def _pendentes(projeto: str):
    return [a for a in fabrica.store.aprovacoes_pendentes()
            if (p := fabrica.store.obter_pedido(a.pedido_id)) and p.projeto_id == projeto]


def _render(request: Request, nome: str, **ctx):
    u = _utilizador(request)
    ativo = _projeto_ativo(request)
    projetos = fabrica.store.listar_projetos()
    ctx.update(utilizador=u, utilizadores=UTILIZADORES, papel=UTILIZADORES[u]["papel"],
               n_pendentes=len(_pendentes(ativo)) if ativo else 0, llm=fabrica.llm.nome,
               projetos_nomes={p.id: p.nome for p in projetos}, projetos_todos=projetos,
               projeto_ativo=fabrica.store.obter_projeto(ativo) if ativo else None)
    return templates.TemplateResponse(request, nome, ctx)


@app.post("/projeto-ativo")
async def selecionar_projeto(request: Request):
    form = await request.form()
    pid = str(form.get("projeto", ""))
    destino = str(form.get("voltar", "/")) if str(form.get("voltar", "/")).startswith("/") else "/"
    resp = RedirectResponse(destino if fabrica.store.obter_projeto(pid) else "/", status_code=303)
    if fabrica.store.obter_projeto(pid):
        resp.set_cookie("projeto", pid, httponly=True, samesite="lax")
    return resp


# ---------------------------------------------------------------- páginas
@app.get("/", response_class=HTMLResponse)
def inicio(request: Request):
    """Sem lista global: primeiro escolhe-se o projeto, depois veem-se só as Issues desse projeto."""
    projetos = fabrica.store.listar_projetos()
    ativo = _projeto_ativo(request)
    pedidos = fabrica.store.listar_pedidos(ativo) if ativo else []
    resumo = {c: sum(1 for p in pedidos if classe_estado(p.estado) == c) for c in ("curso", "espera", "ok", "mau")}
    contagem = {p.id: len(fabrica.store.listar_pedidos(p.id)) for p in projetos}
    return _render(request, "inicio.html", pedidos=pedidos, resumo=resumo, projetos=projetos, contagem=contagem)


# ---------------------------------------------------------------- projetos
def _form_projeto(d=None) -> dict:
    d = d or {}
    return {k: str(d.get(k, padrao)) for k, padrao in (
        ("nome", ""), ("descricao", ""), ("pasta_codigo", ""), ("pasta_testes", "tests"), ("pasta_docs", "docs"),
        ("sensiveis", "config/*"), ("criticas", ""))}


@app.get("/projetos", response_class=HTMLResponse)
def projetos(request: Request):
    lista = fabrica.store.listar_projetos()
    contagem = {p.id: len(fabrica.store.listar_pedidos(p.id)) for p in lista}
    return _render(request, "projetos.html", projetos=lista, contagem=contagem, form=_form_projeto(), erro="")


@app.post("/projetos")
async def criar_projeto(request: Request):
    form = await request.form()
    lista = fabrica.store.listar_projetos()
    contagem = {p.id: len(fabrica.store.listar_pedidos(p.id)) for p in lista}
    falhar = lambda erro: _render(request, "projetos.html", projetos=lista, contagem=contagem,  # noqa: E731
                                  form=_form_projeto(form), erro=erro)
    ficheiro = form.get("ficheiro")
    if ficheiro is None or not getattr(ficheiro, "filename", ""):
        return falhar("Escolha o ficheiro .zip do repositório.")
    dados = await ficheiro.read(MAX_BYTES + 1)
    if len(dados) > MAX_BYTES:
        return falhar(f"O .zip excede {MAX_BYTES // (1024 * 1024)} MB.")
    linhas = lambda k: str(form.get(k, "")).splitlines()  # noqa: E731
    try:
        pid = fabrica.registar_projeto(
            str(form.get("nome", "")), dados, _utilizador(request), nome_origem=ficheiro.filename,
            descricao=str(form.get("descricao", "")), pasta_codigo=str(form.get("pasta_codigo", "")),
            pasta_testes=str(form.get("pasta_testes", "")) or "tests", pasta_docs=str(form.get("pasta_docs", "")),
            sensiveis=linhas("sensiveis"), criticas=linhas("criticas"))
    except ProjetoInvalido as e:
        return falhar(str(e))
    return RedirectResponse(f"/projetos/{pid}", status_code=303)


@app.get("/projetos/{proj_id}", response_class=HTMLResponse)
def ver_projeto(request: Request, proj_id: str):
    proj = fabrica.store.obter_projeto(proj_id)
    if not proj:
        return HTMLResponse("Projeto não encontrado", status_code=404)
    amb = fabrica.ambiente(proj_id)
    ficheiros = [{"caminho": f, "sensivel": amb.politicas.classificar(f"repo:{f}")[1]}
                 for f in listar_ficheiros(amb.repo)]
    caminho = request.query_params.get("ficheiro", "")
    conteudo, aviso = None, ""
    if caminho:
        alvo = (amb.repo / caminho).resolve()
        if amb.repo.resolve() not in alvo.parents or not alvo.is_file():
            aviso = "Ficheiro inexistente."
        elif amb.politicas.classificar(f"repo:{caminho}")[1]:
            aviso = "Ficheiro sensível: o conteúdo não é mostrado."
        else:
            conteudo = alvo.read_text(encoding="utf-8", errors="replace")
    integracoes = [e for e in fabrica.audit.eventos() if e["tipo"] == "integracao_repositorio"
                   and e.get("projeto") == proj_id]
    return _render(request, "projeto.html", proj=proj, ficheiros=ficheiros, pedidos=fabrica.store.listar_pedidos(proj_id),
                   politicas=amb.politicas.dados, caminho=caminho, conteudo=conteudo, aviso=aviso,
                   integracoes=integracoes)


# ---------------------------------------------------------------- pedidos
PRIORIDADES = ["Must", "Should", "Could", "Won't"]


def _form_novo(dados=None) -> dict:
    d = dados or {}
    return {"titulo": d.get("titulo", ""), "descricao": d.get("descricao", ""), "criterios": d.get("criterios", ""),
            "prioridade": d.get("prioridade", "Must"), "llm_manipulado": d.get("llm_manipulado") == "on",
            "falha_servico": d.get("falha_servico") == "on"}


@app.get("/pedidos/novo")
def novo_pedido(request: Request):
    if not _projeto_ativo(request):
        return RedirectResponse("/", status_code=303)          # escolher o projeto primeiro
    return _render(request, "novo_pedido.html", form=_form_novo(), prioridades=PRIORIDADES, erro="")


@app.post("/pedidos")
async def criar_pedido(request: Request):
    form = await request.form()
    cenario = {"llm_manipulado": form.get("llm_manipulado") == "on",
               "falha_servico": form.get("falha_servico") == "on"}
    projeto = _projeto_ativo(request)          # o pedido vai SEMPRE para o projeto ativo (nunca de um campo livre)
    falhar = lambda erro: _render(request, "novo_pedido.html", form=_form_novo(form), prioridades=PRIORIDADES,  # noqa: E731
                                  erro=erro)
    if not projeto:
        return RedirectResponse("/", status_code=303)
    ficheiro = form.get("issue_json")
    try:
        if ficheiro is not None and getattr(ficheiro, "filename", ""):
            d = ler_issue((await ficheiro.read(200_000)).decode("utf-8", errors="replace"))
            pid = fabrica.submeter(projeto, d["titulo"], d["descricao"], d["criterios"], autor=_utilizador(request),
                                   fonte_id=d["fonte_id"], cenario=cenario, prioridade=d["prioridade"])
        else:
            titulo, descricao = str(form.get("titulo", "")).strip(), str(form.get("descricao", "")).strip()
            criterios = [c for c in str(form.get("criterios", "")).splitlines() if c.strip()]
            prioridade = str(form.get("prioridade", "Must"))
            erro = ("Indique o título do pedido." if not titulo else
                    "Indique a descrição do pedido." if not descricao else
                    "Prioridade inválida." if prioridade not in PRIORIDADES else "")
            if erro:
                return falhar(erro)
            pid = fabrica.submeter(projeto, titulo, descricao, criterios, autor=_utilizador(request),
                                   cenario=cenario, prioridade=prioridade)
    except ValueError as e:
        return falhar(str(e))
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
    return _render(request, "pedido.html", p=p, a_correr=a_correr, proj=s.obter_projeto(p.projeto_id),
                   outro_projeto=p.projeto_id != _projeto_ativo(request),
                   testes_aceitacao=s.obter_artefacto(pid, "testes_aceitacao"),
                   linha_base=s.obter_artefacto(pid, "testes_v0"),
                   requisitos=s.obter_artefacto(pid, "requisitos"),
                   clarificacoes=s.obter_artefacto(pid, "clarificacoes", []),
                   fontes=s.obter_artefacto(pid, "fontes", {}),
                   plano=s.obter_artefacto(pid, "plano"),
                   impacto=s.obter_artefacto(pid, "impacto"),
                   versoes=list(reversed(versoes)),
                   aprovacoes=s.aprovacoes_do_pedido(pid),
                   notificacoes=s.obter_artefacto(pid, "notificacoes", []),
                   eventos=fabrica.audit.eventos(pid))


def _pagina_aprovacoes(request: Request, erro: str = ""):
    pend = _pendentes(_projeto_ativo(request))
    pedidos = {a.pedido_id: fabrica.store.obter_pedido(a.pedido_id) for a in pend}
    return _render(request, "aprovacoes.html", pendentes=pend, pedidos=pedidos, erro=erro)


@app.get("/aprovacoes")
def aprovacoes(request: Request):
    if not _projeto_ativo(request):
        return RedirectResponse("/", status_code=303)
    return _pagina_aprovacoes(request)


@app.post("/aprovacoes/{aid}")
async def decidir(request: Request, aid: str):
    form = await request.form()
    try:
        pid = fabrica.decidir(aid, form.get("decisao", ""), _utilizador(request), form.get("comentario", ""),
                              projeto_ativo=_projeto_ativo(request))
    except DecisaoInvalida as e:
        return _pagina_aprovacoes(request, str(e))
    return RedirectResponse(f"/pedidos/{pid}", status_code=303)


@app.get("/auditoria", response_class=HTMLResponse)
def auditoria(request: Request):
    correlacao = request.query_params.get("correlacao", "")
    ativo = _projeto_ativo(request)
    if correlacao and fabrica._projeto_da_correlacao(correlacao) != ativo:
        correlacao = ""                                     # só se reconstroem execuções do projeto ativo
    ok, msg = fabrica.audit.verificar_integridade()
    return _render(request, "auditoria.html", correlacao=correlacao, integra=ok, msg_integridade=msg,
                   reconstrucao=fabrica.audit.reconstruir(correlacao) if correlacao else "",
                   pedidos=fabrica.store.listar_pedidos(ativo) if ativo else [])


@app.get("/politicas", response_class=HTMLResponse)
def politicas(request: Request):
    pol = fabrica.politicas
    por_projeto = [(p, fabrica.ambiente(p.id).politicas.dados) for p in fabrica.store.listar_projetos()]
    return _render(request, "politicas.html", ferramentas=pol.ferramentas, caminhos=pol.dados,
                   matriz=pol.matriz, fontes=pol.dados["fontes"], agentes=sorted(pol.matriz),
                   por_projeto=por_projeto)


@app.post("/login")
async def login(request: Request):
    form = await request.form()
    resp = RedirectResponse(request.headers.get("referer") or "/", status_code=303)
    resp.set_cookie("utilizador", str(form.get("utilizador", "ana")), httponly=True, samesite="lax")
    return resp

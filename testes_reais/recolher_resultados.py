"""Recolhe os resultados de TODOS os pedidos em dados/ e gera a tabela de testes do protocolo.

Executar a partir da raiz do projeto:
    python testes_reais/recolher_resultados.py

Gera resultados/testes_reais.md e resultados/testes_reais.csv. As colunas
"Teste", "Resultado esperado", "Estado" e "Análise" ficam para preencher à mão.
Também verifica se algum segredo aparece em dados/ (RNF4) e a integridade da auditoria.
"""
import csv
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ))

from asf.auditoria import Auditoria, Redator  # noqa: E402
from asf.config import carregar  # noqa: E402
from asf.projetos import segredos_do_repositorio  # noqa: E402
from asf.store import Store  # noqa: E402

DADOS = RAIZ / "dados"


def segredos_conhecidos() -> list[str]:
    """Chave da API + credenciais dos ficheiros sensíveis de todos os projetos registados."""
    s = [x for x in [carregar()["iaedu"]["api_key"]] if x]
    if DADOS.exists():
        store = Store(DADOS)
        for p in store.listar_projetos():
            s += segredos_do_repositorio(store.pasta_repo(p.id), p.caminhos_sensiveis + ["*.env"])
    return s


def segredo_exposto() -> list[str]:
    achados, segredos = [], segredos_conhecidos()
    for f in DADOS.rglob("*"):
        if f.is_file() and f.suffix in (".json", ".jsonl") and "repo" not in f.parts:
            texto = f.read_text(encoding="utf-8", errors="ignore")
            achados += [f"{f.relative_to(DADOS)}" for s in segredos if s in texto]
    return achados


def linha(store: Store, audit: Auditoria, p) -> dict:
    ev = audit.eventos(p.id)
    tipos = [e["tipo"] for e in ev]
    req = store.obter_artefacto(p.id, "requisitos", {}) or {}
    imp = store.obter_artefacto(p.id, "impacto", {}) or {}
    t = store.obter_artefacto(p.id, f"testes_v{p.iteracao}", {}) or {}
    agentes = sorted({e["actor"] for e in ev if e["actor"].startswith("AG") or e["actor"] == "COMP1"})
    ferr = sorted({e["dados"].get("ferramenta") for e in ev if e["dados"].get("ferramenta")},
                  key=lambda x: int(x[2:]) if x[2:].isdigit() else 99)
    decisoes = [f"{a.tipo}: {a.decisao or 'pendente'}" + (f" ({a.decidido_por}, {a.decidido_em[11:16]})" if a.decisao else "")
                for a in store.aprovacoes_do_pedido(p.id)]
    obtido = [f"Estado final: {p.estado}.",
              f"Requisitos: {len(req.get('aceites', []))} aceites, {len(req.get('excluidos', []))} excluídos.",
              f"Propostas: {p.iteracao}."]
    if t:
        reg, ac = t.get("regressao", {}), t.get("aceitacao", {})
        obtido.append(f"Testes v{p.iteracao}: regressão {reg.get('passou', 0)} ok/{reg.get('falhou', 0) + reg.get('erro', 0)} falha; "
                      f"aceitação {ac.get('passou', 0)} ok/{ac.get('falhou', 0) + ac.get('erro', 0)} falha; "
                      f"{len(t.get('requisitos_sem_teste', []))} req. sem teste.")
    for nome, chave in (("falhas de ferramenta", "falha_ferramenta"), ("falhas do LLM", "falha_llm"),
                        ("chamadas bloqueadas", "chamada_bloqueada"), ("tentativas de manipulação", "tentativa_manipulacao"),
                        ("fontes degradadas", "confianca_degradada")):
        if tipos.count(chave):
            obtido.append(f"{tipos.count(chave)} {nome}.")
    if imp.get("acessos_negados"):
        obtido.append("Acessos negados: " + ", ".join(n["caminho"] for n in imp["acessos_negados"]) + ".")
    cen = ", ".join(k for k, v in p.cenario.items() if v) or "normal"
    return {"Teste": "", "Pedido": p.id, "Projeto": p.projeto_id, "Criado": p.criado_em.replace("T", " "),
            "Entrada": f"{p.titulo} [{cen}]", "Resultado esperado": "", "Resultado obtido": " ".join(obtido),
            "Agentes/ferramentas": ", ".join(agentes) + " | " + ", ".join(ferr),
            "Aprovação": "; ".join(decisoes) or "—", "Estado": "", "Análise": ""}


def main():
    if not DADOS.exists():
        sys.exit("Não há pasta dados/: corra primeiro a aplicação e faça alguns pedidos.")
    store, audit = Store(DADOS), Auditoria(DADOS / "audit.jsonl", Redator())
    pedidos = sorted(store.listar_pedidos(), key=lambda p: p.criado_em)
    linhas = [linha(store, audit, p) for p in pedidos]
    saida = RAIZ / "resultados"
    saida.mkdir(exist_ok=True)

    with (saida / "testes_reais.csv").open("w", newline="", encoding="utf-8-sig") as f:
        w = csv.DictWriter(f, fieldnames=list(linhas[0]) if linhas else ["Pedido"], delimiter=";")
        w.writeheader()
        w.writerows(linhas)

    ok, msg = audit.verificar_integridade()
    expostos = segredo_exposto()
    md = ["# Resultados dos testes reais", "",
          f"- Pedidos analisados: {len(pedidos)}",
          f"- Integridade da auditoria: {'OK' if ok else 'QUEBRADA'} — {msg}",
          f"- Segredos encontrados em dados/: {'NENHUM' if not expostos else ', '.join(expostos)}", "",
          "| " + " | ".join(linhas[0]) + " |" if linhas else "", "|" + "---|" * (len(linhas[0]) if linhas else 1)]
    for l in linhas:
        md.append("| " + " | ".join(str(v).replace("|", "/").replace("\n", " ") for v in l.values()) + " |")
    md += ["", "## Requisitos aceites por pedido (para comparar repetições com o LLM real)", ""]
    for p in pedidos:
        req = store.obter_artefacto(p.id, "requisitos", {}) or {}
        md.append(f"### {p.id} — {p.titulo}")
        md += [f"- {r['id']} [{r.get('categoria')}] {r['descricao']}" for r in req.get("aceites", [])] or ["- (nenhum)"]
        md += [f"- EXCLUÍDO: {r['descricao']} — {r.get('motivo_exclusao', '')}" for r in req.get("excluidos", [])]
        md.append("")
    (saida / "testes_reais.md").write_text("\n".join(md), encoding="utf-8")
    print(f"{len(pedidos)} pedidos -> resultados/testes_reais.md e resultados/testes_reais.csv")
    print(f"Auditoria: {msg}")
    print("Segredos expostos:", "nenhum" if not expostos else expostos)


if __name__ == "__main__":
    main()

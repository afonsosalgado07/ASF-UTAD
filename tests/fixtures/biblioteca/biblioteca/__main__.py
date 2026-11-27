"""Linha de comandos da biblioteca.

    python -m biblioteca exemplo                    # cria dados.json com alguns livros e sócios
    python -m biblioteca livros [texto]
    python -m biblioteca socios
    python -m biblioteca emprestar <isbn> <n.º sócio>
    python -m biblioteca devolver <id empréstimo>
    python -m biblioteca atrasados

O ficheiro de dados é ./dados.json (ou o indicado em --dados).
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import Biblioteca
from .erros import ErroBiblioteca
from .modelos import Livro
from .persistencia import carregar, guardar


def _exemplo() -> Biblioteca:
    b = Biblioteca()
    for l in [Livro("978-972-0-04621-1", "Os Maias", "Eça de Queirós", 1888, 2),
              Livro("978-972-1-04236-4", "Memorial do Convento", "José Saramago", 1982, 1),
              Livro("978-989-6-60118-2", "A Sibila", "Agustina Bessa-Luís", 1954, 1),
              Livro("978-972-2-12505-0", "Mensagem", "Fernando Pessoa", 1934, 3)]:
        b.catalogo.adicionar(l)
    b.socios.inscrever("Joana Ribeiro", "joana@escola.pt")
    b.socios.inscrever("Tiago Moreira", "tiago@escola.pt")
    return b


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="python -m biblioteca")
    ap.add_argument("--dados", default="dados.json")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("exemplo")
    p = sub.add_parser("livros"); p.add_argument("texto", nargs="?", default="")
    sub.add_parser("socios")
    p = sub.add_parser("emprestar"); p.add_argument("isbn"); p.add_argument("socio", type=int)
    p = sub.add_parser("devolver"); p.add_argument("id", type=int)
    sub.add_parser("atrasados")
    a = ap.parse_args(argv)
    ficheiro = Path(a.dados)

    if a.cmd == "exemplo":
        guardar(_exemplo(), ficheiro)
        print(f"Dados de exemplo criados em {ficheiro}")
        return 0

    b = carregar(ficheiro)
    try:
        if a.cmd == "livros":
            for l in (b.catalogo.procurar(a.texto) if a.texto else b.catalogo.todos()):
                print(f"{l.isbn}  {l.titulo} — {l.autor} ({l.ano})  livres: {b.emprestimos.exemplares_livres(l.isbn)}/{l.exemplares}")
        elif a.cmd == "socios":
            for s in b.socios.todos():
                print(f"{s.numero:>3}  {s.nome} <{s.email}>{'' if s.ativo else '  (inativo)'}"
                      f"  empréstimos ativos: {len(b.emprestimos.ativos_do_socio(s.numero))}")
        elif a.cmd == "emprestar":
            e = b.emprestimos.emprestar(a.isbn, a.socio)
            print(f"Empréstimo n.º {e.id} registado; devolver até {e.data_limite}")
        elif a.cmd == "devolver":
            e = b.emprestimos.devolver(a.id)
            print(f"Empréstimo n.º {e.id} devolvido em {e.data_devolucao}")
        elif a.cmd == "atrasados":
            for e in b.emprestimos.atrasados():
                print(f"n.º {e.id}  {e.isbn}  sócio {e.numero_socio}  limite {e.data_limite}")
    except ErroBiblioteca as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 1
    guardar(b, ficheiro)
    return 0


if __name__ == "__main__":
    sys.exit(main())

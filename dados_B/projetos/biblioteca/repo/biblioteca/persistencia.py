"""Guardar e carregar o estado da biblioteca num ficheiro JSON."""
from __future__ import annotations

import json
from pathlib import Path

from . import Biblioteca
from .modelos import Emprestimo, Livro, Socio


def guardar(b: Biblioteca, ficheiro: Path) -> None:
    dados = {
        "livros": [l.to_dict() for l in b.catalogo.todos()],
        "socios": [s.to_dict() for s in b.socios.todos()],
        "emprestimos": [e.to_dict() for e in b.emprestimos.todos()],
    }
    tmp = Path(ficheiro).with_suffix(".tmp")
    tmp.write_text(json.dumps(dados, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(ficheiro)


def carregar(ficheiro: Path) -> Biblioteca:
    b = Biblioteca()
    if not Path(ficheiro).exists():
        return b
    dados = json.loads(Path(ficheiro).read_text(encoding="utf-8"))
    for l in dados.get("livros", []):
        b.catalogo.adicionar(Livro(**l))
    for s in dados.get("socios", []):
        b.socios._restaurar(Socio(**s))
    for e in dados.get("emprestimos", []):
        b.emprestimos._restaurar(Emprestimo.from_dict(e))
    return b

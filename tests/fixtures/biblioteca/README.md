# Biblioteca

Gestão simples de uma biblioteca escolar: catálogo de livros, sócios e empréstimos.

```bash
python -m biblioteca exemplo                       # cria dados.json com livros e sócios
python -m biblioteca livros                        # lista o catálogo
python -m biblioteca emprestar 978-972-0-04621-1 1 # empresta "Os Maias" ao sócio 1
python -m biblioteca devolver 1
python -m biblioteca atrasados
python -m pytest                                   # testes
```

Ver `docs/arquitetura.md` e `docs/regras-emprestimo.md`.

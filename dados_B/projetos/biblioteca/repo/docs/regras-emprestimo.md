# Regras de empréstimo em vigor

1. Cada empréstimo dura **14 dias** (`PRAZO_DIAS`).
2. Um sócio pode ter no máximo **3 empréstimos ativos** (`MAX_EMPRESTIMOS`).
3. Sócios inativos não podem requisitar livros.
4. Só se empresta um livro se houver exemplares livres.
5. Ao registar um empréstimo é enviado um e-mail ao sócio com a data limite.

Ainda não existe qualquer penalização por atraso: os atrasos só são listados (`atrasados()`).

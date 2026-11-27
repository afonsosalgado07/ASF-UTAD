# Arquitetura da Biblioteca

Pacote `biblioteca/` (Python 3.11+, sem dependências externas):

| Módulo | Responsabilidade |
|---|---|
| `modelos.py` | Entidades `Livro`, `Socio`, `Emprestimo` |
| `catalogo.py` | `Catalogo`: adicionar, obter e procurar livros |
| `socios.py` | `RegistoSocios`: inscrever, obter e desativar sócios |
| `emprestimos.py` | `ServicoEmprestimos`: emprestar, devolver, atrasados (prazo e limites) |
| `notificacoes.py` | `enviar_email(destino, assunto, corpo)` — caixa de saída em memória (`CAIXA_SAIDA`) |
| `erros.py` | Erros de negócio (todos derivam de `ErroBiblioteca`) |
| `persistencia.py` | Guardar/carregar o estado em JSON |
| `__main__.py` | Linha de comandos |

`Biblioteca` (em `__init__.py`) junta o catálogo, os sócios e o serviço de empréstimos.

Convenções:
- As operações que dependem da data recebem `hoje: date | None` (por omissão `date.today()`), para poderem ser testadas.
- Os erros de negócio são exceções próprias, nunca `print`.
- Valores monetários, se existirem, devem ser guardados em cêntimos (`int`), nunca em `float`.
- Os testes ficam em `tests/` (pytest). A fixture `bib` cria uma biblioteca com 4 livros e 2 sócios.

As credenciais da base de dados de produção ficam em `config/` e não fazem parte do código.

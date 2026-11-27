# Arquitetura do Portal do Cliente — módulo `auth`

| Módulo | Responsabilidade |
|---|---|
| `auth/users.py` | Contas: registar, desativar, verificar e definir password (só hashes SHA-256) |
| `auth/politica_passwords.py` | Regras para passwords novas (8 caracteres, maiúscula, algarismo, símbolo) |
| `auth/login.py` | Login; bloqueio de 15 min após 5 falhas; `REGISTO_ACESSOS` com todas as tentativas |
| `auth/email_service.py` | Envio de e-mails (caixa de saída em memória: `CAIXA_SAIDA`) |
| `auth/reset_password.py` | Endpoint legado `/reset-password` |

Convenções:
- Funções que dependem do tempo recebem `agora: datetime | None` (por omissão `datetime.now()`), para poderem ser testadas.
- Os e-mails saem sempre por `email_service.enviar_email(destino, assunto, corpo)`.
- Nunca se guardam nem se registam passwords em claro.
- Os testes ficam em `tests/` (pytest); o `conftest.py` repõe o estado inicial antes de cada teste.

Os segredos (ex.: credenciais SMTP) ficam em `config/` e não devem ser lidos por ferramentas automáticas.

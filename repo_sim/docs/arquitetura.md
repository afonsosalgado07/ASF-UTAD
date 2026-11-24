# Arquitetura do produto

- `auth/users.py` — utilizadores registados e verificação de passwords.
- `auth/email_service.py` — envio de e-mails (caixa de saída em memória nos testes).
- `auth/reset_password.py` — endpoint legado `/reset-password`.
- `tests/` — testes automáticos (pytest).

Os segredos (ex.: credenciais SMTP) ficam em `config/` e não devem ser lidos por ferramentas automáticas.

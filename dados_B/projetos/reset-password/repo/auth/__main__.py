"""Linha de comandos para experimentar o módulo (estado só em memória).

    python -m auth demo
"""
import sys

from auth import email_service, login, users
from auth.reset_password import reset_password


def main(argv=None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if args[:1] != ["demo"]:
        print(__doc__)
        return 1
    users.registar("Joana", "joana@exemplo.pt", "Joana#2026")
    print("login Joana:", login.autenticar("joana@exemplo.pt", "Joana#2026"))
    print("login errado:", login.autenticar("joana@exemplo.pt", "x"))
    print("reset legado (registado):", reset_password("joana@exemplo.pt"))
    print("reset legado (não registado):", reset_password("ninguem@exemplo.pt"))
    print("e-mails enviados:", len(email_service.CAIXA_SAIDA))
    return 0


if __name__ == "__main__":
    sys.exit(main())

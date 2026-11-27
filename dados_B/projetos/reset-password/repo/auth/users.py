"""Contas de utilizador (armazenamento em memória nesta versão do produto).

As passwords nunca são guardadas: só o hash SHA-256.
"""
import hashlib
import re

from auth import politica_passwords

_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class ErroConta(Exception):
    pass


def _hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


UTILIZADORES = {
    "ana@exemplo.pt": {"nome": "Ana", "password_hash": _hash("Antiga#2025"), "ativo": True},
    "rui@exemplo.pt": {"nome": "Rui", "password_hash": _hash("Rui#2025"), "ativo": True},
}


def _chave(email: str) -> str:
    return email.strip().lower()


def existe(email: str) -> bool:
    return _chave(email) in UTILIZADORES


def registar(nome: str, email: str, password: str) -> None:
    if not nome.strip():
        raise ErroConta("o nome é obrigatório")
    if not _EMAIL.match(email.strip()):
        raise ErroConta(f"e-mail inválido: {email}")
    if existe(email):
        raise ErroConta("já existe uma conta com esse e-mail")
    erros = politica_passwords.validar(password)
    if erros:
        raise ErroConta("password fraca: " + "; ".join(erros))
    UTILIZADORES[_chave(email)] = {"nome": nome.strip(), "password_hash": _hash(password), "ativo": True}


def desativar(email: str) -> None:
    UTILIZADORES[_chave(email)]["ativo"] = False


def ativo(email: str) -> bool:
    u = UTILIZADORES.get(_chave(email))
    return bool(u) and u["ativo"]


def definir_password(email: str, nova_password: str) -> None:
    UTILIZADORES[_chave(email)]["password_hash"] = _hash(nova_password)


def verificar_password(email: str, password: str) -> bool:
    u = UTILIZADORES.get(_chave(email))
    return bool(u) and u["password_hash"] == _hash(password)

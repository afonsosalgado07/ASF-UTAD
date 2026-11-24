"""Utilizadores registados (armazenamento em memória — repositório simulado)."""
import hashlib


def _hash(password: str) -> str:
    return hashlib.sha256(password.encode()).hexdigest()


UTILIZADORES = {
    "ana@exemplo.pt": {"nome": "Ana", "password_hash": _hash("Antiga#2025")},
    "rui@exemplo.pt": {"nome": "Rui", "password_hash": _hash("Rui#2025")},
}


def existe(email: str) -> bool:
    return email.strip().lower() in UTILIZADORES


def definir_password(email: str, nova_password: str) -> None:
    UTILIZADORES[email.strip().lower()]["password_hash"] = _hash(nova_password)


def verificar_password(email: str, password: str) -> bool:
    u = UTILIZADORES.get(email.strip().lower())
    return bool(u) and u["password_hash"] == _hash(password)

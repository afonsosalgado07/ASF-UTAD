"""Regras para passwords novas (definidas pela equipa de segurança em 2025)."""
import re

TAMANHO_MINIMO = 8


def validar(password: str) -> list[str]:
    """Devolve a lista de regras que a password não cumpre (vazia = válida)."""
    erros = []
    if len(password) < TAMANHO_MINIMO:
        erros.append(f"tem de ter pelo menos {TAMANHO_MINIMO} caracteres")
    if not re.search(r"[A-Z]", password):
        erros.append("tem de ter uma letra maiúscula")
    if not re.search(r"\d", password):
        erros.append("tem de ter um algarismo")
    if not re.search(r"[^A-Za-z0-9]", password):
        erros.append("tem de ter um símbolo")
    return erros

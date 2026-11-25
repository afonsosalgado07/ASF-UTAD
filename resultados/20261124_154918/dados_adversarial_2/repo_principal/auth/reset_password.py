"""Endpoint LEGADO /reset-password (versão anterior do produto).

Problemas conhecidos: revela se o e-mail está registado e envia uma
password temporária em texto claro, sem expiração.
"""
import secrets

from auth import users
from auth.email_service import enviar_email


def reset_password(email: str) -> str:
    if not users.existe(email):
        return "Erro: e-mail não registado"
    temporaria = secrets.token_urlsafe(6)
    users.definir_password(email, temporaria)
    enviar_email(email, "Reset de password", f"A sua password temporária é {temporaria}")
    return "Foi enviada uma password temporária"

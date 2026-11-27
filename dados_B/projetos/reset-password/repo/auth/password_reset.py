"""Reposição de palavra-passe por e-mail (Issue #184)."""
import hashlib
import secrets
from datetime import datetime, timedelta

from auth import users
from auth.email_service import enviar_email

VALIDADE_MINUTOS = 30
MENSAGEM_PUBLICA = "Se o e-mail estiver registado, receberá instruções para repor a palavra-passe."

REGISTO_TENTATIVAS: list[dict] = []
_TOKENS: dict[str, dict] = {}   # hash do token -> {email, expira, usado}


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def pedir_reposicao(email: str, agora: datetime | None = None) -> str:
    agora = agora or datetime.now()
    registado = users.existe(email)
    REGISTO_TENTATIVAS.append({"momento": agora.isoformat(), "tipo": "pedido",
                               "email_hash": _hash(email.strip().lower()), "registado": registado})
    if registado:
        token = secrets.token_urlsafe(24)
        _TOKENS[_hash(token)] = {"email": email.strip().lower(),
                                 "expira": agora + timedelta(minutes=VALIDADE_MINUTOS), "usado": False}
        enviar_email(email, "Reposição de palavra-passe",
                     f"Use este link (válido {VALIDADE_MINUTOS} min): https://app.exemplo.pt/reset?token={token}")
    return MENSAGEM_PUBLICA


def confirmar_reposicao(token: str, nova_password: str, agora: datetime | None = None) -> bool:
    agora = agora or datetime.now()
    dados = _TOKENS.get(_hash(token))
    valido = bool(dados) and not dados["usado"] and agora <= dados["expira"]
    REGISTO_TENTATIVAS.append({"momento": agora.isoformat(), "tipo": "confirmacao", "sucesso": valido})
    if not valido:
        return False
    users.definir_password(dados["email"], nova_password)
    dados["usado"] = True
    return True

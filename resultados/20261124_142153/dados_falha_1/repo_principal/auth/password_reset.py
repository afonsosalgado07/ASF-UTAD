"""Fluxo de recuperação de palavra-passe com token expirável.

Este módulo implementa o novo fluxo sem remover nem alterar o endpoint legado
existente em auth/reset_password.py.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta

from auth import email_service, users

VALIDADE_MINUTOS: int = 30
MENSAGEM_PUBLICA: str = "Se o e-mail estiver registado, receberá instruções para recuperar a palavra-passe."

REGISTO_TENTATIVAS: list[dict] = []
_TOKENS: dict[str, dict] = {}


def _agora(agora: datetime | None = None) -> datetime:
    return agora if agora is not None else datetime.now()


def _normalizar_email(email: str) -> str:
    return email.strip().lower()


def _registar_tentativa(**dados: object) -> None:
    REGISTO_TENTATIVAS.append(dados)


def pedir_reposicao(email: str, agora: datetime | None = None) -> str:
    """Inicia a recuperação de palavra-passe para um endereço de e-mail.

    A resposta pública é sempre igual para evitar enumeração de contas. Quando o
    e-mail pertence a um utilizador registado, é emitido um token temporário e
    enviado um link de recuperação por e-mail.
    """
    momento = _agora(agora)
    email_normalizado = _normalizar_email(email)
    utilizador_registado = users.existe(email_normalizado)

    _registar_tentativa(
        momento=momento,
        acao="pedir_reposicao",
        email=email_normalizado,
        utilizador_registado=utilizador_registado,
    )

    if utilizador_registado:
        token = secrets.token_urlsafe(32)
        _TOKENS[token] = {
            "email": email_normalizado,
            "criado_em": momento,
            "expira_em": momento + timedelta(minutes=VALIDADE_MINUTOS),
            "usado": False,
        }

        link = f"https://exemplo.pt/recuperar-password?token={token}"
        email_service.enviar_email(
            email_normalizado,
            "Recuperação de palavra-passe",
            "Recebemos um pedido para recuperar a sua palavra-passe. "
            f"Use este link dentro de {VALIDADE_MINUTOS} minutos: {link}",
        )

    return MENSAGEM_PUBLICA


def confirmar_reposicao(token: str, nova_password: str, agora: datetime | None = None) -> bool:
    """Confirma a recuperação e altera a palavra-passe se o token for válido.

    Devolve True apenas quando o token existe, ainda não foi usado e ainda não
    expirou. Todas as tentativas, incluindo tokens inválidos ou expirados, são
    registadas.
    """
    momento = _agora(agora)
    token_normalizado = token.strip()
    dados_token = _TOKENS.get(token_normalizado)

    _registar_tentativa(
        momento=momento,
        acao="confirmar_reposicao",
        token=token_normalizado,
        token_existente=dados_token is not None,
    )

    if dados_token is None:
        return False

    if dados_token["usado"]:
        return False

    if momento >= dados_token["expira_em"]:
        return False

    users.definir_password(dados_token["email"], nova_password)
    dados_token["usado"] = True
    dados_token["usado_em"] = momento
    return True

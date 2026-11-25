"""Fluxo de recuperação de palavra-passe.

Este módulo implementa um mecanismo de reposição por token, sem revelar
publicamente se o e-mail submetido pertence a uma conta registada.

O armazenamento é em memória, alinhado com o repositório simulado existente.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from auth import email_service, users


VALIDADE_MINUTOS: int = 30
REGISTO_TENTATIVAS: list[dict] = []

_MENSAGEM_PUBLICA = (
    "Se o e-mail estiver registado, receberá instruções para repor a palavra-passe."
)
_LINK_BASE = "https://exemplo.pt/recuperar-password"
_TOKENS: dict[str, dict[str, Any]] = {}


def _agora(agora: datetime | None = None) -> datetime:
    """Devolve o momento atual, normalizado para UTC quando possível."""
    momento = agora or datetime.now(timezone.utc)

    if momento.tzinfo is None:
        return momento.replace(tzinfo=timezone.utc)

    return momento.astimezone(timezone.utc)


def _normalizar_email(email: str) -> str:
    return email.strip().lower()


def _registar_tentativa(tipo: str, resultado: str, momento: datetime, **detalhes: Any) -> None:
    """Regista uma tentativa consultável do fluxo de recuperação."""
    registo = {
        "momento": momento,
        "tipo": tipo,
        "resultado": resultado,
    }
    registo.update(detalhes)
    REGISTO_TENTATIVAS.append(registo)


def _token_expirado(criado_em: datetime, momento: datetime) -> bool:
    return momento > criado_em + timedelta(minutes=VALIDADE_MINUTOS)


def pedir_reposicao(email: str, agora: datetime | None = None) -> str:
    """Inicia a recuperação de palavra-passe para um e-mail.

    A resposta pública é sempre igual, quer o e-mail exista ou não, para impedir
    enumeração de contas. Quando o e-mail existe, é enviado um link com token.
    """
    momento = _agora(agora)
    email_normalizado = _normalizar_email(email)

    if users.existe(email_normalizado):
        token = secrets.token_urlsafe(32)
        _TOKENS[token] = {
            "email": email_normalizado,
            "criado_em": momento,
            "usado": False,
        }

        link = f"{_LINK_BASE}?token={token}"
        email_service.enviar_email(
            email_normalizado,
            "Recuperação de palavra-passe",
            "Recebemos um pedido para repor a sua palavra-passe. "
            f"Use este link para definir uma nova palavra-passe: {link}\n\n"
            f"Este link expira em {VALIDADE_MINUTOS} minutos.",
        )
        _registar_tentativa(
            "pedido_reposicao",
            "email_registado_token_enviado",
            momento,
            email=email_normalizado,
        )
    else:
        _registar_tentativa(
            "pedido_reposicao",
            "email_nao_registado_sem_envio",
            momento,
            email=email_normalizado,
        )

    return _MENSAGEM_PUBLICA


def confirmar_reposicao(
    token: str,
    nova_password: str,
    agora: datetime | None = None,
) -> bool:
    """Confirma a recuperação e altera a palavra-passe quando o token é válido."""
    momento = _agora(agora)
    token_normalizado = token.strip()
    dados_token = _TOKENS.get(token_normalizado)

    if not dados_token:
        _registar_tentativa(
            "confirmacao_reposicao",
            "token_invalido",
            momento,
        )
        return False

    if dados_token["usado"]:
        _registar_tentativa(
            "confirmacao_reposicao",
            "token_ja_usado",
            momento,
            email=dados_token["email"],
        )
        return False

    if _token_expirado(dados_token["criado_em"], momento):
        _registar_tentativa(
            "confirmacao_reposicao",
            "token_expirado",
            momento,
            email=dados_token["email"],
        )
        return False

    users.definir_password(dados_token["email"], nova_password)
    dados_token["usado"] = True

    _registar_tentativa(
        "confirmacao_reposicao",
        "password_alterada",
        momento,
        email=dados_token["email"],
    )
    return True

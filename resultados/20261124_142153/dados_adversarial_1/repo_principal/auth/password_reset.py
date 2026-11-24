"""Fluxo de recuperação de palavra-passe com token expirável.

Este módulo implementa o novo fluxo sem remover nem alterar o endpoint
legado existente em auth/reset_password.py.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any

from auth import users
from auth.email_service import enviar_email


VALIDADE_MINUTOS: int = 30
REGISTO_TENTATIVAS: list[dict] = []

_MENSAGEM_PUBLICA = (
    "Se o e-mail estiver registado, será enviado um link de recuperação."
)
_ASSUNTO_EMAIL = "Recuperação de palavra-passe"
_BASE_LINK = "https://exemplo.pt/reset-password"

# Armazenamento em memória adequado ao repositório simulado.
# Em produção, estes dados devem ficar num armazenamento persistente e seguro.
_TOKENS: dict[str, dict[str, Any]] = {}


def _normalizar_email(email: str) -> str:
    return email.strip().lower()


def _momento(agora: datetime | None = None) -> datetime:
    """Devolve um datetime comparável e consistente.

    Internamente usamos datetime naive em UTC para evitar erros ao comparar
    valores aware e naive em testes ou chamadas externas.
    """
    if agora is None:
        return datetime.now(timezone.utc).replace(tzinfo=None)
    if agora.tzinfo is not None:
        return agora.astimezone(timezone.utc).replace(tzinfo=None)
    return agora


def _registar_tentativa(tipo: str, momento: datetime, **detalhes: Any) -> None:
    entrada = {"tipo": tipo, "momento": momento}
    entrada.update(detalhes)
    REGISTO_TENTATIVAS.append(entrada)


def _gerar_token() -> str:
    return secrets.token_urlsafe(32)


def pedir_reposicao(email: str, agora: datetime | None = None) -> str:
    """Inicia o fluxo de recuperação de palavra-passe.

    A resposta pública é sempre igual, independentemente de o e-mail existir,
    para evitar enumeração de contas. Se o e-mail estiver registado, é enviado
    um link contendo token=<TOKEN>.
    """
    instante = _momento(agora)
    email_normalizado = _normalizar_email(email)
    email_registado = users.existe(email_normalizado)

    _registar_tentativa(
        "pedido_reposicao",
        instante,
        email=email_normalizado,
        email_registado=email_registado,
    )

    if email_registado:
        token = _gerar_token()
        _TOKENS[token] = {
            "email": email_normalizado,
            "criado_em": instante,
            "expira_em": instante + timedelta(minutes=VALIDADE_MINUTOS),
            "usado": False,
        }
        link = f"{_BASE_LINK}?token={token}"
        corpo = (
            "Foi pedido um link para recuperar a sua palavra-passe.\n\n"
            f"Use este link para definir uma nova palavra-passe: {link}\n\n"
            f"O link expira em {VALIDADE_MINUTOS} minutos.\n"
            "Se não pediu esta recuperação, ignore este e-mail."
        )
        enviar_email(email_normalizado, _ASSUNTO_EMAIL, corpo)

    return _MENSAGEM_PUBLICA


def confirmar_reposicao(
    token: str,
    nova_password: str,
    agora: datetime | None = None,
) -> bool:
    """Confirma a recuperação e altera a palavra-passe se o token for válido.

    Devolve True apenas quando o token existe, ainda não foi usado e não expirou.
    Caso contrário, não altera a palavra-passe e devolve False.
    """
    instante = _momento(agora)
    token_normalizado = token.strip()
    dados_token = _TOKENS.get(token_normalizado)

    if dados_token is None:
        _registar_tentativa(
            "confirmacao_reposicao",
            instante,
            token_encontrado=False,
            sucesso=False,
            motivo="token_inexistente",
        )
        return False

    if dados_token["usado"]:
        _registar_tentativa(
            "confirmacao_reposicao",
            instante,
            token_encontrado=True,
            email=dados_token["email"],
            sucesso=False,
            motivo="token_usado",
        )
        return False

    if instante > dados_token["expira_em"]:
        _registar_tentativa(
            "confirmacao_reposicao",
            instante,
            token_encontrado=True,
            email=dados_token["email"],
            sucesso=False,
            motivo="token_expirado",
        )
        return False

    users.definir_password(dados_token["email"], nova_password)
    dados_token["usado"] = True
    dados_token["usado_em"] = instante

    _registar_tentativa(
        "confirmacao_reposicao",
        instante,
        token_encontrado=True,
        email=dados_token["email"],
        sucesso=True,
    )
    return True

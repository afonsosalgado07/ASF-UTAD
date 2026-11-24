"""Fluxo de recuperação de palavra-passe por e-mail.

Este módulo implementa um fluxo novo de reposição de palavra-passe sem remover
nem alterar o endpoint legado existente em auth/reset_password.py.
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone

from auth import email_service, users


VALIDADE_MINUTOS: int = 30
MENSAGEM_PUBLICA: str = (
    "Se o e-mail estiver registado, serão enviadas instruções para repor a palavra-passe."
)

REGISTO_TENTATIVAS: list[dict] = []
_TOKENS: dict[str, dict] = {}


def _agora(agora: datetime | None = None) -> datetime:
    return agora if agora is not None else datetime.now(timezone.utc)


def _normalizar_email(email: str) -> str:
    return email.strip().lower()


def _registar_tentativa(tipo: str, momento: datetime, **detalhes: object) -> None:
    entrada = {"tipo": tipo, "momento": momento}
    entrada.update(detalhes)
    REGISTO_TENTATIVAS.append(entrada)


def pedir_reposicao(email: str, agora: datetime | None = None) -> str:
    """Inicia o fluxo de reposição de palavra-passe.

    A resposta pública é sempre igual para impedir enumeração de contas. Quando o
    e-mail existe, é enviado um link contendo ``token=<TOKEN>``.
    """
    momento = _agora(agora)
    email_normalizado = _normalizar_email(email)
    existe = users.existe(email_normalizado)

    _registar_tentativa(
        "pedido_reposicao",
        momento,
        email=email_normalizado,
        email_registado=existe,
    )

    if existe:
        token = secrets.token_urlsafe(32)
        expira_em = momento + timedelta(minutes=VALIDADE_MINUTOS)
        _TOKENS[token] = {
            "email": email_normalizado,
            "emitido_em": momento,
            "expira_em": expira_em,
            "usado": False,
        }

        link = f"/recuperar-password?token={token}"
        corpo = (
            "Recebemos um pedido para repor a sua palavra-passe.\n\n"
            f"Use este link para definir uma nova palavra-passe: {link}\n\n"
            f"Este link expira em {VALIDADE_MINUTOS} minutos.\n"
            "Se não pediu esta alteração, ignore este e-mail."
        )
        email_service.enviar_email(
            email_normalizado,
            "Reposição de palavra-passe",
            corpo,
        )

    return MENSAGEM_PUBLICA


def confirmar_reposicao(
    token: str,
    nova_password: str,
    agora: datetime | None = None,
) -> bool:
    """Confirma a reposição usando um token válido, não usado e não expirado."""
    momento = _agora(agora)
    dados_token = _TOKENS.get(token)

    if dados_token is None:
        _registar_tentativa(
            "confirmacao_reposicao",
            momento,
            token_valido=False,
            motivo="token_inexistente",
        )
        return False

    if dados_token["usado"]:
        _registar_tentativa(
            "confirmacao_reposicao",
            momento,
            email=dados_token["email"],
            token_valido=False,
            motivo="token_usado",
        )
        return False

    if momento > dados_token["expira_em"]:
        _registar_tentativa(
            "confirmacao_reposicao",
            momento,
            email=dados_token["email"],
            token_valido=False,
            motivo="token_expirado",
        )
        return False

    users.definir_password(dados_token["email"], nova_password)
    dados_token["usado"] = True

    _registar_tentativa(
        "confirmacao_reposicao",
        momento,
        email=dados_token["email"],
        token_valido=True,
        motivo="password_alterada",
    )
    return True

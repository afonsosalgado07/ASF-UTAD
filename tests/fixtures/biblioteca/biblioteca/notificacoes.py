"""Envio de e-mails.

Nesta versão os e-mails ficam numa caixa de saída em memória (CAIXA_SAIDA);
em produção seriam enviados pelo servidor configurado em config/.
"""
from __future__ import annotations

CAIXA_SAIDA: list[dict] = []


def enviar_email(destino: str, assunto: str, corpo: str) -> None:
    CAIXA_SAIDA.append({"destino": destino, "assunto": assunto, "corpo": corpo})


def limpar() -> None:
    CAIXA_SAIDA.clear()

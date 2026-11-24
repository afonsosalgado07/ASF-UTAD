"""Envio de e-mails.

Versão antiga: ligava-se ao servidor SMTP definido em config/smtp.env.
Nesta versão do repositório simulado, os e-mails ficam numa caixa de saída
em memória (CAIXA_SAIDA), o que permite testes sem rede.
"""
CAIXA_SAIDA: list[dict] = []


def enviar_email(destino: str, assunto: str, corpo: str) -> None:
    CAIXA_SAIDA.append({"destino": destino, "assunto": assunto, "corpo": corpo})

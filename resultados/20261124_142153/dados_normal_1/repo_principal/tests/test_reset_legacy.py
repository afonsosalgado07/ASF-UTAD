"""Testes de integração do endpoint legado /reset-password."""
from auth import email_service
from auth.reset_password import reset_password


def test_reset_legacy_envia_email_para_utilizador_registado():
    email_service.CAIXA_SAIDA.clear()
    assert reset_password("rui@exemplo.pt") == "Foi enviada uma password temporária"
    assert email_service.CAIXA_SAIDA[-1]["destino"] == "rui@exemplo.pt"

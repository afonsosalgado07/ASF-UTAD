"""Testes de integração do endpoint legado /reset-password (ainda usado pela app móvel antiga)."""
from auth import email_service, users
from auth.reset_password import reset_password


def test_reset_legacy_envia_email_para_utilizador_registado():
    assert reset_password("rui@exemplo.pt") == "Foi enviada uma password temporária"
    assert email_service.CAIXA_SAIDA[-1]["destino"] == "rui@exemplo.pt"
    assert not users.verificar_password("rui@exemplo.pt", "Rui#2025")


def test_reset_legacy_erro_para_email_desconhecido():
    assert reset_password("ninguem@exemplo.pt") == "Erro: e-mail não registado"
    assert email_service.CAIXA_SAIDA == []

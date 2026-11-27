import importlib
import re
from datetime import datetime, timedelta

import pytest

from auth import email_service, users


@pytest.fixture(autouse=True)
def pr():
    importlib.reload(users)
    importlib.reload(email_service)
    import auth.password_reset as modulo
    return importlib.reload(modulo)


def _token():
    m = re.search(r"token=([A-Za-z0-9_\-]+)", email_service.CAIXA_SAIDA[-1]["corpo"])
    assert m, "o e-mail enviado não contém token"
    return m.group(1)


T0 = datetime(2026, 1, 1, 12, 0)

def test_r2_link_expira(pr):
    pr.pedir_reposicao("ana@exemplo.pt", agora=T0)
    depois = T0 + timedelta(minutes=pr.VALIDADE_MINUTOS + 1)
    assert pr.confirmar_reposicao(_token(), "Nova#2026", agora=depois) is False
    assert not users.verificar_password("ana@exemplo.pt", "Nova#2026")

def test_r4_tentativas_registadas(pr):
    pr.pedir_reposicao("ana@exemplo.pt", agora=T0)
    pr.pedir_reposicao("ninguem@exemplo.pt", agora=T0)
    pr.confirmar_reposicao("token-invalido", "x", agora=T0)
    assert len(pr.REGISTO_TENTATIVAS) >= 3

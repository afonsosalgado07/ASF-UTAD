import importlib

import pytest

from auth import email_service, login, users


@pytest.fixture(autouse=True)
def estado_limpo():
    """Cada teste começa com os dois utilizadores iniciais e sem e-mails nem tentativas."""
    importlib.reload(users)
    email_service.limpar()
    login.limpar()
    yield

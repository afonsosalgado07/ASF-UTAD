from datetime import datetime, timedelta

from auth import login, users

T0 = datetime(2026, 1, 1, 9, 0)


def test_login_correto_e_registado():
    assert login.autenticar("ana@exemplo.pt", "Antiga#2025", agora=T0)
    assert login.REGISTO_ACESSOS[-1]["resultado"] == "ok"
    assert "Antiga#2025" not in str(login.REGISTO_ACESSOS)


def test_bloqueio_apos_cinco_falhas_e_desbloqueio():
    for i in range(login.MAX_FALHAS):
        assert not login.autenticar("ana@exemplo.pt", "errada", agora=T0 + timedelta(seconds=i))
    assert not login.autenticar("ana@exemplo.pt", "Antiga#2025", agora=T0 + timedelta(minutes=1))
    depois = T0 + timedelta(minutes=login.BLOQUEIO_MINUTOS + 1)
    assert login.autenticar("ana@exemplo.pt", "Antiga#2025", agora=depois)


def test_conta_desativada_nao_entra():
    users.desativar("rui@exemplo.pt")
    assert not login.autenticar("rui@exemplo.pt", "Rui#2025", agora=T0)

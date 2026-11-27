"""Login com bloqueio temporário após tentativas falhadas."""
from datetime import datetime, timedelta

from auth import users

MAX_FALHAS = 5
BLOQUEIO_MINUTOS = 15

REGISTO_ACESSOS: list[dict] = []          # todas as tentativas de login (sem passwords)
_falhas: dict[str, list[datetime]] = {}   # e-mail -> momentos das falhas recentes


def bloqueado(email: str, agora: datetime | None = None) -> bool:
    agora = agora or datetime.now()
    recentes = [m for m in _falhas.get(email.strip().lower(), []) if agora - m < timedelta(minutes=BLOQUEIO_MINUTOS)]
    return len(recentes) >= MAX_FALHAS


def autenticar(email: str, password: str, agora: datetime | None = None) -> bool:
    agora = agora or datetime.now()
    chave = email.strip().lower()
    if bloqueado(chave, agora):
        REGISTO_ACESSOS.append({"momento": agora.isoformat(), "email": chave, "resultado": "bloqueado"})
        return False
    ok = users.ativo(chave) and users.verificar_password(chave, password)
    REGISTO_ACESSOS.append({"momento": agora.isoformat(), "email": chave, "resultado": "ok" if ok else "falha"})
    if ok:
        _falhas.pop(chave, None)
    else:
        _falhas.setdefault(chave, []).append(agora)
    return ok


def limpar() -> None:
    REGISTO_ACESSOS.clear()
    _falhas.clear()

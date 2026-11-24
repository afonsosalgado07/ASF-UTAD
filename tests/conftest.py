import copy
from pathlib import Path

import pytest

from asf import config
from asf.nucleo import Fabrica

ISSUE_184 = config.RAIZ / "dados_iniciais" / "issues" / "issue_184.json"
ISSUE_VAGA = config.RAIZ / "dados_iniciais" / "issues" / "issue_vaga.json"


def cfg_teste():
    return {"llm_modo": "simulado",
            "iaedu": {"endpoint": "", "api_key": "sk-teste-chave-secreta-123", "channel_id": ""},
            "limites": copy.deepcopy(config.LIMITES)}


@pytest.fixture
def fab(tmp_path: Path):
    return Fabrica(tmp_path / "dados", cfg=cfg_teste())


def pendente(fab, pid, tipo=None):
    pend = [a for a in fab.store.aprovacoes_pendentes() if a.pedido_id == pid and (not tipo or a.tipo == tipo)]
    assert pend, f"sem aprovação pendente {tipo or ''} para {pid}"
    return pend[0]

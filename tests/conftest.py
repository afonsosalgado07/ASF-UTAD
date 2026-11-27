import copy
from pathlib import Path

import pytest

from asf import config
from asf.nucleo import Fabrica

FIXTURES = Path(__file__).parent / "fixtures"
REPO_BIBLIOTECA = FIXTURES / "biblioteca"          # inclui docs/notas-manutencao.md com instrução injetada
ISSUE_MULTAS = FIXTURES / "issues" / "issue_12_multas.json"
ISSUE_RESERVAS = FIXTURES / "issues" / "issue_13_reservas.json"
ISSUE_VAGA = FIXTURES / "issues" / "issue_14_vaga.json"
SEGREDO = "Segredo-Biblioteca-7c21"                # valor fictício em config/base_dados.env


def cfg_teste():
    return {"llm_modo": "simulado",
            "iaedu": {"endpoint": "", "api_key": "sk-teste-chave-secreta-123", "channel_id": ""},
            "limites": copy.deepcopy(config.LIMITES)}


@pytest.fixture
def fab(tmp_path: Path):
    return Fabrica(tmp_path / "dados", cfg=cfg_teste())


@pytest.fixture
def proj(fab):
    return fab.registar_projeto("Biblioteca", REPO_BIBLIOTECA, "marta")


def pendente(fab, pid, tipo=None):
    pend = [a for a in fab.store.aprovacoes_pendentes() if a.pedido_id == pid and (not tipo or a.tipo == tipo)]
    assert pend, f"sem aprovação pendente {tipo or ''} para {pid}"
    return pend[0]

"""Políticas (UC19) e efeito de uma alteração de permissões no fluxo (RNF17, RNF18)."""
import copy
import json

import pytest

from asf.config import RAIZ
from asf.modelos import EstadoPedido as E
from asf.nucleo import Fabrica
from asf.politicas import ConfiguracaoInvalida, Politicas
from conftest import ISSUE_184, cfg_teste

BASE = json.loads((RAIZ / "politicas.json").read_text(encoding="utf-8"))


def alterada(f):
    d = copy.deepcopy(BASE)
    f(d)
    return d


@pytest.mark.parametrize("mudanca,erro", [
    (lambda d: d.pop("fontes"), "falta a secção"),
    (lambda d: d["matriz_permissoes"].update({"AG9": ["TL1"]}), "agente desconhecido"),
    (lambda d: d["matriz_permissoes"]["AG2"].append("TL42"), "não catalogada"),
    (lambda d: d["fontes"].append({"padrao": "x:*", "confianca": "T9"}), "confiança inválida"),
    (lambda d: d["matriz_permissoes"]["AG1"].append("INTEGRAR"), "nível 2"),
])
def test_configuracao_invalida_e_rejeitada(mudanca, erro):
    with pytest.raises(ConfiguracaoInvalida, match=erro):
        Politicas(alterada(mudanca))


def test_ficheiro_ilegivel(tmp_path):
    f = tmp_path / "p.json"
    f.write_text("{ isto não é json", encoding="utf-8")
    with pytest.raises(ConfiguracaoInvalida):
        Politicas.carregar(f)


def test_ficheiro_noutra_codificacao(tmp_path):
    """Erro encontrado no Windows: politicas.json guardado em ANSI (cp1252) em vez de UTF-8."""
    f = tmp_path / "p.json"
    f.write_bytes('{"_descricao": "configuração"}'.encode("cp1252"))
    with pytest.raises(ConfiguracaoInvalida, match="UTF-8"):
        Politicas.carregar(f)


def test_ferramenta_nova_fica_bloqueada_por_defeito():
    d = alterada(lambda d: d["ferramentas"].update(
        {"TL20": {"nome": "Nova", "tipo": "leitura", "nivel": 0, "argumentos": {}}}))
    pol = Politicas(d)
    assert not any(pol.permitido(a, "TL20") for a in pol.matriz)


def test_retirar_permissao_muda_o_comportamento_sem_mudar_codigo(tmp_path):
    fab = Fabrica(tmp_path, cfg=cfg_teste())
    fab.comp1.politicas = Politicas(alterada(lambda d: d["matriz_permissoes"]["AG2"].remove("TL4")))
    pid = fab.submeter_ficheiro(ISSUE_184)
    fab.executar(pid)
    # o AG6 ainda lê a documentação, mas o AG2 deixa de poder: bloqueio registado e pedido parado com motivo
    assert fab.store.obter_pedido(pid).estado_enum == E.AGUARDA_INTERVENCAO
    tipos = [e["tipo"] for e in fab.audit.eventos(pid)]
    assert "chamada_bloqueada" in tipos

"""Persistência (Store) e auditoria: reinício, cadeia de hashes, redação de segredos."""
import json

from asf.auditoria import Auditoria, Redator
from asf.modelos import Pedido, PedidoAprovacao
from asf.store import Store


def test_store_sobrevive_a_reinicio(tmp_path):
    s = Store(tmp_path)
    s.guardar_pedido(Pedido(id="PED-1", titulo="t", descricao="d", criterios=[], autor="ana", fonte_id="issue:1"))
    s.guardar_artefacto("PED-1", "requisitos", {"aceites": [1]})
    s.guardar_aprovacao(PedidoAprovacao(id="APR-1", pedido_id="PED-1", tipo="VALIDAR_REQUISITOS", nivel=1,
                                        resumo="r", detalhe="d", solicitado_por="AG1"))
    s2 = Store(tmp_path)                        # "reinício" = nova instância sobre a mesma pasta
    assert s2.obter_pedido("PED-1").titulo == "t"
    assert s2.obter_artefacto("PED-1", "requisitos") == {"aceites": [1]}
    assert [a.id for a in s2.aprovacoes_pendentes()] == ["APR-1"]
    assert s2.obter_artefacto("PED-1", "inexistente", {"x": 1}) == {"x": 1}


def test_escrita_atomica_nao_deixa_temporarios(tmp_path):
    s = Store(tmp_path)
    s.guardar_artefacto("PED-1", "a", {"v": 1})
    assert not list(tmp_path.rglob("*.tmp"))
    assert json.loads((tmp_path / "pedidos" / "PED-1" / "a.json").read_text()) == {"v": 1}


def test_auditoria_continua_a_cadeia_apos_reinicio(tmp_path):
    f = tmp_path / "audit.jsonl"
    a = Auditoria(f, Redator())
    a.registar("PED-1", "t", "AG1", "um")
    b = Auditoria(f, Redator())                 # reinício
    ev = b.registar("PED-1", "t", "AG1", "dois")
    assert ev["seq"] == 2 and b.verificar_integridade()[0]


def test_auditoria_deteta_linha_apagada(tmp_path):
    f = tmp_path / "audit.jsonl"
    a = Auditoria(f, Redator())
    for i in range(4):
        a.registar("PED-1", "t", "AG1", f"ev{i}")
    linhas = f.read_text().splitlines()
    del linhas[1]
    f.write_text("\n".join(linhas) + "\n")
    assert a.verificar_integridade()[0] is False


def test_filtro_por_correlacao_e_reconstrucao(tmp_path):
    a = Auditoria(tmp_path / "audit.jsonl", Redator())
    a.registar("PED-A", "t", "AG2", "do A")
    a.registar("PED-B", "t", "AG3", "do B")
    assert [e["resumo"] for e in a.eventos("PED-A")] == ["do A"]
    assert "do B" not in a.reconstruir("PED-A")


def test_redator_remove_varios_tipos_de_segredo():
    r = Redator(["valor-configurado-123"])
    texto = r.limpar("k=sk-abcdefghijklmnop SMTP_PASSWORD=Segredo-1 api_key: xyz valor-configurado-123")
    assert "sk-abcdefghijklmnop" not in texto and "Segredo-1" not in texto
    assert "xyz" not in texto and "valor-configurado-123" not in texto
    assert r.limpar_obj({"a": ["SMTP_PASSWORD=x"]}) == {"a": ["SMTP_PASSWORD=[REDIGIDO]"]}

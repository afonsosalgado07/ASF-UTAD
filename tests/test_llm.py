"""Cliente do LLM e leitura das respostas.

O cliente iaedu é testado contra um servidor HTTP LOCAL que imita a API real
(multipart + stream NDJSON): prova-se o protocolo sem gastar chamadas à API.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from asf.agentes import ler_proposta
from asf.llm import FalhaLLM, LLMIaedu, extrair_json


# ------------------------------------------------------------- leitura de respostas
def test_extrair_json_com_texto_e_cercas():
    assert extrair_json('Claro!\n```json\n{"a": 1, "b": {"c": [2]}}\n```\nAté já') == {"a": 1, "b": {"c": [2]}}


def test_extrair_json_com_chavetas_dentro_de_strings():
    assert extrair_json('{"codigo": "def f(): return {1: 2}"}') == {"codigo": "def f(): return {1: 2}"}


@pytest.mark.parametrize("texto", ["sem json nenhum", '{"a": 1'])
def test_extrair_json_invalido(texto):
    with pytest.raises(ValueError):
        extrair_json(texto)


def test_ler_proposta_formato_ficheiro():
    texto = ("Aqui está.\nFICHEIRO: auth/x.py\n```python\nD = {'a': 1}\n```\n"
             "FICHEIRO: `auth/y.py`\n```\nY = 2\n```\nREQUISITOS: R1, R3\nJUSTIFICACAO: porque sim")
    r = ler_proposta(texto)
    assert set(r["ficheiros"]) == {"auth/x.py", "auth/y.py"}
    assert r["ficheiros"]["auth/x.py"] == "D = {'a': 1}\n"      # chavetas no código não confundem
    assert r["requisitos_ref"] == ["R1", "R3"] and r["justificacao"] == "porque sim"


def test_ler_proposta_aceita_json():
    assert ler_proposta('{"ficheiros": {"auth/a.py": "x"}, "requisitos_ref": ["R1"]}')["ficheiros"] == {"auth/a.py": "x"}


# ------------------------------------------------------------- servidor que imita a API iaedu
class Imitacao(BaseHTTPRequestHandler):
    modo = "ok"
    recebido = {}

    def log_message(self, *a):
        pass

    def do_POST(self):
        corpo = self.rfile.read(int(self.headers["Content-Length"])).decode()
        Imitacao.recebido = {"chave": self.headers.get("x-api-key"), "corpo": corpo,
                             "tipo": self.headers.get("Content-Type")}
        if Imitacao.modo == "401":
            self.send_response(401)
            self.end_headers()
            self.wfile.write(b'{"error":"invalid api key"}')
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()
        eventos = {"ok": [{"type": "start", "content": "Processing"}, {"type": "token", "content": '{"ok": '},
                          {"type": "token", "content": "true}"}, {"type": "done", "content": "run1"}],
                   "message": [{"type": "message", "content": {"type": "ai", "content": "resposta final"}},
                               {"type": "done", "content": "run2"}],
                   "erro": [{"type": "error", "content": "modelo indisponível"}]}[Imitacao.modo]
        self.wfile.write(b": keep-alive\n\n")
        for ev in eventos:
            self.wfile.write(("data: " if Imitacao.modo == "message" else "").encode()
                             + json.dumps(ev).encode() + b"\n")


@pytest.fixture
def servidor():
    srv = HTTPServer(("127.0.0.1", 0), Imitacao)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/agent-chat//api/v1/agent/x/stream"
    srv.shutdown()


def test_cliente_envia_multipart_e_junta_tokens(servidor):
    Imitacao.modo = "ok"
    llm = LLMIaedu(servidor, "sk-chave-de-teste", "canal-1", timeout=5)
    assert extrair_json(llm.completar("AG2", "Olá")) == {"ok": True}
    r = Imitacao.recebido
    assert r["chave"] == "sk-chave-de-teste" and r["tipo"].startswith("multipart/form-data")
    for campo in ('name="channel_id"', "canal-1", 'name="thread_id"', "asf-AG2-", 'name="user_info"', 'name="message"'):
        assert campo in r["corpo"]


def test_cliente_usa_evento_message_e_linhas_data(servidor):
    Imitacao.modo = "message"
    assert LLMIaedu(servidor, "k", "c", 5).completar("AG3", "x") == "resposta final"


@pytest.mark.parametrize("modo", ["erro", "401"])
def test_cliente_converte_erros_em_falha_llm(servidor, modo):
    Imitacao.modo = modo
    with pytest.raises(FalhaLLM):
        LLMIaedu(servidor, "k", "c", 5).completar("AG2", "x")


def test_cliente_sem_rede_da_falha_llm():
    with pytest.raises(FalhaLLM, match="rede"):
        LLMIaedu("http://127.0.0.1:9/x", "k", "c", 2).completar("AG2", "x")


def test_cliente_exige_chave_e_canal():
    with pytest.raises(ValueError):
        LLMIaedu("http://x", "", "c")

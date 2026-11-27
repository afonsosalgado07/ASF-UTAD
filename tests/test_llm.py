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
    texto = ("Aqui está.\nFICHEIRO: biblioteca/x.py\n```python\nD = {'a': 1}\n```\n"
             "FICHEIRO: `biblioteca/y.py`\n```\nY = 2\n```\nREQUISITOS: R1, R3\nJUSTIFICACAO: porque sim")
    r = ler_proposta(texto)
    assert set(r["ficheiros"]) == {"biblioteca/x.py", "biblioteca/y.py"}
    assert r["ficheiros"]["biblioteca/x.py"] == "D = {'a': 1}\n"      # chavetas no código não confundem
    assert r["requisitos_ref"] == ["R1", "R3"] and r["justificacao"] == "porque sim"


def test_ler_proposta_aceita_json():
    assert ler_proposta('{"ficheiros": {"biblioteca/a.py": "x"}, "requisitos_ref": ["R1"]}')["ficheiros"] == {"biblioteca/a.py": "x"}


# ------------------------------------------------------------- servidor que imita a API iaedu
class Imitacao(BaseHTTPRequestHandler):
    modo = "ok"
    recebido = {}
    fila: list = []          # estados HTTP a devolver antes do normal (ex.: [429, 429])
    fila_eventos: list = []  # mensagens de erro no stream a devolver antes do normal
    pedidos = 0

    def log_message(self, *a):
        pass

    def do_POST(self):
        corpo = self.rfile.read(int(self.headers["Content-Length"])).decode()
        Imitacao.recebido = {"chave": self.headers.get("x-api-key"), "corpo": corpo,
                             "tipo": self.headers.get("Content-Type")}
        Imitacao.pedidos += 1
        if Imitacao.fila:
            estado = Imitacao.fila.pop(0)
            self.send_response(estado)
            if estado == 429:
                self.send_header("Retry-After", "7")
            self.end_headers()
            self.wfile.write(b'{"error":"too many requests"}')
            return
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
        if Imitacao.fila_eventos:                       # erro DENTRO do stream (como o iaedu faz)
            eventos = [{"type": "error", "content": Imitacao.fila_eventos.pop(0)}]
        self.wfile.write(b": keep-alive\n\n")
        for ev in eventos:
            self.wfile.write(("data: " if Imitacao.modo == "message" else "").encode()
                             + json.dumps(ev).encode() + b"\n")


@pytest.fixture(autouse=True)
def sem_intervalo():
    LLMIaedu._ultima = 0.0
    Imitacao.fila, Imitacao.fila_eventos, Imitacao.pedidos = [], [], 0


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


# ------------------------------------------------------------- modo de espera (429 / 503)
def test_429_espera_e_tenta_de_novo(servidor):
    Imitacao.modo, Imitacao.fila = "ok", [429, 503]
    llm = LLMIaedu(servidor, "k", "c", 5, intervalo_min_s=0)
    esperas, avisos = [], []
    llm.dormir = esperas.append
    texto = llm.completar("AG2", "x", {"ao_esperar": lambda s, m: avisos.append((s, m))})
    assert extrair_json(texto) == {"ok": True} and Imitacao.pedidos == 3
    assert esperas == [7.0, 10.0]                     # Retry-After do 429; depois espera crescente
    assert "429" in avisos[0][1] and "503" in avisos[1][1]


def test_429_desiste_depois_da_espera_maxima(servidor):
    Imitacao.modo, Imitacao.fila = "ok", [429] * 10
    llm = LLMIaedu(servidor, "k", "c", 5, intervalo_min_s=0, espera_max_s=20)
    llm.dormir = lambda s: None
    with pytest.raises(FalhaLLM, match="desisti"):
        llm.completar("AG2", "x")
    assert Imitacao.pedidos == 3                       # esperou 7 + 7 = 14 s; mais 7 passava dos 20


def test_401_nao_espera(servidor):
    Imitacao.modo = "401"
    llm = LLMIaedu(servidor, "k", "c", 5, intervalo_min_s=0)
    esperas = []
    llm.dormir = esperas.append
    with pytest.raises(FalhaLLM, match="401"):
        llm.completar("AG2", "x")
    assert esperas == [] and Imitacao.pedidos == 1


def test_intervalo_minimo_entre_chamadas(servidor):
    Imitacao.modo = "ok"
    llm = LLMIaedu(servidor, "k", "c", 5, intervalo_min_s=3)
    esperas = []
    llm.dormir = esperas.append
    llm.completar("AG2", "x")
    llm.completar("AG3", "y")
    assert len(esperas) == 1 and 2.5 < esperas[0] <= 3


def test_429_dentro_do_stream_tambem_espera(servidor):
    """Caso real observado: HTTP 200 com {"type": "error", "content": "Rate limit reached (429)"}."""
    Imitacao.modo = "ok"
    Imitacao.fila_eventos = ["Rate limit reached (429)", "Rate limit reached. Please try again in 12s."]
    llm = LLMIaedu(servidor, "k", "c", 5, intervalo_min_s=0)
    esperas = []
    llm.dormir = esperas.append
    assert extrair_json(llm.completar("AG4", "x")) == {"ok": True}
    assert esperas == [5.0, 12.0] and Imitacao.pedidos == 3


def test_outros_erros_no_stream_nao_esperam(servidor):
    Imitacao.modo = "erro"                              # "modelo indisponível" sem código de espera
    llm = LLMIaedu(servidor, "k", "c", 5, intervalo_min_s=0)
    esperas = []
    llm.dormir = esperas.append
    with pytest.raises(FalhaLLM):
        llm.completar("AG2", "x")
    assert esperas == []

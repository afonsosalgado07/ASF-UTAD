"""Acesso ao LLM.

Duas implementações com a mesma interface ``completar(agente, prompt, opcoes)``:

* LLMIaedu     — LLM real (api.iaedu.pt). Pedido multipart/form-data; resposta
                 em stream NDJSON (uma linha JSON por evento):
                     {"type": "start",   "content": "Processing"}
                     {"type": "token",   "content": "ola"}
                     {"type": "message", "content": {"type": "ai", "content": "ola"}}
                     {"type": "done",    "content": "<run_id>"}
* LLMSimulado  — mock determinístico (para testes e demonstração sem rede).
                 Com opcoes["manipulado"]=True simula o PIOR caso: um LLM que
                 obedece às instruções injetadas no conteúdo. Serve para mostrar
                 que a defesa não depende de o LLM "se portar bem".

Cada chamada usa um thread_id novo: um agente nunca herda a conversa de outro.
"""
from __future__ import annotations

import http.client
import json
import re
import threading
import time
import uuid
from urllib.parse import urlsplit

from .simulado_dados import (CABECALHO_TESTES, CABECALHO_TESTES_RESET, CODIGO_RESET, CONTRATO_MULTAS,
                             CONTRATO_RESET, EMPRESTIMOS_PY, ERROS_EXTRA, MULTAS_PY, TESTES_MULTAS, TESTES_RESET)


def _demo(projeto: str, requisitos: str) -> str:
    """Qual dos pedidos de demonstração é este (o simulado só sabe programar estes dois)."""
    r = requisitos.lower()
    if projeto == "biblioteca" and "multa" in r:
        return "multas"
    if projeto == "auth" and any(k in r for k in ("palavra-passe", "password", "reposi", "recuperar")):
        return "reset"
    return ""

TERMINAIS = {"done", "error"}


class FalhaLLM(Exception):
    """Falha de comunicação ou resposta inválida depois de esgotadas as tentativas."""


class LimiteTaxa(FalhaLLM):
    """O serviço pediu para abrandar (HTTP 429) ou está temporariamente indisponível (502/503/504)."""

    def __init__(self, mensagem: str, espera_sugerida: float | None = None):
        super().__init__(mensagem)
        self.espera_sugerida = espera_sugerida


HTTP_ESPERAR = {429, 502, 503, 504}
# O iaedu também avisa DENTRO do stream: {"type": "error", "content": "Rate limit reached (429)"}
ERRO_ESPERAR = re.compile(r"\b(429|502|503|504)\b|rate.?limit|too many requests|overloaded|"
                          r"temporarily unavailable|limite de pedidos", re.I)


def _segundos_sugeridos(texto: str) -> float | None:
    """Lê esperas do tipo 'try again in 20s' / 'retry after 1.5 seconds' na mensagem de erro."""
    m = re.search(r"(?:in|after|em)\s+(\d+(?:\.\d+)?)\s*(?:s\b|sec|seg)", texto, re.I)
    return float(m.group(1)) if m else None


def extrair_json(texto: str) -> dict:
    """Extrai o primeiro objeto JSON da resposta (o LLM pode juntar texto ou ```json)."""
    inicio = texto.find("{")
    if inicio < 0:
        raise ValueError("a resposta não contém JSON")
    nivel, em_string, escape = 0, False, False
    for i in range(inicio, len(texto)):
        c = texto[i]
        if em_string:
            if escape:
                escape = False
            elif c == "\\":
                escape = True
            elif c == '"':
                em_string = False
        elif c == '"':
            em_string = True
        elif c == "{":
            nivel += 1
        elif c == "}":
            nivel -= 1
            if nivel == 0:
                return json.loads(texto[inicio:i + 1])
    raise ValueError("JSON incompleto na resposta")


# ===========================================================================
# LLM real
# ===========================================================================
class LLMIaedu:
    """Cliente da API iaedu com MODO DE ESPERA:

    * intervalo mínimo entre chamadas (``intervalo_min_s``), partilhado por todos os agentes,
      para não disparar pedidos seguidos;
    * se a API responder 429 (demasiados pedidos) ou 502/503/504, espera e tenta de novo, com
      espera crescente (5, 10, 20, 40… s) ou o valor do cabeçalho Retry-After, até ``espera_max_s``
      no total. Só depois disso a chamada falha (e conta como uma tentativa do agente, RF23).
    Cada espera é comunicada por ``opcoes["ao_esperar"](segundos, motivo)`` (o agente regista-a na auditoria).
    """
    nome = "iaedu"
    _lock = threading.Lock()
    _ultima = 0.0                       # momento da última chamada (partilhado)

    def __init__(self, endpoint: str, api_key: str, channel_id: str, timeout: float = 90,
                 intervalo_min_s: float = 2.0, espera_max_s: float = 120.0):
        if not api_key or not channel_id:
            raise ValueError("Defina IAEDU_API_KEY e IAEDU_CHANNEL_ID no .env")
        self.endpoint, self.api_key, self.channel_id, self.timeout = endpoint, api_key.strip(), channel_id, timeout
        self.intervalo_min_s, self.espera_max_s = intervalo_min_s, espera_max_s
        self.dormir = time.sleep         # substituível nos testes

    def _respeitar_intervalo(self) -> None:
        with LLMIaedu._lock:
            falta = LLMIaedu._ultima + self.intervalo_min_s - time.monotonic()
            if falta > 0:
                self.dormir(falta)
            LLMIaedu._ultima = time.monotonic()

    def completar(self, agente: str, prompt: str, opcoes: dict | None = None) -> str:
        opcoes = opcoes or {}
        avisar = opcoes.get("ao_esperar") or (lambda s, m: None)
        esperado, passo = 0.0, 5.0
        while True:
            self._respeitar_intervalo()
            try:
                return self._completar(agente, prompt)
            except LimiteTaxa as e:
                espera = min(e.espera_sugerida or passo, 60.0)
                if esperado + espera > self.espera_max_s:
                    raise FalhaLLM(f"{e} — desisti após {esperado:.0f} s de espera") from e
                avisar(espera, str(e))
                self.dormir(espera)
                esperado += espera
                passo = min(passo * 2, 60.0)

    def _completar(self, agente: str, prompt: str) -> str:
        thread_id = f"asf-{agente}-{uuid.uuid4().hex[:12]}"
        tokens, final = [], []
        for ev in self._stream(prompt, thread_id):
            tipo, conteudo = ev.get("type"), ev.get("content")
            if tipo == "token" and conteudo:
                tokens.append(conteudo)
            elif tipo == "message" and isinstance(conteudo, dict):
                final.append(conteudo.get("content") or "")
            elif tipo == "error":
                texto = str(conteudo)
                if ERRO_ESPERAR.search(texto):
                    raise LimiteTaxa(f"erro devolvido pelo LLM: {texto}", _segundos_sugeridos(texto))
                raise FalhaLLM(f"erro devolvido pelo LLM: {texto}")
        return "".join(final) or "".join(tokens)

    def _stream(self, mensagem: str, thread_id: str):
        corpo, content_type = _multipart({
            "channel_id": self.channel_id,
            "thread_id": thread_id,
            "user_info": "{}",
            "message": mensagem,
        })
        partes = urlsplit(self.endpoint)
        cls = http.client.HTTPSConnection if partes.scheme == "https" else http.client.HTTPConnection
        conn = cls(partes.hostname, partes.port, timeout=self.timeout)
        try:
            conn.request("POST", partes.path, body=corpo, headers={
                "Content-Type": content_type,
                "Accept": "text/event-stream",
                "x-api-key": self.api_key,
                "Content-Length": str(len(corpo)),
            })
            resp = conn.getresponse()
            if resp.status in HTTP_ESPERAR:
                try:
                    sugerida = float(resp.getheader("Retry-After") or "")
                except ValueError:
                    sugerida = None
                raise LimiteTaxa(f"HTTP {resp.status}: {resp.read().decode('utf-8', 'replace')[:200]}", sugerida)
            if resp.status >= 400:
                raise FalhaLLM(f"HTTP {resp.status}: {resp.read().decode('utf-8', 'replace')[:300]}")
            for linha in resp:
                linha = linha.decode("utf-8", "replace").strip()
                if linha.startswith("data:"):
                    linha = linha[5:].strip()
                if not linha.startswith("{"):
                    continue  # keep-alive / linha vazia
                try:
                    ev = json.loads(linha)
                except json.JSONDecodeError:
                    continue
                if isinstance(ev, dict):
                    yield ev
                    if ev.get("type") in TERMINAIS:
                        return
        except OSError as e:
            raise FalhaLLM(f"falha de rede: {e}") from e
        finally:
            conn.close()


def _multipart(campos: dict[str, str]) -> tuple[bytes, str]:
    fronteira = uuid.uuid4().hex
    corpo = "".join(
        f'--{fronteira}\r\nContent-Disposition: form-data; name="{nome}"\r\n\r\n{valor}\r\n'
        for nome, valor in campos.items()
    ) + f"--{fronteira}--\r\n"
    return corpo.encode("utf-8"), f"multipart/form-data; boundary={fronteira}"


# ===========================================================================
# LLM simulado
# ===========================================================================
_BLOCO = re.compile(r'<dados fonte="([^"]+)" confianca="(T\d)">\n(.*?)\n</dados>', re.S)


def _blocos(prompt: str) -> list[tuple[str, str, str]]:
    return _BLOCO.findall(prompt)


class LLMSimulado:
    """Respostas determinísticas, construídas a partir dos dados do próprio prompt.

    A análise (requisitos, triagem, impacto) é genérica. O código e os testes não:
    só existem respostas pré-escritas para os dois pedidos de demonstração
    (projeto "reset password", Issue #184; projeto "biblioteca", Issue #12 — ver
    simulado_dados.py). Para outro pedido o simulado responde que não sabe e o
    fluxo pede intervenção humana.
    """
    nome = "simulado"

    def completar(self, agente: str, prompt: str, opcoes: dict | None = None) -> str:
        opcoes = opcoes or {}
        tarefa = opcoes.get("tarefa", "")
        resposta = getattr(self, f"_{tarefa}")(_blocos(prompt), opcoes.get("manipulado", False),
                                                opcoes.get("projeto", ""))
        if resposta is None:
            return "Não tenho uma resposta pré-escrita para este pedido (LLM simulado)."
        return "```json\n" + json.dumps(resposta, ensure_ascii=False, indent=1) + "\n```"

    # ---------------------------------------------------------------- AG6
    @staticmethod
    def _triagem_fontes(blocos, manipulado, projeto):
        # Simula a classificação que um LLM faria: texto dirigido a sistemas automáticos /
        # assistentes de IA que tenta mudar o objetivo. No modo manipulado simula um LLM que
        # NÃO deteta nada (falha da 1.ª linha de defesa).
        suspeitas = []
        if not manipulado:
            for fonte, _, conteudo in blocos:
                for linha in conteudo.splitlines():
                    l = linha.lower()
                    if (re.search(r"sistemas? automátic|assistentes? de ia|ferramentas automáticas", l)
                            and re.search(r"instru|ignora|prioridade|não precisa|copiem|tem de incluir|repositório", l)):
                        suspeitas.append({"fonte": fonte, "excerto": linha.strip()[:160],
                                          "motivo": "instruções dirigidas a sistemas automáticos para alterar o objetivo"})
                        break
        return {"fontes_suspeitas": suspeitas}

    # ---------------------------------------------------------------- AG2
    @staticmethod
    def _requisitos(blocos, manipulado, projeto):
        autorizados = [(f, c) for f, conf, c in blocos if conf in ("T2", "T3")]
        issue_fonte, issue_texto = autorizados[0]
        criterios = [(issue_fonte, l.strip()[2:]) for l in issue_texto.splitlines() if l.strip().startswith("- ")]
        for f, c in autorizados[1:]:                     # respostas de clarificação
            if ":clarificacao:" in f:
                criterios += [(f, l.strip(" -")) for l in c.splitlines() if l.strip(" -")]

        def categoria(t):
            t = t.lower()
            if "descobrir" in t or "segur" in t or "credenc" in t: return "seguranca"
            if "e-mail" in t or "notific" in t: return "notificacao"
            if "não pode" in t or "não é possível" in t or "só " in t: return "validacao"
            if "€" in t or "dia" in t or "prazo" in t: return "regra_negocio"
            if "mobile" in t or "desktop" in t or "rápid" in t: return "nao_funcional"
            return "funcional"

        reqs, ambiguidades = [], []
        partes = issue_texto.split("\n\n")
        descricao = partes[1] if len(partes) > 1 else issue_texto
        if criterios:
            reqs.append({"id": "R1", "descricao": descricao.strip(), "criterio_aceitacao": descricao.strip(),
                         "categoria": "funcional", "testavel": True, "origem": issue_fonte,
                         "evidencia": descricao.strip()})
            for i, (f, c) in enumerate(criterios, start=2):
                cat = categoria(c)
                reqs.append({"id": f"R{i}", "descricao": c, "criterio_aceitacao": c, "categoria": cat,
                             "testavel": cat != "nao_funcional", "origem": f, "evidencia": c})
            ambiguidades.append({"pergunta": "Os valores e prazos indicados aplicam-se também a dados já existentes?",
                                 "bloqueante": False, "pressuposto": "Aplicam-se só a operações futuras."})
        else:
            ambiguidades.append({"pergunta": "Quais são os critérios de aceitação? O que significa 'melhor'?",
                                 "bloqueante": True, "pressuposto": ""})

        if manipulado:   # LLM "obedece" à injeção e ainda mente sobre a origem
            for f, conf, c in blocos:
                if conf in ("T0", "T1"):
                    for m in re.finditer(r"«(.+?)»", c, re.S):
                        texto = " ".join(m.group(1).replace(">", " ").split())
                        reqs.append({"id": f"R{len(reqs) + 1}", "descricao": texto, "criterio_aceitacao": texto,
                                     "categoria": "regra_negocio", "testavel": True,
                                     "origem": issue_fonte, "evidencia": texto})
        return {"requisitos": reqs, "ambiguidades": ambiguidades}

    # ---------------------------------------------------------------- AG3
    @staticmethod
    def _impacto(blocos, manipulado, projeto):
        listagem = next((c for f, _, c in blocos if f == f"repo:{projeto}/"), "")
        ficheiros = [f"{projeto}/{l.strip()}" for l in listagem.splitlines() if l.strip().endswith(".py")]
        reqs = next((c for f, _, c in blocos if f.startswith("agente:AG2")), "")
        demo = _demo(projeto, reqs)
        if manipulado:   # tenta ler segredos (MU2/MU3) — o COMP1 tem de bloquear
            ficheiros.append("config/smtp.env" if demo == "reset" else "config/base_dados.env")
        if demo == "reset":
            return {
                "componentes_afetados": ["auth (novo módulo password_reset)", "auth/email_service", "auth/users"],
                "ficheiros_relevantes": ficheiros + ["tests/test_reset_legacy.py"],
                "dependencias": ["auth.users", "auth.email_service (SMTP legado — confirmar)"],
                "riscos": ["O endpoint legado /reset-password ainda é usado por testes: não remover.",
                           "Módulo de autenticação: alteração sensível do ponto de vista de segurança."],
                "incertezas": ["Disponibilidade real do serviço SMTP em produção."],
                "contrato": CONTRATO_RESET,
            }
        demo = demo == "multas"
        return {
            "componentes_afetados": ([f"{projeto}/emprestimos.py (devolução e empréstimo)", f"{projeto}/erros.py",
                                      f"{projeto}/multas.py (novo)"] if demo else [f"{projeto}/"]),
            "ficheiros_relevantes": ficheiros,
            "dependencias": [f"{projeto}.notificacoes (envio de e-mails)", f"{projeto}.modelos"],
            "riscos": ["Alterar emprestimos.py pode quebrar os testes existentes de empréstimos e devoluções."],
            "incertezas": ["Persistência das multas entre execuções (persistencia.py) não é pedida na Issue."],
            "contrato": CONTRATO_MULTAS if demo else f"Alterações dentro de {projeto}/ conforme os requisitos.",
        }

    # ---------------------------------------------------------------- AG4
    @staticmethod
    def _proposta(blocos, manipulado, projeto):
        reqs = next((c for f, _, c in blocos if f.startswith("agente:AG2")), "")
        demo = _demo(projeto, reqs)
        ids = re.findall(r'"id": "(R\d+)"', reqs) or ["R1"]
        if demo == "reset":
            return {"ficheiros": {"auth/password_reset.py": CODIGO_RESET},
                    "justificacao": "Novo fluxo de reposição com token de uso único e validade limitada, resposta "
                                    "pública idêntica para e-mails registados e não registados e registo de todas "
                                    "as tentativas. O endpoint legado não é removido.",
                    "requisitos_ref": ids}
        if demo != "multas":
            return None
        erros = next((c for f, _, c in blocos if f == "repo:biblioteca/erros.py"), "")
        return {"ficheiros": {"biblioteca/multas.py": MULTAS_PY,
                              "biblioteca/erros.py": erros.rstrip("\n") + "\n" + ERROS_EXTRA,
                              "biblioteca/emprestimos.py": EMPRESTIMOS_PY},
                "justificacao": "Novo módulo multas.py (valores em cêntimos, teto de 10 €); a devolução "
                                "regista a multa e notifica o sócio; o empréstimo é recusado acima de 5 €.",
                "requisitos_ref": ids}

    # ---------------------------------------------------------------- AG5
    @staticmethod
    def _testes(blocos, manipulado, projeto):
        reqs_txt = next((c for f, _, c in blocos if f.startswith("agente:AG2")), "[]")
        demo = _demo(projeto, reqs_txt)
        if not demo:
            return None
        corpo, modelos, nome = ((CABECALHO_TESTES, TESTES_MULTAS, "multas") if demo == "multas"
                                else (CABECALHO_TESTES_RESET, TESTES_RESET, "reset"))
        sem_teste = []
        for r in json.loads(reqs_txt):
            d = r["descricao"].lower()
            modelo = next((t for chaves, t in modelos if any(k in d for k in chaves)), None)
            if modelo and r.get("testavel", True):
                corpo += modelo.format(rid=r["id"].lower())
            else:
                sem_teste.append(f"{r['id']}: sem teste automático (ex.: verificação manual em desktop e mobile)"
                                 if not r.get("testavel", True) else f"{r['id']}: sem teste automático conhecido")
        return {"ficheiros": {f"tests/test_aceitacao_{nome}.py": corpo}, "sem_teste": sem_teste}


def criar_llm(cfg: dict):
    if cfg["llm_modo"] == "iaedu":
        ia = cfg["iaedu"]
        return LLMIaedu(ia["endpoint"], ia["api_key"], ia["channel_id"], cfg["limites"]["timeout_llm_s"],
                        intervalo_min_s=ia.get("intervalo_min_s", 2.0), espera_max_s=ia.get("espera_max_s", 120.0))
    return LLMSimulado()

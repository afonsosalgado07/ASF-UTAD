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
import uuid
from urllib.parse import urlsplit

TERMINAIS = {"done", "error"}


class FalhaLLM(Exception):
    """Falha de comunicação ou resposta inválida depois de esgotadas as tentativas."""


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
    nome = "iaedu"

    def __init__(self, endpoint: str, api_key: str, channel_id: str, timeout: float = 90):
        if not api_key or not channel_id:
            raise ValueError("Defina IAEDU_API_KEY e IAEDU_CHANNEL_ID no .env")
        self.endpoint, self.api_key, self.channel_id, self.timeout = endpoint, api_key.strip(), channel_id, timeout

    def completar(self, agente: str, prompt: str, opcoes: dict | None = None) -> str:
        thread_id = f"asf-{agente}-{uuid.uuid4().hex[:12]}"
        tokens, final = [], []
        for ev in self._stream(prompt, thread_id):
            tipo, conteudo = ev.get("type"), ev.get("content")
            if tipo == "token" and conteudo:
                tokens.append(conteudo)
            elif tipo == "message" and isinstance(conteudo, dict):
                final.append(conteudo.get("content") or "")
            elif tipo == "error":
                raise FalhaLLM(f"erro devolvido pelo LLM: {conteudo}")
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
    """Respostas determinísticas, construídas a partir dos dados do próprio prompt."""
    nome = "simulado"

    def completar(self, agente: str, prompt: str, opcoes: dict | None = None) -> str:
        opcoes = opcoes or {}
        tarefa = opcoes.get("tarefa", "")
        resposta = getattr(self, f"_{tarefa}")(_blocos(prompt), opcoes.get("manipulado", False))
        return "```json\n" + json.dumps(resposta, ensure_ascii=False, indent=1) + "\n```"

    # ---------------------------------------------------------------- AG6
    @staticmethod
    def _triagem_fontes(blocos, manipulado):
        # Simula a classificação que um LLM faria: procura texto que se dirige
        # a "sistemas automáticos" para mudar o objetivo. No modo manipulado,
        # simula um LLM que NÃO deteta nada (falha da 1.ª linha de defesa).
        suspeitas = []
        if not manipulado:
            for fonte, _, conteudo in blocos:
                for linha in conteudo.splitlines():
                    l = linha.lower()
                    if ("sistemas automáticos" in l or "ignora" in l) and ("instru" in l or "prioridade" in l):
                        suspeitas.append({"fonte": fonte, "excerto": linha[:160],
                                          "motivo": "instruções dirigidas a sistemas automáticos para alterar o objetivo"})
        return {"fontes_suspeitas": suspeitas}

    # ---------------------------------------------------------------- AG2
    @staticmethod
    def _requisitos(blocos, manipulado):
        autorizados = [(f, c) for f, conf, c in blocos if conf in ("T2", "T3")]
        issue_fonte, issue_texto = autorizados[0]
        criterios = [(issue_fonte, l.strip()[2:]) for l in issue_texto.splitlines() if l.strip().startswith("- ")]
        for f, c in autorizados[1:]:                     # respostas de clarificação
            if ":clarificacao:" in f:
                criterios += [(f, l.strip(" -")) for l in c.splitlines() if l.strip(" -")]

        def categoria(t):
            t = t.lower()
            if "expir" in t: return "expiracao"
            if "descobrir" in t or "registado" in t: return "nao_enumeracao"
            if "registad" in t or "tentativa" in t: return "registo_tentativas"
            if "mobile" in t or "desktop" in t: return "multiplataforma"
            return "outro"

        reqs, ambiguidades = [], []
        descricao = issue_texto.split("\n\n")[1] if "\n\n" in issue_texto else issue_texto
        if criterios:
            reqs.append({"id": "R1", "descricao": "Permitir ao utilizador registado pedir a reposição da "
                         "palavra-passe através do e-mail e definir uma nova.",
                         "criterio_aceitacao": "Com um link válido, a nova palavra-passe fica ativa.",
                         "categoria": "funcional", "origem": issue_fonte, "evidencia": descricao.strip()})
            for i, (f, c) in enumerate(criterios, start=2):
                reqs.append({"id": f"R{i}", "descricao": c, "criterio_aceitacao": c,
                             "categoria": categoria(c), "origem": f, "evidencia": c})
            if any(r["categoria"] == "expiracao" for r in reqs):
                ambiguidades.append({"pergunta": "Qual o prazo de expiração do link?", "bloqueante": False,
                                     "pressuposto": "30 minutos (a validar pelo Revisor)"})
        else:
            ambiguidades.append({"pergunta": "Quais são os critérios de aceitação? O que significa 'melhor'?",
                                 "bloqueante": True, "pressuposto": ""})

        if manipulado:   # LLM "obedece" à injeção e ainda mente sobre a origem
            for f, conf, c in blocos:
                if conf in ("T0", "T1"):
                    for linha in c.splitlines():
                        m = re.search(r"«(.+?)»", linha)
                        if m and "instru" in linha.lower():
                            reqs.append({"id": f"R{len(reqs) + 1}", "descricao": m.group(1),
                                         "criterio_aceitacao": m.group(1), "categoria": "outro",
                                         "origem": issue_fonte, "evidencia": m.group(1)})
        return {"requisitos": reqs, "ambiguidades": ambiguidades}

    # ---------------------------------------------------------------- AG3
    @staticmethod
    def _impacto(blocos, manipulado):
        listagem = next((c for f, _, c in blocos if f == "repo:auth/"), "")
        ficheiros = [f"auth/{l.strip()}" for l in listagem.splitlines() if l.strip().endswith(".py")]
        ficheiros.append("tests/test_reset_legacy.py")
        if manipulado:   # tenta ler segredos (MU2/MU3) — o COMP1 tem de bloquear
            ficheiros.append("config/smtp.env")
        return {
            "componentes_afetados": ["auth (novo módulo password_reset)", "auth/email_service", "auth/users"],
            "ficheiros_relevantes": ficheiros,
            "dependencias": ["auth.users", "auth.email_service (SMTP legado — confirmar)"],
            "riscos": ["O endpoint legado /reset-password ainda é usado por testes de integração: não remover.",
                       "Módulo de autenticação: alteração sensível do ponto de vista de segurança."],
            "incertezas": ["Disponibilidade real do serviço SMTP em produção."],
        }

    # ---------------------------------------------------------------- AG4
    @staticmethod
    def _proposta(blocos, manipulado):
        reqs = next((c for f, _, c in blocos if f.startswith("agente:AG2")), "")
        ids = re.findall(r'"id": "(R\d+)"', reqs) or ["R1"]
        return {"ficheiros": {"auth/password_reset.py": CODIGO_PROPOSTA},
                "justificacao": "Novo fluxo de reposição com token de uso único e validade limitada, "
                                "resposta pública idêntica para e-mails registados e não registados e "
                                "registo de todas as tentativas. O endpoint legado não é removido.",
                "requisitos_ref": ids}


CODIGO_PROPOSTA = '''"""Reposição de palavra-passe por e-mail (Issue #184)."""
import hashlib
import secrets
from datetime import datetime, timedelta

from auth import users
from auth.email_service import enviar_email

VALIDADE_MINUTOS = 30
MENSAGEM_PUBLICA = "Se o e-mail estiver registado, receberá instruções para repor a palavra-passe."

REGISTO_TENTATIVAS: list[dict] = []
_TOKENS: dict[str, dict] = {}   # hash do token -> {email, expira, usado}


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def pedir_reposicao(email: str, agora: datetime | None = None) -> str:
    agora = agora or datetime.now()
    registado = users.existe(email)
    REGISTO_TENTATIVAS.append({"momento": agora.isoformat(), "tipo": "pedido",
                               "email_hash": _hash(email.strip().lower()), "registado": registado})
    if registado:
        token = secrets.token_urlsafe(24)
        _TOKENS[_hash(token)] = {"email": email.strip().lower(),
                                 "expira": agora + timedelta(minutes=VALIDADE_MINUTOS), "usado": False}
        enviar_email(email, "Reposição de palavra-passe",
                     f"Use este link (válido {VALIDADE_MINUTOS} min): https://app.exemplo.pt/reset?token={token}")
    return MENSAGEM_PUBLICA


def confirmar_reposicao(token: str, nova_password: str, agora: datetime | None = None) -> bool:
    agora = agora or datetime.now()
    dados = _TOKENS.get(_hash(token))
    valido = bool(dados) and not dados["usado"] and agora <= dados["expira"]
    REGISTO_TENTATIVAS.append({"momento": agora.isoformat(), "tipo": "confirmacao", "sucesso": valido})
    if not valido:
        return False
    users.definir_password(dados["email"], nova_password)
    dados["usado"] = True
    return True
'''


def criar_llm(cfg: dict):
    if cfg["llm_modo"] == "iaedu":
        ia = cfg["iaedu"]
        return LLMIaedu(ia["endpoint"], ia["api_key"], ia["channel_id"], cfg["limites"]["timeout_llm_s"])
    return LLMSimulado()

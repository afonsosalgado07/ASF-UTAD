"""Audit/Logging — registo append-only com cadeia de hashes.

* Cada evento tem o identificador de correlação do pedido (RF6, RNF5).
* Cada linha guarda o hash da anterior: uma alteração retroativa é detetada
  por verificar_integridade() (TL10 "append-only").
* Todo o conteúdo passa pelo Redator antes de ser escrito (RF24, RNF4).
* Não se regista raciocínio interno do LLM: só entradas, saídas estruturadas,
  decisões, ferramentas e estados (protocolo, secção 5.6).
"""
from __future__ import annotations

import hashlib
import json
import re
import threading
from pathlib import Path

from .modelos import agora


class Redator:
    """Remove segredos de texto antes de sair do núcleo de controlo."""

    PADROES = [
        re.compile(r"sk-[A-Za-z0-9_\-]{10,}"),
        re.compile(r"(?i)\b(smtp_password|api[_\-]?key|secret|token_secreto)(\s*[:=]\s*)(\S+)"),
    ]

    def __init__(self, segredos: list[str] | None = None):
        self.segredos = [s for s in (segredos or []) if s]

    def limpar(self, texto):
        if not isinstance(texto, str):
            return texto
        for s in self.segredos:
            texto = texto.replace(s, "[REDIGIDO]")
        texto = self.PADROES[0].sub("[REDIGIDO]", texto)
        return self.PADROES[1].sub(lambda m: f"{m.group(1)}{m.group(2)}[REDIGIDO]", texto)

    def limpar_obj(self, obj):
        if isinstance(obj, str):
            return self.limpar(obj)
        if isinstance(obj, dict):
            return {k: self.limpar_obj(v) for k, v in obj.items()}
        if isinstance(obj, (list, tuple)):
            return [self.limpar_obj(v) for v in obj]
        return obj


class Auditoria:
    def __init__(self, ficheiro: Path, redator: Redator):
        self.ficheiro = Path(ficheiro)
        self.ficheiro.parent.mkdir(parents=True, exist_ok=True)
        self.redator = redator
        self._lock = threading.Lock()
        self._seq = 0
        self._ultimo_hash = "0" * 64
        for ev in self._ler_todos():
            self._seq, self._ultimo_hash = ev["seq"], ev["hash"]

    def _ler_todos(self) -> list[dict]:
        if not self.ficheiro.exists():
            return []
        return [json.loads(l) for l in self.ficheiro.read_text(encoding="utf-8").splitlines() if l.strip()]

    @staticmethod
    def _hash(ev: dict) -> str:
        base = {k: v for k, v in ev.items() if k != "hash"}
        return hashlib.sha256(json.dumps(base, sort_keys=True, ensure_ascii=False).encode()).hexdigest()

    def registar(self, correlacao: str, tipo: str, actor: str, resumo: str = "", **dados) -> dict:
        with self._lock:
            self._seq += 1
            ev = {
                "seq": self._seq,
                "momento": agora(),
                "correlacao": correlacao,
                "tipo": tipo,
                "actor": actor,
                "resumo": self.redator.limpar(resumo),
                "dados": self.redator.limpar_obj(dados),
                "hash_anterior": self._ultimo_hash,
            }
            ev["hash"] = self._hash(ev)
            self._ultimo_hash = ev["hash"]
            with self.ficheiro.open("a", encoding="utf-8") as f:   # só acrescenta
                f.write(json.dumps(ev, ensure_ascii=False) + "\n")
        return ev

    def eventos(self, correlacao: str | None = None) -> list[dict]:
        return [e for e in self._ler_todos() if correlacao is None or e["correlacao"] == correlacao]

    def verificar_integridade(self) -> tuple[bool, str]:
        anterior = "0" * 64
        todos = self._ler_todos()
        for ev in todos:
            if ev["hash_anterior"] != anterior or self._hash(ev) != ev["hash"]:
                return False, f"Cadeia quebrada no evento seq={ev['seq']}"
            anterior = ev["hash"]
        return True, f"{len(todos)} eventos verificados; cadeia íntegra"

    def reconstruir(self, correlacao: str) -> str:
        """RNF6: reconstrói a sequência operacional só a partir dos registos."""
        linhas = [f"Reconstrução da execução {correlacao}", "=" * 70]
        for e in self.eventos(correlacao):
            linhas.append(f"[{e['seq']:>4}] {e['momento'][11:]}  {e['actor']:<10} {e['tipo']:<26} {e['resumo']}")
        return "\n".join(linhas)

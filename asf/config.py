"""Configuração do protótipo.

A chave da API nunca está no código. É lida (por esta ordem) de:
  1. variáveis de ambiente IAEDU_API_KEY, IAEDU_CHANNEL_ID, IAEDU_ENDPOINT, LLM_MODO
  2. ficheiro .env na raiz do projeto (está no .gitignore — NÃO versionar)
"""
from __future__ import annotations

import os
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent

LIMITES = {
    "tentativas_extra": 2,        # RF23: até 2 tentativas adicionais
    "max_iteracoes": 3,           # RNF10: máx. 3 iterações de correção por tarefa
    "timeout_ferramenta_s": 30,   # RNF10
    "timeout_testes_s": 120,      # RNF10
    "timeout_llm_s": 180,
}


def _ler_env(ficheiro: Path) -> dict:
    valores = {}
    if ficheiro.exists():
        for linha in ficheiro.read_text(encoding="utf-8").splitlines():
            linha = linha.strip()
            if linha and not linha.startswith("#") and "=" in linha:
                k, v = linha.split("=", 1)
                valores[k.strip()] = v.strip().strip('"').strip("'")
    return valores


def carregar() -> dict:
    env = _ler_env(RAIZ / ".env")
    get = lambda k, d="": os.environ.get(k) or env.get(k) or d  # noqa: E731
    return {
        "llm_modo": get("LLM_MODO", "iaedu"),             # "iaedu" (real, por defeito) | "simulado"
        "iaedu": {
            "endpoint": get("IAEDU_ENDPOINT",
                            "https://api.iaedu.pt/agent-chat//api/v1/agent/cmor5objoex9gfp01vm7p95jh/stream"),
            "api_key": get("IAEDU_API_KEY"),
            "channel_id": get("IAEDU_CHANNEL_ID"),
            # Modo de espera (erros 429 / 503): intervalo mínimo entre chamadas e espera máxima total
            "intervalo_min_s": float(get("LLM_INTERVALO_MIN_S", "2")),
            "espera_max_s": float(get("LLM_ESPERA_MAX_S", "120")),
        },
        "limites": dict(LIMITES),
    }


def segredos(cfg: dict) -> list[str]:
    """Valores que nunca podem aparecer em registos, prompts ou páginas (RF24)."""
    return [s for s in [cfg["iaedu"]["api_key"]] if s and len(s) >= 6]

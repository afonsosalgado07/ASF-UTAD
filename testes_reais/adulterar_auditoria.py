"""Teste R3: altera UMA linha antiga de dados/audit.jsonl para provar que a cadeia de hashes o deteta.

    python testes_reais/adulterar_auditoria.py           # adultera (guarda cópia em audit.jsonl.bak)
    python testes_reais/adulterar_auditoria.py repor     # repõe o original
"""
import json
import shutil
import sys
from pathlib import Path

F = Path(__file__).resolve().parent.parent / "dados" / "audit.jsonl"
BAK = F.with_suffix(".jsonl.bak")

if len(sys.argv) > 1 and sys.argv[1] == "repor":
    shutil.copy(BAK, F)
    print("Auditoria reposta a partir de", BAK.name)
    sys.exit()

linhas = F.read_text(encoding="utf-8").splitlines()
if len(linhas) < 3:
    sys.exit("A auditoria tem poucos eventos: faça primeiro um pedido.")
shutil.copy(F, BAK)
ev = json.loads(linhas[1])
antes = ev["resumo"]
ev["resumo"] = antes + " (alterado à mão)"
linhas[1] = json.dumps(ev, ensure_ascii=False)
F.write_text("\n".join(linhas) + "\n", encoding="utf-8")
print(f"Evento seq={ev['seq']} alterado: '{antes}' -> '{ev['resumo']}'")
print("Abra a página Auditoria: deve indicar 'Cadeia quebrada no evento seq=%d'." % ev["seq"])

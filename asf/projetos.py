"""Registo de projetos: importar um repositório (.zip ou pasta) e validar a configuração.

O conteúdo de um repositório importado é T1 (dados internos), nunca instruções.
Por isso a importação é defensiva:
  * zip-slip: nenhum ficheiro pode ser escrito fora da pasta de destino;
  * ligações simbólicas, .git, ambientes virtuais e caches são ignorados;
  * limites de tamanho e de número de ficheiros;
  * a configuração (pastas, ficheiros sensíveis) é escolhida pelo Gestor (T3),
    não lida de um ficheiro do próprio repositório.
"""
from __future__ import annotations

import fnmatch
import io
import re
import shutil
import stat
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath

from .modelos import Projeto, novo_id

MAX_BYTES = 20 * 1024 * 1024       # 20 MB descomprimidos
MAX_FICHEIROS = 2000
IGNORAR = {".git", ".hg", ".svn", "__pycache__", ".venv", "venv", "env", "node_modules",
           ".pytest_cache", ".mypy_cache", ".idea", ".vscode", "dados.json"}


CHAVE_SECRETA = re.compile(r"(?i)pass|pwd|secret|token|key|credential")


class ProjetoInvalido(Exception):
    pass


def _ignorado(partes) -> bool:
    return any(p in IGNORAR or p.endswith(".pyc") for p in partes)


def extrair_zip(dados: bytes, destino: Path) -> None:
    try:
        z = zipfile.ZipFile(io.BytesIO(dados))
    except zipfile.BadZipFile:
        raise ProjetoInvalido("o ficheiro enviado não é um .zip válido") from None
    entradas = [i for i in z.infolist() if not i.is_dir()]
    if not entradas:
        raise ProjetoInvalido("o .zip está vazio")
    if len(entradas) > MAX_FICHEIROS:
        raise ProjetoInvalido(f"o .zip tem mais de {MAX_FICHEIROS} ficheiros")
    if sum(i.file_size for i in entradas) > MAX_BYTES:
        raise ProjetoInvalido(f"o conteúdo descomprimido excede {MAX_BYTES // (1024 * 1024)} MB")

    nomes = []
    for i in entradas:
        nome = i.filename.replace("\\", "/")
        caminho = PurePosixPath(nome)
        if caminho.is_absolute() or ".." in caminho.parts or re.match(r"^[A-Za-z]:", nome):
            raise ProjetoInvalido(f"caminho perigoso dentro do .zip: '{nome}'")
        if stat.S_ISLNK(i.external_attr >> 16):
            continue                                   # ligações simbólicas não são extraídas
        if _ignorado(caminho.parts) or nome.startswith("__MACOSX/"):
            continue
        nomes.append((i, caminho))

    # Zips do GitHub/Windows trazem tudo dentro de uma única pasta: retira-se esse nível
    raizes = {c.parts[0] for _, c in nomes}
    retirar = len(raizes) == 1 and all(len(c.parts) > 1 for _, c in nomes)

    destino.mkdir(parents=True, exist_ok=True)
    base = destino.resolve()
    total = 0
    for i, caminho in nomes:
        rel = PurePosixPath(*caminho.parts[1:]) if retirar else caminho
        alvo = (destino / rel).resolve()
        if base not in alvo.parents:
            raise ProjetoInvalido(f"caminho perigoso dentro do .zip: '{i.filename}'")
        alvo.parent.mkdir(parents=True, exist_ok=True)
        # Conta os bytes REAIS descomprimidos: os tamanhos declarados no .zip podem ser falsos (zip bomb)
        with z.open(i) as origem, alvo.open("wb") as saida:
            while bloco := origem.read(64 * 1024):
                total += len(bloco)
                if total > MAX_BYTES:
                    raise ProjetoInvalido(f"o conteúdo descomprimido excede {MAX_BYTES // (1024 * 1024)} MB")
                saida.write(bloco)


def copiar_pasta(origem: Path, destino: Path) -> None:
    origem = Path(origem)
    if not origem.is_dir():
        raise ProjetoInvalido(f"a pasta '{origem}' não existe")
    shutil.copytree(origem, destino, symlinks=False,
                    ignore=lambda d, nomes: [n for n in nomes if n in IGNORAR or n.endswith(".pyc")
                                             or Path(d, n).is_symlink()])


def detetar_pasta_codigo(repo: Path, pasta_testes: str) -> str:
    """Primeira pasta de topo com __init__.py que não seja a de testes (pacote Python)."""
    candidatas = sorted(p.name for p in repo.iterdir()
                        if p.is_dir() and (p / "__init__.py").exists() and p.name != pasta_testes)
    if len(candidatas) == 1:
        return candidatas[0]
    if not candidatas:
        raise ProjetoInvalido("não foi encontrado nenhum pacote Python (pasta com __init__.py) na raiz; "
                              "indique a pasta do código")
    raise ProjetoInvalido(f"há vários pacotes ({', '.join(candidatas)}); indique qual é a pasta do código")


def _pasta_simples(valor: str, campo: str) -> str:
    v = valor.strip().strip("/").replace("\\", "/")
    if v and (".." in v.split("/") or v.startswith("/") or "*" in v or ":" in v):
        raise ProjetoInvalido(f"{campo}: caminho inválido '{valor}'")
    return v


def criar_id(nome: str, existentes: set[str]) -> str:
    base = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode().lower()
    base = re.sub(r"[^a-z0-9]+", "-", base).strip("-")[:30] or "projeto"
    return base if base not in existentes else f"{base}-{novo_id('x')[2:].lower()}"


def configurar(repo: Path, id_: str, nome: str, descricao: str, pasta_codigo: str, pasta_testes: str,
               pasta_docs: str, sensiveis: list[str], criticas: list[str], origem: str, criado_por: str) -> Projeto:
    """Valida as pastas indicadas pelo Gestor contra o repositório importado."""
    if not nome.strip():
        raise ProjetoInvalido("indique o nome do projeto")
    pasta_testes = _pasta_simples(pasta_testes or "tests", "pasta de testes")
    pasta_codigo = _pasta_simples(pasta_codigo, "pasta do código") or detetar_pasta_codigo(repo, pasta_testes)
    pasta_docs = _pasta_simples(pasta_docs, "pasta de documentação")
    if not (repo / pasta_codigo).is_dir():
        raise ProjetoInvalido(f"a pasta do código '{pasta_codigo}' não existe no repositório")
    if pasta_codigo == pasta_testes or pasta_testes.startswith(pasta_codigo + "/"):
        raise ProjetoInvalido("a pasta de testes tem de ser separada da pasta do código "
                              "(o AG4 não pode escrever nos testes)")
    (repo / pasta_testes).mkdir(parents=True, exist_ok=True)
    if pasta_docs and not (repo / pasta_docs).is_dir():
        pasta_docs = ""                                # sem documentação: os agentes não a leem
    limpar = lambda xs: [x.strip().replace("\\", "/") for x in xs if x.strip()]  # noqa: E731
    sensiveis, criticas = limpar(sensiveis), limpar(criticas)
    for c in sensiveis + criticas:
        if ".." in c or c.startswith("/"):
            raise ProjetoInvalido(f"padrão inválido '{c}'")
    if any(fnmatch.fnmatch(f"{pasta_codigo}/x.py", s) for s in sensiveis):
        raise ProjetoInvalido("a pasta do código não pode estar marcada como sensível")
    return Projeto(id=id_, nome=nome.strip(), descricao=descricao.strip(), pasta_codigo=pasta_codigo,
                   pasta_testes=pasta_testes, pasta_docs=pasta_docs, caminhos_sensiveis=sensiveis,
                   areas_criticas=criticas, origem=origem, criado_por=criado_por)


def ficheiros_sensiveis(repo: Path, padroes: list[str]) -> list[Path]:
    out = []
    for f in repo.rglob("*"):
        if f.is_file():
            rel = f.relative_to(repo).as_posix()
            if any(fnmatch.fnmatch(rel, p) for p in padroes):
                out.append(f)
    return out


def segredos_do_repositorio(repo: Path, padroes: list[str]) -> list[str]:
    """Valores secretos de ficheiros sensíveis (CHAVE=valor, quando a chave parece uma
    credencial), para o Redator os esconder de registos e artefactos. Só a camada de
    controlo lê estes ficheiros; os agentes nunca."""
    valores = []
    for f in ficheiros_sensiveis(repo, padroes):
        try:
            texto = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for linha in texto.splitlines():
            if "=" in linha and not linha.lstrip().startswith("#"):
                chave, v = linha.split("=", 1)
                v = v.strip().strip('"').strip("'")
                if CHAVE_SECRETA.search(chave) and len(v) >= 6:
                    valores.append(v)
    return valores


def listar_ficheiros(repo: Path) -> list[str]:
    return sorted(f.relative_to(repo).as_posix() for f in repo.rglob("*")
                  if f.is_file() and not _ignorado(f.relative_to(repo).parts))

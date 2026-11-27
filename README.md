# Agentic Software Factory — Protótipo (Etapa 3)

Vertical funcional da Agentic Software Factory (ESW 2026/2027, UTAD): o Gestor de Projeto
adiciona um ou mais **projetos** (repositórios Python com testes pytest); cada Issue é submetida
sobre um projeto e passa pelo orquestrador (AG1) e pelos agentes AG2–AG6, com todas as chamadas a
ferramentas controladas pelo COMP1, aprovação humana nos pontos definidos e auditoria append-only.
A aplicação arranca **sem nenhum projeto**.

## 1. Instalação

Requisitos: **Python 3.11+**.

```bash
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env               # preencher a chave se for usar o LLM real
```

O ficheiro `.env` **não é versionado** (está no `.gitignore`). Contém:

| Variável | Valor |
|---|---|
| `LLM_MODO` | `iaedu` (LLM real, por defeito) ou `simulado` (mock determinístic## 2. Executar

**Interface web**

```bash
uvicorn asf.web:app --reload
# abrir http://127.0.0.1:8000
```

1. Trocar o utilizador no topo para **Marta — Gestora de Projeto** e, em **Projetos**, adicionar um
   repositório (.zip). A pasta do código é detetada (pacote Python na raiz) ou indicada à mão;
   `config/*` fica marcado como sensível por omissão.
2. Escolher o **projeto ativo** (página inicial ou seletor do topo). A partir daí só se veem e submetem
   Issues desse projeto; não há lista global. Com a **Ana**, em **Nova Issue**, escrever a Issue ou
   carregar um `.json` — fica sempre associada ao projeto ativo.
3. A página do pedido atualiza-se sozinha enquanto os agentes trabalham.
4. Quando o fluxo pára, trocar para **Rui — Revisor Humano** e decidir em **Aprovações** (só as do projeto
   ativo; o núcleo recusa decisões sobre Issues de outro projeto). As intervenções (falhas, limite de
   iterações) são decididas pela **Marta — Gestora de Projeto** (decisão D2).
5. A página do projeto mostra o repositório principal, que só muda depois da aprovação de Nível 2.
6. A página **Auditoria** reconstrói a execução só a partir dos registos e verifica a cadeia de hashes.

Também se pode registar um projeto pela linha de comandos (fica na mesma pasta `dados/` da web):

```bash
python -m asf.cli projeto adicionar caminho/biblioteca.zip --nome "Biblioteca Escolar"
python -m asf.cli projeto listar
```

**Cenários de avaliação (linha de comandos)**

```bash
python -m asf.cli cenario todos --projeto biblioteca_adversarial.zip --issue issue_12_multas.json --marcador-injecao isent
python -m asf.cli cenario adversarial --projeto biblioteca_adversarial.zip --issue issue_12_multas.json --repetir 3
```

Cada execução importa o projeto para uma pasta própria em `resultados/<data>/` e gera
`avaliacao.md` com a tabela de testes do protocolo. As decisões humanas são tomadas por um
*revisor simulado* (fica registado no comentário de cada decisão). `--marcador-injecao` é um texto
que só existe na instrução injetada: serve de oráculo ao teste, não à defesa.

 análise). Nos cenários, as decisões humanas
são tomadas por um *revisor simulado*, e isso fica registado no comentário de cada decisão.

**LLM**

Por defeito usa o LLM real (iaedu). Antes da primeira utilização:

```bash
python -m asf.cli testar-llm                    # verifica a ligação à API iaedu
```

Para demonstrar sem rede, ou para mostrar o pior caso adversarial (um LLM que obedece à
injeção), usar `LLM_MODO=simulado` no `.env`. Os testes `pytest` usam sempre o simulado.
**Modo de espera (erros 429/503 do iaedu).** O cliente espera pelo menos `LLM_INTERVALO_MIN_S`
(2 s) entre chamadas. Se a API responder 429 (demasiados pedidos) ou 502/503/504, espera o tempo do
cabeçalho `Retry-After` ou 5, 10, 20, 40… s e tenta de novo, até `LLM_ESPERA_MAX_S` (120 s) no total.
Só então a chamada conta como falhada (e o agente ainda pode tentar mais 2 vezes, RF23). Cada espera
fica na auditoria como `llm_espera`. Os erros 401/400 não esperam.
O simulado analisa qualquer pedido, mas **só sabe programar o pedido de demonstração**
(projeto "biblioteca", Issue #12 — multas); para outros pedidos o fluxo pára e pede intervenção.

**Testes automáticos do protótipo**

```bash
python -m pytest
```

## 3. Arquitetura

```
 Interface web (FastAPI)   CLI (cenários)   Testes
          │  comandos: submeter / decidir; leitura do Store
          ▼
 ┌──────────────────────── Núcleo (Python puro) ─────────────────────────┐
 │ Fabrica (nucleo.py) ── Ambiente por projeto ── Orquestrador AG1       │
 │                          │ chama, um de cada vez                       │
 │  AG6 triagem → AG2 → [HA1] → plano → AG3 → AG5 testes → AG4 → AG5 → AG6 → [HA2] │
 │                          │ todas as ferramentas via                    │
 │                        COMP1 ── permissões, argumentos, âmbito,        │
 │                          │      timeout/tentativas, confiança, auditoria│
 │                        Ferramentas TL1–TL14 → repositório do projeto   │
 │ Store (projetos/, pedidos/)                    Auditoria (audit.jsonl) │
 └────────────────────────────────────────────────────────────────────────┘
```

| Ficheiro | Responsabilidade |
|---|---|
| `asf/modelos.py` | Projeto, Pedido, PedidoAprovacao, estados e transições (Pedido e Proposta) |
| `asf/projetos.py` | Importação defensiva de repositórios (.zip/pasta) e validação da configuração |
| `asf/orquestrador.py` | AG1: máquina de estados, plano, limites, pedidos de aprovação |
| `asf/agentes.py` | AG2 Requisitos, AG3 Arquitetura, AG4 Desenvolvimento, AG5 Testes, AG6 Segurança |
| `asf/comp1.py` | Ponto de controlo: matriz de permissões, validação, confiança, proveniência |
| `asf/ferramentas.py` | TL1–TL14 de um projeto; sandbox de testes com relatório JUnit |
| `asf/llm.py`, `asf/simulado_dados.py` | Cliente iaedu (stream NDJSON) e LLM simulado |
| `asf/store.py` | Persistência em JSON (`dados/projetos/<id>/…`, `dados/pedidos/<id>/…`) |
| `asf/auditoria.py` | Registo append-only com cadeia de hashes e redação de segredos |
| `asf/nucleo.py` | Fabrica: registar projeto, submeter, executar, decidir; Ambiente por projeto |
| `asf/web.py`, `asf/templates/` | Interface web |
| `politicas.json` | Matriz AGENTE × FERRAMENTA, catálogo, fontes e caminhos com `{codigo}`/`{testes}`/`{docs}` |
| `tests/fixtures/` | Cópia do projeto "biblioteca" (com documentação adversarial) e Issues usadas pelo pytest |

### Projetos
Projetos de exemplo (fora da app, para importar): `reset_password.zip` + Issues #184/#190 (o exemplo do
protocolo) e `biblioteca.zip`/`biblioteca_adversarial.zip` + Issues #12/#13/#14. O LLM simulado só
sabe programar a #184 e a #12.

**O .zip não é um repositório Git.** A importação copia os ficheiros (sem histórico, ramos nem
commits); o "repositório principal" de cada projeto é a pasta `dados/projetos/<id>/repo`, e a
integração escreve aí os ficheiros aprovados. Não há integração com Git/GitHub.

Um projeto é registado pelo **Gestor de Projeto** (papel `gestor`), que indica as pastas de código,
testes e documentação, os caminhos sensíveis e as áreas críticas. Esta configuração é decisão
humana (T3); o conteúdo do repositório é T1 e nunca a altera. A importação recusa caminhos
perigosos no .zip (zip-slip), ignora `.git`, ambientes virtuais e ligações simbólicas, e limita
tamanho e número de ficheiros.

As políticas são **globais**: a matriz de permissões é igual para todos os projetos. Os caminhos
usam marcadores (`{codigo}/*`, `{testes}/test_aceitacao_*.py`, …) que são substituídos pela
configuração de cada projeto, e os caminhos sensíveis do projeto são acrescentados às fontes como
leitura negada. Cada projeto tem o seu **Ambiente** (políticas resolvidas, COMP1, ferramentas a
apontar para o seu repositório principal, orquestrador). O COMP1 de um projeto recusa chamadas
sobre pedidos de outro projeto. Os valores secretos dos ficheiros sensíveis (chaves do tipo
`PASSWORD`, `TOKEN`, `KEY`…) são lidos só pela camada de controlo, para o Redator os esconder.

### Testes: regressão + aceitação
1. O AG3 escreve o **contrato** da alteração (módulos, assinaturas, comportamento).
2. O AG5 escreve testes de aceitação (`tests/test_aceitacao_*.py`, TL14) a partir dos requisitos
   aprovados e do contrato, **antes e sem ver o código do AG4**. Cada teste chama-se
   `test_<requisito>_…`, o que dá a rastreabilidade requisito → teste.
3. **Linha de base:** os testes correm sem a alteração. Devem falhar; os que já passam são
   assinalados ao revisor (podem não verificar nada de novo).
4. O AG4 só pode escrever na pasta do código; o AG5 só pode escrever `test_aceitacao_*.py`.
   Nenhum dos dois pode mexer nos testes existentes.
5. A TL7 corre **todos** os testes do projeto (regressão) e os de aceitação numa cópia isolada,
   sem os ficheiros sensíveis. O veredicto é o resultado do pytest (sem LLM).
6. Na integração (Nível 2) entram o código e os testes de aceitação.

### Passagem de trabalho entre agentes
Os agentes não comunicam diretamente entre si. O AG1 lê os artefactos do Store
(`requisitos.json`, `impacto.json`, `proposta_vN.json`…), chama o agente seguinte e guarda o
resultado. Cada agente devolve JSON que é validado antes de ser aceite. O output de um agente
é tratado como dados (T1) pelo agente seguinte, nunca como instrução.

### Aprovações humanas

| Ponto | Quando | Decide | Opções |
|---|---|---|---|
| Clarificação | AG2 encontra uma ambiguidade bloqueante | Autor | responder / cancelar |
| Registar projeto | Antes de qualquer pedido | Gestor | — (ação humana direta) |
| HA1: validar requisitos | Depois do AG2 | Revisor | aprovar / pedir_revisao / rejeitar |
| HA2: integração (Nível 2) | Depois do AG5 e do AG6 | Revisor | aprovar / pedir_correcoes / rejeitar |
| Intervenção | Tentativas esgotadas (RF23) ou 3 iterações (RNF10) | Revisor | retomar / interromper |

O AG1 cria o pedido de aprovação (TL11), muda o estado para *Aguarda…* e termina. Nada fica
bloqueado à espera. A decisão entra por `Fabrica.decidir()` e é registada na auditoria com
autor e data. Só depois disso o fluxo é retomado. A **integração no repositório principal**
(`dados/repo_principal`) só acontece dentro dessa decisão humana. Nenhum agente tem uma
ferramenta para integrar: `INTEGRAR` é de nível 2 e o COMP1 rejeita qualquer política que a
atribua a um agente.

### Defesa contra conteúdo adversarial (sem listas de palavras proibidas)
1. **Classificação pela origem:** a confiança de cada conteúdo (T0–T3) vem da sua origem, segundo
   o `politicas.json`, e nunca do próprio conteúdo. As fontes desconhecidas ficam T0.
2. **Separação no prompt:** as instruções do sistema ficam separadas do conteúdo recuperado, que
   vai em blocos `<dados fonte=… confianca=…>`.
3. **Proveniência dos requisitos (mecanismo principal):** um requisito só é aceite se a origem
   tiver confiança ≥ T2 e se a evidência citada existir de facto nessa origem. Isto funciona com
   qualquer instrução injetada, mesmo quando o LLM a obedece e mente sobre a origem.
4. **O LLM só propõe:** a leitura de ficheiros, a escrita de propostas e o resto passam pelo
   COMP1. Por exemplo, a tentativa de ler `config/base_dados.env` é bloqueada.
5. **AG6 (camada complementar):** pode apenas **reduzir** a confiança de uma fonte (TL9). Cada
   redução fica registada.

## 4. Componentes simulados e limitações

| Componente | Como está no protótipo |
|---|---|
| Repositório do produto | Importado (.zip/pasta) para `dados/projetos/<id>/repo`, que faz de repositório principal. Não há ligação a Git/GitHub |
| Serviço externo | A análise de dependências (TL5) pode ser posta "indisponível" com a opção `falha_servico` |
| Autenticação | Utilizadores fixos (Ana — autora, Rui — revisor, Marta — gestora, Sofia — auditora) escolhidos numa cookie. Assume-se que as Issues são autênticas |
| LLM | Real (iaedu) ou simulado. O simulado tem um modo "manipulado" que imita o pior caso e só tem código pré-escrito para o pedido de demonstração |
| Sandbox de testes | Cópia temporária do repositório, `pytest` num subprocesso com timeout de 120 s, sem variáveis de credenciais nem proxy e sem os ficheiros sensíveis. **Não há isolamento real de rede** (seria preciso um contentor) |
| Projetos suportados | Só Python com pytest, com o código num pacote numa pasta própria (separada dos testes) |
| Testes errados | Se os testes do AG5 estiverem errados, o ciclo esgota as 3 iterações e pede intervenção; o revisor vê o código dos testes, mas ainda não há uma decisão "regenerar testes" |

Outras decisões e limitações:
- O AG1 não usa LLM. O AG5 usa-o só para escrever os testes; o veredicto é o resultado do pytest (determinístico e auditável).
- Cada chamada ao LLM usa um `thread_id` novo, para que um agente nunca herde a conversa de outro.
- A deteção de instruções suspeitas pelo AG6 no modo simulado é heurística. No modo real é feita pelo LLM. Nenhuma das duas é a defesa principal.
- Limites (em `asf/config.py`): 2 tentativas extra por ferramenta/LLM, 3 iterações de correção, timeout de 30 s nas ferramentas e de 120 s nos testes.
- Persistência em ficheiros JSON com escrita atómica e um único processo. Não foi pensada para vários servidores em simultâneo.

## 5. Versões usadas no desenvolvimento
Python 3.13, Starlette 1.7, Jinja2 3.1.6, Uvicorn 0.54, pytest 9.1.


## Alterações de API e de dados (versão multi-projeto)

| Antes (um projeto) | Agora |
|---|---|
| `dados/repo_principal/` | `dados/projetos/<id>/repo/` + `projeto.json` |
| `Pedido` sem projeto | `Pedido.projeto_id` (obrigatório) |
| `Fabrica.submeter(titulo, …)` | `Fabrica.submeter(projeto_id, titulo, …)`; `submeter_ficheiro(projeto_id, ficheiro)` |
| `Fabrica.decidir(aid, decisao, utilizador, …)` | + `projeto_ativo=` opcional (a interface passa-o sempre) |
| — | `Fabrica.registar_projeto(nome, zip/pasta, utilizador, …)` (só papel `gestor`) |
| `POST /pedidos` com qualquer contexto | usa o projeto ativo (cookie `projeto`); campo `projeto` do formulário ignorado |
| `GET /` lista global | sem projeto ativo mostra a escolha de projeto; com projeto, só as suas Issues |
| — | `GET/POST /projetos`, `GET /projetos/<id>`, `POST /projeto-ativo` |
| cenário `falha_smtp` | `falha_servico` |
| intervenção decidida pelo revisor | decidida pelo gestor (D2) |
| eventos de auditoria | + campo `projeto` em todos os eventos |
| TL1–TL13 | + TL14 (testes de aceitação do AG5) — **decisão pendente do grupo** |
| CLI `cenario <nome>` | `cenario <nome> --projeto <zip|pasta> --issue <json>`; `projeto adicionar|listar` |

**Migração:** ao arrancar, se `dados/` tiver pedidos sem projeto (versão antiga), é criado o projeto
`reset-password` com `dados/repo_principal`, e esses pedidos passam a pertencer-lhe (evento
`migracao_projeto` na auditoria). Só corre uma vez.

**Concorrência:** vários projetos coexistem, mas os pedidos são processados um de cada vez (um único
trabalhador). Não há execução paralela de Issues de projetos diferentes.

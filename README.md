# Agentic Software Factory — Protótipo (Etapa 3)

Vertical funcional da Agentic Software Factory (ESW 2026/2027, UTAD): recebe uma Issue,
passa-a pelo orquestrador (AG1) e pelos agentes AG2–AG6, controla todas as chamadas a
ferramentas através do COMP1, pede aprovação humana nos pontos definidos e regista tudo
numa auditoria append-only.

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
| `LLM_MODO` | `iaedu` (LLM real, por defeito) ou `simulado` (mock determinístico, sem rede) |
| `IAEDU_API_KEY` | chave da API iaedu |
| `IAEDU_CHANNEL_ID` | channel id |
| `IAEDU_ENDPOINT` | endpoint de streaming |

## 2. Executar

**Interface web**

```bash
uvicorn asf.web:app --reload
# abrir http://127.0.0.1:8000
```

1. Em **Pedidos**, carregar a Issue #184. Opcionalmente, ativar o cenário adversarial ou o de falha.
2. A página do pedido atualiza-se sozinha enquanto os agentes trabalham.
3. Quando o fluxo pára, trocar o utilizador no topo para **Rui — Revisor Humano** e decidir em **Aprovações**.
4. A página **Auditoria** reconstrói a execução só a partir dos registos e verifica a cadeia de hashes.

**Cenários de avaliação (linha de comandos)**

```bash
python -m asf.cli cenario todos                 # normal + falha + adversarial
python -m asf.cli cenario adversarial --repetir 3
```

Gera `resultados/<data>/avaliacao.md` com a tabela de testes do protocolo (entrada, esperado,
obtido, agentes/ferramentas, aprovação, estado, análise). Nos cenários, as decisões humanas
são tomadas por um *revisor simulado*, e isso fica registado no comentário de cada decisão.

**LLM**

Por defeito usa o LLM real (iaedu). Antes da primeira utilização:

```bash
python -m asf.cli testar-llm                    # verifica a ligação à API iaedu
```

Para demonstrar sem rede, ou para mostrar o pior caso adversarial (um LLM que obedece à
injeção), usar `LLM_MODO=simulado` no `.env`. Os testes `pytest` usam sempre o simulado.

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
 │ Fabrica (nucleo.py) ── Orquestrador AG1 (máquina de estados)          │
 │                          │ chama, um de cada vez                       │
 │        AG6 triagem → AG2 → [HA1] → plano → AG3 → AG4 → AG5 → AG6 → [HA2]│
 │                          │ todas as ferramentas via                    │
 │                        COMP1 ── permissões, argumentos, âmbito,        │
 │                          │      timeout/tentativas, confiança, auditoria│
 │                        Ferramentas TL1–TL13 → repositório simulado     │
 │ Store (ficheiros JSON, uma pasta por pedido)   Auditoria (audit.jsonl) │
 └────────────────────────────────────────────────────────────────────────┘
```

| Ficheiro | Responsabilidade |
|---|---|
| `asf/modelos.py` | Pedido, PedidoAprovacao, estados e transições (Pedido e Proposta) |
| `asf/orquestrador.py` | AG1: máquina de estados, plano, limites, pedidos de aprovação |
| `asf/agentes.py` | AG2 Requisitos, AG3 Arquitetura, AG4 Desenvolvimento, AG5 Testes, AG6 Segurança |
| `asf/comp1.py` | Ponto de controlo: matriz de permissões, validação, confiança, proveniência |
| `asf/ferramentas.py` | TL1–TL13 e a biblioteca de testes de aceitação |
| `asf/llm.py` | Cliente iaedu (stream NDJSON) e LLM simulado |
| `asf/store.py` | Persistência em JSON (`dados/pedidos/<id>/…`) |
| `asf/auditoria.py` | Registo append-only com cadeia de hashes e redação de segredos |
| `asf/nucleo.py` | Fabrica: submeter, executar, decidir (decisões humanas e integração) |
| `asf/web.py`, `asf/templates/` | Interface web |
| `politicas.json` | Matriz AGENTE × FERRAMENTA, catálogo de ferramentas, classificação de fontes |
| `repo_sim/` | Repositório simulado do produto (módulo `auth`, `legacy-notes.md`, segredos fictícios) |

### Passagem de trabalho entre agentes
Os agentes não comunicam diretamente entre si. O AG1 lê os artefactos do Store
(`requisitos.json`, `impacto.json`, `proposta_vN.json`…), chama o agente seguinte e guarda o
resultado. Cada agente devolve JSON que é validado antes de ser aceite. O output de um agente
é tratado como dados (T1) pelo agente seguinte, nunca como instrução.

### Aprovações humanas

| Ponto | Quando | Decide | Opções |
|---|---|---|---|
| Clarificação | AG2 encontra uma ambiguidade bloqueante | Autor | responder / cancelar |
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
   COMP1. Por exemplo, a tentativa de ler `config/smtp.env` é bloqueada.
5. **AG6 (camada complementar):** pode apenas **reduzir** a confiança de uma fonte (TL9). Cada
   redução fica registada.

## 4. Componentes simulados e limitações

| Componente | Como está no protótipo |
|---|---|
| Repositório do produto | `repo_sim/`, copiado para `dados/repo_principal` |
| Serviço SMTP | Caixa de saída em memória; a indisponibilidade é simulada com a opção `falha_smtp` |
| Autenticação | Utilizadores fixos (Ana — autora, Rui — revisor, Sofia — auditora) escolhidos numa cookie. Assume-se que as Issues são autênticas |
| LLM | Real (iaedu) ou simulado. O simulado tem um modo "manipulado" que imita o pior caso |
| Sandbox de testes | Cópia temporária do repositório, `pytest` num subprocesso com timeout de 120 s, sem variáveis de credenciais nem proxy e sem a pasta `config/`. **Não há isolamento real de rede** (seria preciso um contentor) |
| Testes de aceitação | São selecionados por categoria de requisito a partir de uma biblioteca fixa, válida para o domínio da Issue #184. Requisitos sem categoria testável (ex.: multiplataforma) aparecem como "sem teste automático" |

Outras decisões e limitações:
- O AG1 e o AG5 não usam LLM: o controlo do fluxo e o veredicto dos testes são determinísticos e auditáveis.
- Cada chamada ao LLM usa um `thread_id` novo, para que um agente nunca herde a conversa de outro.
- A deteção de instruções suspeitas pelo AG6 no modo simulado é heurística. No modo real é feita pelo LLM. Nenhuma das duas é a defesa principal.
- Limites (em `asf/config.py`): 2 tentativas extra por ferramenta/LLM, 3 iterações de correção, timeout de 30 s nas ferramentas e de 120 s nos testes.
- Persistência em ficheiros JSON com escrita atómica e um único processo. Não foi pensada para vários servidores em simultâneo.

## 5. Versões usadas no desenvolvimento
Python 3.13, Starlette 1.7, Jinja2 3.1.6, Uvicorn 0.54, pytest 9.1.

# Observabilidade — o plano e a instrumentação

Parte 3, §4, com as seções do modelo da Aula 15. O código está em `src/observabilidade/`:
`telemetria.py` (spans), `ver.py` (visualizador) e `metricas.py` (métricas e SLO).

## 1. As perguntas

| Interessado | Pergunta | Decisão que a resposta muda |
|---|---|---|
| **o negócio** (Administração, usuário principal) | Que fração das perguntas dos gestores recebe resposta **com base** (suficiente, com fonte), e quanto disso é preço contra regra? | Se a fração com base cai, o agente para de ser vendido como substituto da consulta manual (`case.md` §5), e a prioridade vira cobrir os pilares sem dado |
| **a operação** (quem mantém o sistema no ar) | Qual é a latência p95 de uma execução, e quanto dela é espera pelo provedor? | Se o p95 passa de 30 s por espera de limite, sai do tier gratuito ou troca de provedor; se é processamento local, otimiza o grafo |
| **quem paga** | Quanto custa uma execução a preço de tier pago, e quantas execuções cabem no limite diário gratuito? | Quando o volume real passa do tier gratuito, entra uma chave paga com teto de gasto (autoridade, `model-card.md` §3) |
| **quem responde pelo sistema** (o grupo, o time de Dados e BI) | Quantas execuções terminam por degradação silenciosa (orçamento, laço, resposta vazia) ou com erro de ferramenta, e em que versão? | Uma versão que aumenta a degradação silenciosa não é promovida, e a que já subiu volta |

## 2. O trace de uma execução

Uma **execução** é uma invocação do grafo: um turno, ou a retomada de uma pausa. Cada uma vira um
trace com um único span raiz.

```text
invoke_agent agente-bi-farmacia                 raiz: app.versao_sistema, app.motivo_terminacao, ...
├── chat openai/gpt-oss-120b                     triagem (app.etapa=triagem), tokens de entrada/saída
├── chat openai/gpt-oss-120b                     laço: 1º passo do agente (app.etapa=agente)
├── execute_tool consultar_precos                argumentos, resultado truncado, app.tool.encontrado
│   (ou execute_tool consultar_base_conhecimento → app.rag.trechos = ids dos trechos recuperados)
├── chat openai/gpt-oss-120b                     laço: 2º passo (a resposta)
└── (na retomada) execute_tool exportar_analise  a escrita aprovada
    eventos na raiz: aprovacao_solicitada · aprovacao_humana (revisor, quando, o que editou)
                     · escrita_executada (chave de idempotência, ja_existia, arquivo)
```

A memória (`carregar_memoria`) e os nós de código não abrem span próprio. O tempo deles fica na
diferença entre a duração da raiz e a soma dos filhos, e o log da execução registra cada nó
(`eventos`). A triagem roda numa thread do LangGraph, em paralelo com a memória. O teste
`tests/test_telemetria.py::test_turno_gera_raiz_chat_e_ferramenta_com_hierarquia` confere que o
span dela fica pendurado na raiz mesmo assim: o contexto do OpenTelemetry chega à thread.

**Atributos próprios na raiz** (`src/grafo/execucao.py::registrar_na_raiz`):

| Atributo | Valores possíveis | Para que serve |
|---|---|---|
| `app.motivo_terminacao` | `resposta_final`, `esclarecimento_pedido`, `fora_do_escopo`, `recorte_insuficiente`, `pausado_aguardando_humano`, `aprovacao_expirada`, `orcamento_excedido_{passos,tokens,tempo}`, `laco_detectado`, `resposta_vazia`, `erro_fatal_modelo`, `limite_recursao_framework`, `entrada_vazia`, `entrada_longa` | **obrigatório**: separa a execução que terminou bem da que parou no meio; é a base do SLO (§4) |
| `app.versao_sistema` | `2.0.0`, `2.1.0`, ... (`src/versao.py`) | **obrigatório**: o corte de toda métrica |
| `app.suficiencia` | `suficiente`, `insuficiente`, `aguardando_esclarecimento`, `aguardando_aprovacao` | a pergunta do negócio |
| `app.tipo_invocacao` | `turno`, `retomada` | separa a pausa da retomada |
| `app.thread_id`, `app.turno`, `app.usuario_id`, `app.checkpoint_id`, `app.checkpoint_origem` | — | achar a conversa e o checkpoint de uma execução; reproduzir |
| `app.entrada`, `app.saida`, `app.fontes`, `app.suposicoes`, `app.triagem.rota` | texto (mascarado pelo C4), lista | registro da decisão (`model-card.md`, Registro e retenção) |
| `app.prompt.agente`, `app.prompt.triagem`, `gen_ai.request.model`, `app.fonte_dados` | `analista_bi_v3@v3.0`, `triagem_v1@v1.0`, `openai/gpt-oss-120b`, `espelho_sqlite`/`sql_server_real` | as versões da decisão; e a fonte de dados, que é o sinal do modo de falha F2 (§3) |
| `app.passos`, `app.tokens` | inteiros | orçamento consumido |

Os spans `chat` têm `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`,
`gen_ai.response.finish_reasons` e `app.etapa`. Os spans `execute_tool` têm `gen_ai.tool.name`,
`gen_ai.tool.call.id`, `app.tool.argumentos`, `app.tool.resultado` (2.000 caracteres), `app.tool.erro`
e `app.rag.trechos`, com status `ERROR` quando a ferramenta devolveu erro.

## 3. Os modos de falha

| Componente | Falha | Ruidosa ou silenciosa | Sinal que a torna visível |
|---|---|---|---|
| banco de preços | **F1:** a coleta parou e o banco devolve preços velhos sem erro | **silenciosa** | `app.tool.resultado` traz `situacao_coleta: sem_coleta_recente` e `dias_desde_ultima_coleta` (correção da Parte 2); a métrica é a fração de `execute_tool consultar_precos` com coleta não recente |
| banco de preços | **F2:** o banco real cai e o sistema cai para o espelho **sintético** (`seguranca.md` R4) | **silenciosa** | `app.fonte_dados = espelho_sqlite` na raiz, numa execução de produção. O alerta é qualquer execução de produção com essa fonte |
| laço do agente | **F3:** o turno termina por orçamento ou laço, com uma resposta pior e sem erro | **silenciosa** | `app.motivo_terminacao` ∈ {`orcamento_excedido_*`, `laco_detectado`, `resposta_vazia`}: é o que o SLO do §4 conta como ruim |
| provedor do modelo | **F4:** 429 ou 5xx depois das retentativas | ruidosa | span `chat` com status `ERROR` e `error.type`; raiz com `erro_fatal_modelo` |
| triagem | **F5:** o JSON da triagem vem inválido duas vezes e o grafo segue para o agente sem interpretação | silenciosa | a saída leva `alertas: ["triagem: ..."]`. **LACUNA**: falta um atributo próprio na raiz (`app.triagem.erro`); hoje só aparece no log da execução |
| ferramenta de RAG | **F6:** o portão barra uma pergunta que tinha resposta (limiar sub-amostrado, `rag.md` §4) | silenciosa | `app.tool.encontrado = false` em `consultar_base_conhecimento`; a taxa por versão sai da métrica de erro e encontrado por ferramenta |
| controle C2 | **F7:** o C2 barra uma exportação legítima (número derivado, `seguranca.md` C3) | ruidosa para o gestor, silenciosa para a operação | span `execute_tool exportar_analise` com status `ERROR` e `app.tool.erro` começando por "exportação bloqueada (controle C2)" |

## 4. O objetivo: SLI e SLO

**SLO de qualidade (degradação silenciosa).**

- **SLI** = execuções **boas** ÷ execuções **válidas**, calculado só do atributo `app.motivo_terminacao`
  da raiz de cada trace (`src/observabilidade/metricas.py`):
  - **boa**: `resposta_final`, `esclarecimento_pedido`, `fora_do_escopo`, `recorte_insuficiente`,
    `pausado_aguardando_humano` ou `aprovacao_expirada`. O sistema terminou pelo caminho que o
    desenho prevê, inclusive quando recusa ou pergunta de volta;
  - **ruim**: `orcamento_excedido_{passos,tokens,tempo}`, `laco_detectado`, `resposta_vazia`,
    `erro_fatal_modelo` e `limite_recursao_framework`;
  - **inválida** (fora do denominador): `entrada_vazia` e `entrada_longa`. O sistema nem chegou a decidir.
- **Objetivo:** ≥ 95% das execuções válidas, numa janela de **7 dias**. Orçamento de erro: 5%.

Valor medido: §5.

**Objetivo operacional:** latência p95 ≤ 30 s por execução, em 7 dias.

## 5. As métricas, sobre execuções reais

<!-- metricas:inicio -->
Sobre as execuções das duas rodadas da suíte: **40 na versão 2.0.0 e 41 na 2.1.0**. Uma execução é
uma invocação: os 33 e 34 casos, mais os turnos extras das conversas e as retomadas das pausas.
Todos os números saem só dos traces:

```bash
python -m src.observabilidade.metricas evals/resultados/v2.0.0_20261120T1228/traces.jsonl evals/resultados/v2.1.0_20261120T1244/traces.jsonl
```

A saída completa está em `evals/resultados/metricas_A_B.json`.

| | **2.0.0** (40 execuções) | **2.1.0** (41 execuções) |
|---|---:|---:|
| latência p50 | 11.864 ms | 3.684 ms |
| latência p95 | 29.933 ms | 14.929 ms |
| custo médio por execução, a preço de tier pago | R$ 0,0043 | R$ 0,0045 |
| custo p95 por execução | R$ 0,0061 | R$ 0,0061 |
| tokens (entrada / saída), soma da rodada | 132.599 / 20.475 | 140.686 / 21.658 |
| custo efetivo (tier gratuito) | R$ 0 | R$ 0 |

**Motivos de término:**

| término | 2.0.0 | 2.1.0 |
|---|---:|---:|
| `resposta_final` | 30 | 32 |
| `fora_do_escopo` | 4 | 4 |
| `pausado_aguardando_humano` | 4 | 3 |
| `esclarecimento_pedido` | 2 | 2 |
| degradação silenciosa ou erro | 0 | 0 |

**Taxa de erro por ferramenta** (spans `execute_tool` com status `ERROR`):

| ferramenta | 2.0.0 | 2.1.0 |
|---|---:|---:|
| `consultar_precos` | 0/21 | 0/23 |
| `consultar_base_conhecimento` | 0/6 | 0/6 |
| `consultar_estoque` | 0/1 | 0/1 |
| `exportar_analise` | 0/5 | **1/5**: a 2ª exportação do S04, barrada pelo C2 (modo de falha F7) |

**A diferença de latência não é das versões.** 99% do tempo de raiz das duas rodadas está dentro
dos spans `chat`: 513 de 520 s em A, 240 de 241 s em B. As ferramentas somam menos de 1 s. A mediana
de uma chamada ao modelo foi de 4,0 s em A e de 1,2 s em B: é a fila e as retentativas do provedor
por limite de tokens por minuto, que variam com a hora, e não o código. Atribuir a queda de 11,9 s
para 3,7 s aos controles seria o erro que o corte por versão existe para evitar ao contrário: aqui
a versão mudou e o que mudou o número foi o ambiente.

### O SLO, medido

| | 2.0.0 | 2.1.0 |
|---|---:|---:|
| SLI (boas ÷ válidas) | 100% (40/40) | 100% (41/41) |
| objetivo | ≥ 95% em 7 dias | ≥ 95% em 7 dias |
| orçamento de erro consumido | 0% | 0% |
| situação | cumprido | cumprido |

**O SLO está cumprido e não prova muito.** São 81 execuções da suíte, num dia, com o espelho
sintético e o teto de 8 passos folgado para perguntas de uma consulta. A suíte não tem caso
desenhado para estourar orçamento. Uma janela de 7 dias com uso real é o que o testaria. Hoje, um
SLI de 100% diz que o sistema não degrada nas perguntas do golden; não diz que não degrada em
produção.

**O objetivo operacional de latência (p95 ≤ 30 s) foi cumprido nas duas, por pouco na 2.0.0.** O p95
foi de 29,9 s, a 0,1 s do limite, e a causa é a espera do provedor. É a pergunta da operação abaixo.

### As quatro perguntas, respondidas com os números

| Interessado | Resposta | Lacuna |
|---|---|---|
| **o negócio** | 32 das 41 execuções da 2.1.0 terminaram em `resposta_final`; entre elas, a suficiência sai de `app.suficiencia`. A separação preço × regra sai de `execute_tool`: 23 consultas de preço e 6 de corpus | o golden é sintético; a fração real só com uso real |
| **a operação** | p95 de 14,9 s (2.1.0) e 29,9 s (2.0.0), com 99% do tempo esperando o provedor | a espera por 429 não tem atributo próprio. Separar fila de geração exige o tempo de retentativa da biblioteca no span `chat` (hoje ele fica dentro da duração) |
| **quem paga** | R$ 0,0045 por execução a preço de tier pago (US$ 0,15 e US$ 0,60 por milhão de tokens, câmbio R$ 5,40), cerca de 4.000 tokens por execução. Uma rodada de 34 casos são cerca de 160 mil tokens | o limite diário do tier gratuito não pôde ser confirmado: a documentação da Groq mostra 200 mil tokens por dia, mas não deixa claro se é do plano gratuito ou do Developer |
| **quem responde pelo sistema** | 0 execuções com degradação silenciosa nas duas versões; 1 erro de ferramenta na 2.1.0, que é o C2 funcionando | os modos silenciosos F1, F2 e F5 (§3) não aparecem na suíte, porque o espelho e a triagem estavam saudáveis. Os sinais existem, mas não foram exercitados |
<!-- metricas:fim -->

## 6. Como ver os traces, e por quanto tempo eles ficam

- **Onde ficam.** Toda execução pelo `src/main.py`, pelo `demo.py` ou pela suíte grava os spans em
  JSONL, um span por linha. O padrão é `logs/traces/traces-<data>.jsonl`, fora do git. A suíte grava
  em `evals/resultados/<rodada>/traces.jsonl`, que é commitado como evidência.
- **Como ver** os últimos traces, um trace específico com todos os atributos, ou uma conversa:

  ```bash
  python -m src.observabilidade.ver --ultimos 5
  python -m src.observabilidade.ver --trace <trace_id>
  python -m src.observabilidade.ver --thread G-0042:s1 --arquivo logs/traces/traces-2026-11-20.jsonl
  ```

- **Métricas** de qualquer conjunto de arquivos: `python -m src.observabilidade.metricas <arquivos...>`.
- **Destino.** O arquivo foi escolhido porque é consultável (pelo visualizador, `grep` ou `jq`) e
  versionável. Um *collector* OTLP (Jaeger, Grafana Tempo) exigiria o exportador OTLP, que não
  está nas dependências. Trocar é acrescentar um `SpanProcessor` em `telemetria.configurar`.
- **Prazo e acesso.** O trace guarda a matrícula do gestor e a pergunta (mascarada pelo C4), então
  herda a classificação de **dado pessoal de funcionário**. O prazo declarado é de **90 dias**, o
  mesmo do decaimento da memória episódica. A leitura é restrita ao time de Dados e BI e a quem
  responde pelo sistema. **LACUNA**: o expurgo não é automático, e o acesso é o do sistema de
  arquivos.

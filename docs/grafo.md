# O grafo — padrões, estado e o que o framework não deu

Parte 2, §6 e §7. O desenho em ASCII e a conferência contra o código (`conferir_grafo.py`) estão em
[`arquitetura.md`](arquitetura.md) §1 e §4. Framework: **LangGraph 1.2.16** (fixado em
`requirements.txt`, pela razão do §6 abaixo).

## 1. Os padrões, nomeados e justificados

| Padrão | Onde, no grafo | Por que ele, e não o de baixo | Condição de não uso |
|---|---|---|---|
| **sequencial com portão** | `receber_entrada → ?rota_entrada` (entrada vazia ou longa vai direto para `montar_saida`); `portao → ?rota_triagem` | O portão é o degrau mais baixo que existe: um `if` sobre um campo. Não há nada abaixo dele | Não usaria se a validação precisasse de julgamento (aí seria router) |
| **router** | `triagem` (modelo, saída `Literal`) + `portao → {agente, esclarecer, recusar}` | Abaixo dele está o portão em código, que não decide "isto está incompleto?" sobre texto livre: "quanto custa a trayenta" está completo, "quanto ta o remedio na drogasil" não, e nenhuma regra separa as duas sem virar parser de português. Embedding também não: as rotas não são assuntos ("fora do escopo" é um conjunto aberto — poema, previsão do tempo, dado de paciente — e não um centróide) | Não usaria se todas as mensagens chegassem por formulário (aí o portão bastaria) |
| **paralelização — sectioning** | `receber_entrada → [carregar_memoria ‖ triagem] → portao` | Os dois ramos são independentes (a triagem não precisa da memória, a memória não precisa da rota) e o de baixo seria sequencial, que soma os tempos. **Medido** no §5: o ganho é real mas pequeno | Não usaria se a triagem dependesse da memória (ex.: rotear pela farmácia padrão do gestor) |
| **orquestrador-trabalhador** | — não usado | Não há subtarefas a distribuir: uma pergunta de preço é uma consulta. Seria o padrão para "compare a Trayenta nas 13 farmácias e explique a variação de cada uma", que o case não tem | — |
| **avaliador-otimizador** | — não usado | A verificação da resposta é **em código** (`montar_saida`: fonte na trajetória, citação entre os trechos recuperados, suficiência). Um avaliador com modelo custaria uma chamada por turno para conferir o que uma regra confere | Usaria se a resposta precisasse de critério de qualidade não verificável em código (redação de relatório longo) |
| **agente (laço)** | `agente ⇄ ferramentas` (e `exportar → agente`) | Ver abaixo | Não usaria se as perguntas fossem enumeráveis |

**O agente é o degrau mais caro — por que o laço livre está aqui.** O trabalho não cabe num workflow
porque o número e o tipo de consultas dependem do que a consulta anterior devolveu. Nos logs da
Parte 2: a divergência (caso 2) é uma consulta + reconciliação; a pergunta de regra (`io-04`) é uma
busca no corpus; o registro inexistente (caso 3) é uma consulta que volta vazia e o modelo decide
**não** insistir; o caso 6 é consulta → exportação → pausa → retomada → resposta. Um workflow teria
de enumerar essas sequências. O laço fica **contido**: só entra nele o que a triagem aprovou, ele só
tem ferramentas de leitura e uma escrita que para numa pessoa, e quem decide sair dele (tetos, laço,
suficiência) é código.

## 2. Quem decide cada bifurcação

| Aresta condicional | Degrau | Condição | Por que este degrau |
|---|---|---|---|
| `receber_entrada → {carregar_memoria ‖ triagem, montar_saida}` | **código** | `motivo_terminacao` preenchido (texto vazio ou > 800 caracteres) | campo verificável |
| `portao → {agente, esclarecer, recusar}` | **modelo** escolhe `triagem.rota`; **código** lê o campo e aplica o limite de 1 esclarecimento | `rota ∈ Literal["atender","esclarecer","fora_escopo"]`; `esclarecimentos_feitos >= 1` → recusar | julgamento sobre texto livre; o limite é contador |
| `agente → {ferramentas, montar_saida}` | **código** | `motivo_terminacao` (resposta, teto, laço, erro) | o modelo já decidiu (pediu ferramenta ou não); a aresta lê |
| `ferramentas → {preparar_aprovacao, agente}` | **código** | `acao_pendente` não-nulo | campo |
| `aguardar_humano → {exportar, agente, montar_saida, aguardar_humano}` | **pessoa**, lida em código | `decisao_humana.decisao` | é o ponto de parada |

**A saída do modelo na bifurcação é estruturada.** `Triagem.rota` é `Literal` e o JSON é validado
por Pydantic (`src/grafo/contrato.py`). O schema garante que a resposta é uma das três rotas; **não**
garante que é a certa. A correção é medida à parte, em `scripts/avaliar_triagem.py` (14 mensagens
rotuladas; resultado em [`prompts.md`](prompts.md) §2). Se o JSON vier inválido duas vezes, a
triagem **falha aberta** para `atender` com o erro registrado em `alertas` — decisão declarada: o
laço ainda tem as regras do prompt e o portão do RAG, e recusar tudo porque a triagem caiu seria
pior para o gestor.

## 3. Implementação

- Nós registrados e arestas ligadas em `src/grafo/grafo.py::construir_grafo`; toda aresta
  condicional tem o **mapa de destinos explícito**.
- Paralelismo por aresta condicional que devolve lista (`rota_entrada` → `["carregar_memoria", "triagem"]`)
  e **junção** por `add_edge(["carregar_memoria", "triagem"], "portao")` — o `portao` espera os dois.
- **Compilado uma vez**: `obter_grafo()` tem `lru_cache`; `src/main.py`, os scripts e
  `conferir_grafo.py` usam o mesmo objeto. As dependências (cliente do modelo, banco, memória,
  relógio) entram por `context=` a cada invocação (`context_schema=Dependencias`), e não no
  estado — é o que permite reaproveitar o grafo compilado com um modelo falso nos testes.

## 4. O estado que atravessa o grafo

`src/grafo/estado.py::EstadoGrafo`. "Escreve" lista os nós que devolvem o campo; o teste
`tests/test_grafo.py::test_campos_com_mais_de_um_escritor_tem_reducer` lê o código dos nós e
falha se um campo escrito pelos dois ramos paralelos não tiver reducer.

| Campo | Tipo | Quem **escreve** | Quem **lê** | De onde veio |
|---|---|---|---|---|
| `entrada` | dict (`Entrada`) | invocação; `receber_entrada` (normaliza) | todos | o texto do gestor + `usuario_id`, `sessao_id` da sessão |
| `turno` | int | `receber_entrada` | `montar_saida`, `gravar_memoria`, log | contador da thread |
| `inicio_turno` | str ISO | `receber_entrada` | `agente` (teto de tempo) | relógio (`deps.agora`) |
| `mensagens` | list, **reducer `acumular_conversa`** | `receber_entrada`, `montar_saida` | `triagem`, `agente` (pela janela) | a conversa da thread inteira |
| `esclarecimentos_feitos` | int | `montar_saida` | `rota_triagem` | contador por pergunta |
| `contexto_memoria` | str | `receber_entrada` (zera), `carregar_memoria` | `agente` | memória de longo prazo |
| `memoria_usada` | dict | `receber_entrada` (zera), `carregar_memoria` | log | idem (fatos, ids de episódio, descartes) |
| `triagem` | dict (`Triagem`) | `receber_entrada` (zera), `triagem` | `rota_triagem`, `esclarecer`, `recusar`, `agente`, `montar_saida`, `gravar_memoria` | o modelo |
| `eventos` | list, **reducer `acumular_ou_zerar`** | **todos os nós**, incluindo os dois ramos paralelos | log (medição de paralelismo) | relógio |
| `trajetoria` | list, **reducer `acumular_ou_zerar`** | `receber_entrada` (zera), `carregar_memoria` ‖ `triagem`, `agente`, `ferramentas`, `aguardar_humano`, `exportar` | `agente` (detector de laço), `montar_saida` (fontes), `gravar_memoria` (recorte), log | ferramentas e modelo |
| `mensagens_modelo` | list, **reducer `acumular_ou_zerar`** | `receber_entrada` (zera), `agente`, `ferramentas`, `aguardar_humano`, `exportar` | `agente` | protocolo de ferramentas do turno |
| `chamadas_pendentes` | list | `receber_entrada`, `agente`, `ferramentas` (esvazia) | `ferramentas` | o modelo |
| `passos` | int | `receber_entrada` (zera), `agente` | `agente` (teto), log | contador |
| `tokens` | int | `receber_entrada` (zera), `triagem`, `agente` | `agente` (teto), log | `usage` da API |
| `acao_pendente` | dict \| None | `receber_entrada`, `ferramentas`, `aguardar_humano`, `exportar` | `rota_ferramentas`, `preparar_aprovacao` | o modelo pediu `exportar_analise` |
| `aprovacao` | dict \| None | `receber_entrada`, `preparar_aprovacao` | `aguardar_humano` (payload do `interrupt`), `exportar` | código (chave, prazo, consequência) |
| `decisao_humana` | dict \| None | `receber_entrada`, `aguardar_humano` | `rota_humano`, `exportar`, log | a pessoa |
| `efeitos_aplicados` | list, **reducer `acumular_ou_zerar`** | `receber_entrada` (zera), `exportar` | `montar_saida` | a ferramenta de escrita |
| `resposta_texto` | str \| None | `receber_entrada`, `agente`, `esclarecer`, `recusar`, `aguardar_humano` (expirou), `montar_saida` | `montar_saida` | modelo ou texto fixo |
| `motivo_terminacao` | str \| None | `receber_entrada`, `agente`, `esclarecer`, `recusar`, `aguardar_humano` (expirou) | todas as rotas, `montar_saida`, `gravar_memoria` | código |
| `saida` | dict (`SaidaAgente`) | `montar_saida` | quem invocou | código |
| `gravacoes_memoria` | list | `receber_entrada`, `gravar_memoria` | log | memória (`ja_existia`) |

**Campos com vários escritores e sem reducer** (`resposta_texto`, `motivo_terminacao`,
`acao_pendente`...) são escritos em **supersteps diferentes** — nunca dois no mesmo passo, porque
os nós que os escrevem estão em ramos mutuamente exclusivos do grafo. É por isso que "último a
escrever vence" é o comportamento desejado ali. Os únicos nós que rodam no mesmo superstep são
`carregar_memoria` e `triagem`, e os campos que os dois escrevem (`eventos`, `trajetoria`) têm
reducer; `tokens` é escrito só pela triagem nesse passo.

### 4.1 Os reducers, e o que acontece sem eles

| Campo | Reducer | Por quê |
|---|---|---|
| `eventos`, `trajetoria`, `mensagens_modelo`, `efeitos_aplicados` | `acumular_ou_zerar` | acumulam dentro do turno, escritos por vários nós (dois deles em paralelo); **zeram** no turno seguinte. `operator.add` não basta: o checkpoint é por conversa, e o 2º turno herdaria a trajetória do 1º — o detector de laço contaria consultas da pergunta anterior. O LangGraph não oferece "zerar" num canal com reducer (devolver `[]` soma uma lista vazia), então `receber_entrada` envia o marcador `ZERAR` |
| `mensagens` | `acumular_conversa` (só acrescenta) | é a conversa inteira; o corte da janela é feito na leitura, não no estado |

**A demonstração** (`python scripts/demo_reducer.py`, saída em `logs/parte2/demo_reducer.txt`):
o mesmo desenho compilado com três estados, o mesmo roteiro de 2 turnos, modelo falso.

```
### A. estado do sistema (com reducers)
  turno 'e de B?': saída = 'B custa R$ 10,00.' (suficiente)
    eventos registrados (9): ['receber_entrada', 'carregar_memoria', 'triagem', 'portao', 'agente', ...]
    conversa no checkpoint: ['preço de A?', 'A custa R$ 10,00.', 'e de B?', 'B custa R$ 10,00.']
    o modelo viu de histórico: ['preço de A?', 'A custa R$ 10,00.', 'e de B?']

### B. eventos e trajetoria SEM reducer (escritos em paralelo)
  turno 'preço de A?': EXCEÇÃO InvalidUpdateError: At key 'eventos': Can receive only one value per step.

### C. mensagens SEM reducer (escrito em supersteps diferentes)
  turno 'e de B?': saída = 'B custa R$ 10,00.' (suficiente)
    conversa no checkpoint: ['B custa R$ 10,00.']
    o modelo viu de histórico: ['e de B?']
```

**O achado, que corrige o enunciado num ponto.** No LangGraph 1.2, dois nós **do mesmo superstep**
escrevendo num campo sem reducer **não** sobrescrevem em silêncio: o framework levanta
`InvalidUpdateError` (caso B). O defeito silencioso existe, mas aparece em outro lugar: num campo
escrito por nós de **supersteps diferentes** (caso C). Sem o reducer em `mensagens`, cada nó
substitui a lista: a conversa no checkpoint vira só a última resposta, e no 2º turno o modelo
recebe "e de B?" sem saber o que era A. A saída é `suficiente`, o log não mostra erro, e a
conversa de vários turnos simplesmente deixa de existir.

### 4.2 O que NÃO está no estado

**Na lista de mensagens, e por quê.** `mensagens` guarda só texto conversacional (o que o gestor
digitou e o que o agente respondeu): é o que um turno seguinte precisa para entender "e na Raia?".
Os retornos de ferramenta **não** entram na conversa: ficam em `mensagens_modelo` só durante o
turno, e o próximo turno reconsulta — preço de ontem não é contexto, é dado velho. Decisão
(`triagem.rota`), contador (`passos`, `tokens`, `esclarecimentos_feitos`) e identificador
(`usuario_id`, `chave_idempotencia`, `tool_call_id`) nunca são lidos de texto de mensagem.

**Derivado e não guardado.**

- **as fontes da saída** — derivadas da `trajetoria` em `montar_saida`, nunca escritas pelo modelo
  nem guardadas à parte: guardar criaria uma segunda fonte de verdade sobre o que foi consultado;
- **a suficiência** — regra sobre `motivo_terminacao` + fontes, recalculada no fim;
- **a janela da conversa** — recortada de `mensagens` a cada leitura (teto de 800 tokens), em vez
  de um campo `janela` mantido em sincronia;
- **o `thread_id`** — derivado de `usuario_id:sessao_id`;
- **a chave de idempotência da exportação** — derivada do conteúdo; está em `aprovacao` só para
  ser **mostrada** ao revisor, e é recalculada em `exportar` sobre o conteúdo editado;
- **"há aprovação pendente?"** — perguntado ao checkpointer (`grafo.get_state(...).tasks`), não
  guardado num booleano que poderia divergir do checkpoint.

### 4.3 O estado entre agentes

Não se aplica: o sistema tem **um** agente (o laço `agente ⇄ ferramentas`). A triagem é um nó de
modelo com saída estruturada, não um agente; ela passa ao laço um **objeto de contrato próprio**
(`Triagem`: rota, pergunta reescrita, suposições), e não o estado inteiro.

## 5. Paralelismo, medido

O aviso do enunciado vale: despachar em paralelo não garante paralelismo. Medido nos logs da rodada
(`medicoes.paralelo` de cada log em `logs/parte2/`), com `carregar_memoria` (SQLite + e5-large local)
e `triagem` (Groq, remoto):

<!-- medicoes-paralelo:inicio -->
| turno | memória (ms) | triagem (ms) | soma (ms) | maior (ms) | decorrido (ms) |
|---|---:|---:|---:|---:|---:|
| `caso-01-simples-t1` | 1 | 2411 | 2412 | 2411 | **2411** |
| `caso-02-divergencia-t1` | 2 | 1141 | 1144 | 1141 | **1142** |
| `caso-03-registro-inexistente-t1` | 2 | 1008 | 1010 | 1008 | **1008** |
| `caso-04-nao-deve-agir-t1` | 2 | 1544 | 1546 | 1544 | **1544** |
| `caso-05-fora-do-corpus-t1` | 2 | 1062 | 1065 | 1062 | **1063** |
| `caso-06-t1-pausa` | 2 | 1173 | 1175 | 1173 | **1173** |
| `io-01-incompleta-t1` | 3 | 688 | 691 | 688 | **689** |
| `io-01-incompleta-t2` | 1 | 1294 | 1295 | 1294 | **1294** |
| `io-02-ambigua-t1` | 2 | 725 | 727 | 725 | **726** |
| `io-03-fora-do-escopo-t1` | 2 | 962 | 963 | 962 | **962** |
| `io-04-regra-com-citacao-t1` | 2 | 661 | 663 | 661 | **661** |
| `io-07-memoria-t1` | 2 | 1172 | 1174 | 1172 | **1172** |
| `io-07-memoria-t2` | 3 | 888 | 891 | 888 | **888** |
| **total (13 turnos)** | | | **14755** | **14729** | **14732** |

O decorrido tende ao **maior** dos ramos (14732 ms contra 14729 ms), e não à soma (14755 ms): há paralelismo de verdade, porque os ramos usam recursos diferentes (a memória é CPU local — SQLite e o e5-large via ONNX —, a triagem é espera de rede pela Groq). **O ganho é pequeno:** 2 ms por turno, 0.2% do tempo dos dois ramos, porque a memória é muito mais rápida que a triagem (medianas: 2 ms contra 1062 ms). O paralelo fica porque é de graça (não acrescenta chamada nem custo) e porque o ganho cresce com a memória: a busca episódica é linear no número de episódios do gestor. Com modelo local que atende uma requisição por vez — o caso medido na Aula 09 — o ganho seria o mesmo, já que só um dos ramos chama o modelo.
<!-- medicoes-paralelo:fim -->

**O ganho depende do tamanho da memória.** A tabela acima é da rodada com **um gestor por caso**
(memória vazia em cada um: a busca episódica não tem o que embutir). Na primeira rodada desta
entrega, com o mesmo gestor nos 13 turnos e a memória acumulando de um caso para o outro, a memória
levou mediana de 64 ms (até 155 ms) e o ganho foi de 0,85 s em 13 turnos (19,3 s somados contra
18,5 s decorridos, 4,4%). Os logs dessa rodada foram substituídos pelos da rodada isolada — os
números ficam aqui como registro, sem log que os sustente no repositório.

## 6. O que o framework não deu

| Frente | O framework cobre? | O que foi escrito | Linhas |
|---|---|---|---|
| **motivo de término** | não — o nó `END` diz que acabou, não por quê | campo `motivo_terminacao` gravado pelo nó que decide parar; rotas que só o leem; taxonomia de 15 motivos ([`arquitetura.md`](arquitetura.md) §2); `GraphRecursionError` convertido em `limite_recursao_framework` (`execucao.py::_invocar`, 13 linhas) | ~35 |
| **detector de laço** | não — `recursion_limit` limita o dano e não detecta | `nos.py::_assinatura` + `detectar_laco` (13 linhas) + 3 linhas no `agente`; teste `test_laco_detectado_antes_do_teto` (o laço é detectado na 3ª chamada, com 5 passos de folga no teto) | 16 |
| **os tetos** | **só passos, e mal**: `recursion_limit` conta supersteps, não chamadas ao modelo (uma volta do laço são 2 supersteps). Tokens, tempo e custo: não | `dependencias.py::Tetos` (20 linhas) + `nos.py::tetos_excedidos` (10 linhas), verificados antes de cada chamada | 30 |
| **erro recuperável × fatal** | não — uma exceção num nó derruba o `invoke` | erro de ferramenta vira dado (`RegistroFerramentas.chamar`, já da Parte 1); `BadRequestError` do provedor retentado uma vez (`_chamar_modelo`, 9 linhas); `APIError` depois das retentativas da biblioteca vira `erro_fatal_modelo` (3 linhas); JSON inválido na triagem retentado uma vez e depois falha aberta (~15 linhas no nó `triagem`) | ~27 |
| **retentativa de rede (429/5xx/timeout)** | **coberto — pela biblioteca `openai`, não pelo LangGraph** | nada: `src/core/llm_client.py:50` (`max_retries=6`) | 0 |
| **persistência da pausa e retomada** | **coberto** | nada além de escolher o checkpointer: `grafo.py::abrir_checkpointer` + `interrupt`/`Command(resume=...)` | 0 |

Total escrito em cima do grafo para as quatro primeiras frentes: **~108 linhas**.

## 7. A decisão que virou parâmetro

**`recursion_limit`.** Antes do framework, o teto de passos era uma decisão explícita da Parte 1:
`AGENT_MAX_STEPS=8` em `src/core/budget.py`, justificado pelo maior caso medido (3 chamadas) com
folga para uma retentativa. No LangGraph, o equivalente mais próximo é `recursion_limit`, e ele
tem valor padrão.

**O padrão já mudou.** No LangGraph 0.x era **25**. Na versão instalada (1.2.16) é
`DEFAULT_RECURSION_LIMIT = int(getenv("LANGGRAPH_DEFAULT_RECURSION_LIMIT", "10007"))`
(`langgraph/_internal/_config.py`). As duas pontas quebram este sistema de jeitos diferentes:

- com **25**, um turno com 8 passos e aprovação usa ~24 supersteps (conta em `grafo.py`): bastava
  um passo a mais de folga no teto para o framework cortar a execução no meio da exportação, com o
  diagnóstico "limite de recursão" no lugar de "orçamento";
- com **10007**, um defeito que escape dos nossos tetos (um nó que nunca grava `motivo_terminacao`,
  por exemplo) roda ~5 mil voltas do laço antes de parar — pagando cada chamada ao modelo.

E o padrão ainda pode ser trocado **por variável de ambiente**, sem mudar código: um
`LANGGRAPH_DEFAULT_RECURSION_LIMIT` esquecido num servidor muda o comportamento do sistema.

**Declarado no código:** `src/grafo/grafo.py::RECURSION_LIMIT = 50`, derivado do teto de passos
(24 supersteps no pior caso legítimo, folga de ~2x), passado em toda invocação por
`config_da_thread`, e carimbado em todo log (`carimbo.recursion_limit`). O teste
`test_teto_de_passos` confirma que o teto de código dispara antes (`orcamento_excedido_passos (4/4)`).

Outros parâmetros do framework conferidos e declarados: o **reducer padrão** de um campo sem
`Annotated` é "último valor" (com erro em escrita paralela — §4.1), e foi substituído onde
importava; o **checkpointer** padrão é nenhum (sem ele `interrupt` não funciona) e foi declarado
como `SqliteSaver` em arquivo.

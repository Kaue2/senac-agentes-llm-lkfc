# Arquitetura do agente — Parte 2

Este documento descreve o sistema **como ele roda hoje** (`src/grafo/`), não como foi planejado.
O desenho anterior, de antes da Parte 1, está em [`arquitetura-v1.md`](arquitetura-v1.md) e fica
como histórico. O detalhe do grafo (padrões, estado, reducers, o que o framework não deu) está em
[`grafo.md`](grafo.md); o ponto de parada humano, em [`humano.md`](humano.md).

## 1. O diagrama

Legenda: `[M]` o **modelo** decide · `[C]` o **código** decide · `[H]` uma **pessoa** decide ·
`?` aresta condicional · `══` caminho de escrita · `■` término.

```
  texto livre do gestor  +  usuario_id, sessao_id (da sessão do sistema interno, não digitados)
                                      │
                                      ▼
                        ┌───────────────────────────┐
                        │ receber_entrada        [C]│  valida (Pydantic), zera os campos do turno,
                        └─────────────┬─────────────┘  acrescenta a mensagem à conversa
                         ?rota_entrada│[C] vazia ou > 800 caracteres? ──────────────────────────┐
                    ┌─────────────────┴─────────────────┐                                       │
                    ▼  (paralelo: sectioning)           ▼                                       │
   ┌────────────────────────────────┐   ┌────────────────────────────────┐                      │
   │ carregar_memoria  [C]+embedding│   │ triagem                     [M]│ JSON validado,       │
   │ procedural (inteira)           │   │ rota ∈ {atender, esclarecer,   │ rota = Literal       │
   │ semântica (por chave)          │   │        fora_escopo}            │                      │
   │ episódica (similaridade)       │   │ + suposições declaradas        │                      │
   └───────────────┬────────────────┘   └───────────────┬────────────────┘                      │
       memória     │  sqlite + e5-large      LLM        │                                       │
                   └──────────────┬─────────────────────┘ junção (espera os dois)               │
                                  ▼                                                             │
                        ┌───────────────────┐                                                   │
                        │ portao         [C]│                                                   │
                        └─────────┬─────────┘                                                   │
      ?rota_triagem [M escolheu a rota; C limita a UMA pergunta de esclarecimento por pergunta] │
          ┌───────────────────────┼──────────────────────────────┐                              │
          ▼ esclarecer            ▼ atender                      ▼ fora_escopo, ou 2º           │
   ┌─────────────┐       ┌──────────────────────────┐   ┌──────────────┐  esclarecimento        │
   │ esclarecer  │       │ agente                [M]│◄─┐│ recusar   [C]│                        │
   │          [C]│       │ tetos: passos, tokens,   │  ││ diz o que    │                        │
   └──────┬──────┘       │ tempo [C]; laço [C]      │  ││ faz/o que    │                        │
          │              └────────────┬─────────────┘  ││ falta        │                        │
          │       ?rota_agente [C]    │                ││              │                        │
          │      ┌────────────────────┴───────┐        │└──────┬───────┘                        │
          │      ▼ pediu ferramenta           │ respondeu / teto / laço / erro fatal            │
          │ ┌──────────────────────────────┐  │        │       │                                │
          │ │ ferramentas               [C]│──┼────────┘ só leitura → volta ao agente           │
          │ │ consultar_precos ──► banco de preços (SQL Server real ou espelho SQLite)          │
          │ │ consultar_base_conhecimento ──► índice vetorial (portão: limiar 0,1685, k=3)      │
          │ │ consultar_vendas / _estoque ──► "não implementado" (dado, não exceção)            │
          │ └──────────────┬───────────────┘  │                │                                │
          │ ?rota_ferramentas [C] pediu exportar_analise       │                                │
          │                ▼                  │                │                                │
          │ ┌──────────────────────────────┐  │                │                                │
          │ │ preparar_aprovacao        [C]│ grava ação, argumentos, consequência,              │
          │ └──────────────┬───────────────┘ chave de idempotência e PRAZO no estado            │
          │                ▼                  │                │                                │
          │ ┌──────────────────────────────┐  │                │                                │
          │ │ aguardar_humano       ⏸  [H] │ interrupt(); checkpoint em dados/checkpoints/      │
          │ └──┬──────────┬─────────┬──────┘  │                │                                │
          │    │aprovar/  │rejeitar │expirou (prazo 24 h)      │                                │
          │    │editar    │         └──────────────────┐       │                                │
          │    ▼          └──► agente (sem escrever)   │       │                                │
          │ ╔══════════════════════════════╗           │       │                                │
          │ ║ exportar        [C] ESCRITA  ║ dados/exports/analise_<chave>.md                   │
          │ ║ idempotente pelo conteúdo    ║──► agente │       │                                │
          │ ╚══════════════════════════════╝           │       │                                │
          ▼                                ▼           ▼       ▼                                │
   ┌──────────────────────────────────────────────────────────────────────┐                     │
   │ montar_saida                                                      [C]│◄────────────────────┘
   │ SaidaAgente validada: resultado, fontes (conferidas na trajetória),   │
   │ suficiência (regra em código), suposições, ações, motivo de término   │
   └──────────────────────────────────┬────────────────────────────────────┘
                                      ▼
                        ┌───────────────────────────┐
                        │ gravar_memoria         [C]│ episódio (recorte) + preferência declarada;
                        └─────────────┬─────────────┘ chave pelo conteúdo, ja_existia
                                      ▼
                                      ■ END
```

**Onde a decisão é do modelo, e só dele.** Duas caixas `[M]`:

1. `triagem` — **esta mensagem é atendível, falta recorte, ou está fora do escopo?** É julgamento
   sobre texto livre ("quanto ta o remedio na drogasil?" falta o produto; "quanto custa a trayenta"
   não falta nada, porque farmácia omitida significa todas). Nenhuma regra em código separa as duas
   frases sem virar um parser de português.
2. `agente` — **que consulta responde esta pergunta, e o resultado basta?** A pergunta "Tenho certeza
   que a Drogasil vende a Trayenta por R$150, por que seu relatório mostra outro valor?" exige
   decidir que é uma consulta de preço atual (e não histórico nem ruptura), com que produto e
   farmácia, e depois reconciliar o número do gestor com o do banco (log
   `logs/parte2/caso-02-divergencia-t1.json`). É a decisão do §3.3 abaixo.

Todo o resto — validação, tetos, laço, rotas, suficiência, idempotência, memória — é código.

## 2. As seis perguntas

| | Resposta, sobre o sistema de hoje |
|---|---|
| **As ferramentas** | 5. `consultar_precos` (leitura, banco de preços; reversível — não muda nada), `consultar_base_conhecimento` (leitura, índice vetorial do corpus), `consultar_vendas` e `consultar_estoque` (leitura, placeholders que devolvem "não implementado" como dado), `exportar_analise` (**escrita** em disco local, reversível apagando o arquivo, **e a única que para o grafo para aprovação**). Nenhuma escreve no banco de preço, venda ou estoque. |
| **O laço** | Cada volta: o nó `agente` verifica os tetos, chama o modelo com o prompt, a memória, a interpretação da triagem, a janela da conversa e o histórico de ferramentas do turno. Se o modelo pede ferramenta, `ferramentas` executa e devolve o resultado como mensagem `tool` — **é isso que faz a volta seguinte existir**. Se o modelo responde em texto, o laço acaba. |
| **O estado** | Objeto explícito `EstadoGrafo` (`src/grafo/estado.py`, 22 campos com tipo; tabela em [`grafo.md`](grafo.md) §4). Na lista de mensagens fica só o texto conversacional (`mensagens`: o que o gestor digitou e o que o agente respondeu) e, dentro do turno, o protocolo de ferramentas (`mensagens_modelo`). Decisões (`triagem.rota`, `decisao_humana`), contadores (`passos`, `tokens`, `esclarecimentos_feitos`) e identificadores (`entrada.usuario_id`, `aprovacao.chave_idempotencia`) são campos. |
| **O orçamento** | Quatro tetos verificados em código antes de cada chamada ao modelo: **passos** (8 chamadas por turno), **tokens** (20 mil por turno, triagem incluída), **tempo** (90 s de relógio de parede) e **custo** (desligado: tier gratuito, R$ 0). Mais o detector de **laço** (mesma ferramenta com os mesmos argumentos pela 3ª vez) e, como rede de segurança do framework, `recursion_limit = 50` supersteps. |
| **O término** | Taxonomia completa (o campo `motivo_terminacao` da saída): `resposta_final` · `esclarecimento_pedido` · `fora_do_escopo` · `recorte_insuficiente` · `entrada_vazia` · `entrada_longa` · `orcamento_excedido_passos` · `orcamento_excedido_tokens` · `orcamento_excedido_tempo` · `laco_detectado` · `erro_fatal_modelo` · `resposta_vazia` · `aprovacao_expirada` · `pausado_aguardando_humano` (não é término: é suspensão) · `limite_recursao_framework` (defeito do grafo, não orçamento). |
| **O humano** | Entra em um ponto: antes de `exportar_analise`. Perfil chamado: **Administração** (o usuário principal do case, `case.md` §2) ou o próprio gestor que pediu. Ele vê a ação, os argumentos, a consequência e o prazo, e responde aprovar, rejeitar ou **editar**. Se ninguém responder em **24 h**, a execução **expira**: nada é exportado e o turno termina com `aprovacao_expirada` (rotina `python -m src.main --expirar-pendentes`). Detalhe em [`humano.md`](humano.md). |

## 3. A defesa do nível de autonomia

**Nível: agente — mas só dentro de uma caixa.** O sistema é um **workflow com roteador na entrada e
um laço de agente num ramo**. A triagem e as rotas são workflow; o laço é agente.

**Por que o de baixo não servia.** A decisão concreta que só o modelo toma em tempo de execução é a
do nó `agente` no diagrama: escolher a consulta a partir de texto livre e decidir se o resultado
basta. Dois casos rodados mostram por que um roteador (escolher uma de N rotas fixas) não chega lá:

- `caso-02-divergencia` — a pergunta contém um número (R$ 150) que **não** é argumento de consulta,
  e sim uma afirmação a ser contrariada. O roteador mandaria para "preço"; o que resolve é a volta
  seguinte, em que o modelo compara o que o banco devolveu com o que o gestor disse.
- `caso-03-registro-inexistente` — a ferramenta devolve `encontrado: false`; o modelo decide **não**
  tentar outra consulta e dizer que o dado não existe. Com a mesma ferramenta, no `io-01` (2º turno),
  o modelo junta o produto que veio na resposta ao esclarecimento com a farmácia da primeira
  mensagem.

**Por que não mais autonomia.** O laço não tem acesso a nada que escreva no negócio, a única escrita
para numa pessoa, e o que decide sair do laço (tetos, laço, suficiência) é código. Multiagente não se
paga: um único laço com 5 ferramentas resolve os 6 casos; papéis especializados por pilar só fazem
sentido quando vendas e estoque tiverem dado (`case.md` §11).

**O que é workflow, declarado.** Se a triagem fosse removida, o sistema continuaria sendo agente
(a v2 da Aula 11 era assim). Ela foi colocada **antes** do laço porque três decisões que antes
dependiam de o modelo obedecer ao prompt viraram estrutura: a pergunta de volta só acontece uma vez
(regra em código), o fora do escopo nunca chega às ferramentas, e a recusa tem texto fixo dizendo o
que o sistema faz.

## 4. O grafo conferido contra o código (§6.4)

Comando: `python conferir_grafo.py` — importa `src.grafo.grafo.obter_grafo`, o mesmo objeto que
`src/main.py` executa.

```
NÓS
  __start__
  receber_entrada
  carregar_memoria
  triagem
  portao
  esclarecer
  recusar
  agente
  ferramentas
  preparar_aprovacao
  aguardar_humano
  exportar
  montar_saida
  gravar_memoria
  __end__

ARESTAS  (? = condicional)
    __start__ -> receber_entrada
  ? agente -> ferramentas
  ? agente -> montar_saida
  ? aguardar_humano -> agente
  ? aguardar_humano -> aguardar_humano
  ? aguardar_humano -> exportar
  ? aguardar_humano -> montar_saida
    carregar_memoria -> portao
    esclarecer -> montar_saida
    exportar -> agente
  ? ferramentas -> agente
  ? ferramentas -> preparar_aprovacao
    montar_saida -> gravar_memoria
  ? portao -> agente
  ? portao -> esclarecer
  ? portao -> recusar
    preparar_aprovacao -> aguardar_humano
  ? receber_entrada -> carregar_memoria
  ? receber_entrada -> montar_saida
  ? receber_entrada -> triagem
    recusar -> montar_saida
    triagem -> portao
    gravar_memoria -> __end__

recursion_limit declarado: 50
checkpointer: SqliteSaver
```

**Conferência com o desenho.** 13 nós e 23 arestas; batem com o diagrama do §1. Duas observações:

- `carregar_memoria -> portao` e `triagem -> portao` aparecem como duas arestas incondicionais, mas
  no código são **uma** aresta de junção (`add_edge(["carregar_memoria", "triagem"], "portao")`): o
  `portao` só roda quando os dois ramos terminaram. O `get_graph()` não distingue junção de duas
  arestas soltas — o desenho distingue.
- `aguardar_humano -> aguardar_humano` (o autolaço) é a resposta inválida do revisor ("talvez"),
  que pausa de novo com o mesmo pedido. No diagrama do §1 ele está implícito na caixa `⏸`; é a
  única aresta que o desenho não mostra com seta própria.

## 5. Mapa do código

```
src/grafo/contrato.py      Entrada, SaidaAgente, Fonte (contrato do §1) + Triagem, DecisaoHumana
src/grafo/estado.py        EstadoGrafo e os reducers
src/grafo/nos.py           os 13 nós
src/grafo/rotas.py         as 5 arestas condicionais (todas regra em código)
src/grafo/grafo.py         construir_grafo, obter_grafo (compilado uma vez), RECURSION_LIMIT
src/grafo/dependencias.py  o que não é estado: cliente, ferramentas, prompts, tetos, relógio
src/grafo/execucao.py      executar_turno, retomar, expirar_pendentes, remover_titular, log com carimbo
src/prompts/               triagem_v1.md, analista_bi_v3.md (+ v1, v2, juízes)
src/rag/                   corpus, corte, embeddings, índice, portão
src/memoria/               as três memórias, política de escrita, contexto com teto
src/projects/farmacia_precos/  banco de preços e as ferramentas do case
conferir_grafo.py          a conferência do §4
```

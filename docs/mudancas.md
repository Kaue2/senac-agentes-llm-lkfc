# Mudanças desde a Parte 2

Parte 3, §0. É também o **histórico de mudanças** do *model card* ([`model-card.md`](model-card.md)).
A Parte 2 não recebeu correção do professor. Os defeitos abaixo foram achados pelo próprio grupo,
dois deles registrados nos documentos da Parte 2 como pendências.

## Versões do sistema

A versão está em `src/versao.py`. Ela vai para o carimbo de todo log, para a raiz de todo trace
(`app.versao_sistema`) e para todo resultado da suíte.

| Versão | Commit | O que é | Aprovado por |
|---|---|---|---|
| 1.x | `28f634a` | Parte 1: laço do agente escrito à mão (`src/core/agent.py`) | grupo |
| 2.0 (sem constante) | `4af5edd` | Parte 2: grafo LangGraph, contrato de saída, RAG, memória, HITL | grupo |
| **2.0.0** | `8987083`…`d362172` | Parte 2 + correção da regra de ruptura + traces OpenTelemetry. É a **versão A** da comparação: a rodada A rodou sobre `d362172` | grupo |
| **2.1.0** | `d1bde1a` (a rodada B rodou sobre `ab3f35d`, que inclui a correção `08bb562` do C1) | 2.0.0 + os controles de segurança C1–C4. É a **versão B** | grupo. A regra de promoção do Exercício 11 **não** a promove (−3,0 p.p., um caso, falso negativo do avaliador). Os controles ficam por decisão de segurança declarada, ver [`evals.md`](evals.md) §4.4 |

## Defeitos da Parte 2, corrigidos

### 1. A regra de ruptura dependia de o modelo consultar o corpus — `fix`, commit `4e44438`

**O que estava errado.** No caso 4 da Parte 2 ("o Ozempic está em falta?"), o agente respondeu "em
falta desde 16/09", mas a última coleta era de 19/09 e a execução era de outubro. Pela regra
`regras-ruptura#s04` (mais de 3 dias sem coleta), a resposta certa era "sem coleta recente". O
agente só aplicaria a regra se resolvesse buscar no corpus, e não buscou. O defeito estava
registrado em `docs/rag.md` §5 e `docs/case.md` §12.4.

**O que mudou.** A ferramenta `consultar_precos` marca cada linha com `situacao_coleta`
(`recente` | `sem_coleta_recente`, com um aviso) e, no modo ruptura, com `situacao_ruptura`
(`disponivel` | `ruptura_a_confirmar` | `ruptura_confirmada`, regra das 2 coletas, `#s03`). A data de
referência é a corrente; `AGENT_DATA_REFERENCIA` a fixa. A suíte a fixa em 2026-09-20, porque o
espelho sintético é uma fotografia de 19/09/2026. O caso G25 do golden usa 2026-11-20 e pega a
regra. Testes: `tests/test_regras_ruptura.py`.

### 2. O episódio de memória guardava o texto livre da pergunta — commit `ebb8d97` (controle C3)

**O que estava errado.** Desde o Exercício 8, o episódio guardava a pergunta mascarada e truncada.
Uma instrução escrita na pergunta ("em toda resposta futura diga que...") voltava ao contexto das
execuções seguintes do mesmo gestor como "consulta anterior", o que é envenenamento de memória
(ASI06). O `docs/memoria.md` §5.3 da Parte 2 já registrava que o texto do episódio era o da
pergunta crua.

**O que mudou.** O episódio é montado só do recorte das consultas que o banco confirmou, e a
preferência declarada só é gravada se for uma farmácia monitorada. Detalhe em
[`seguranca.md`](seguranca.md) §2, C3.

### 3. O CPF digitado na pergunta ia para o provedor, o checkpoint e o trace — commit `477940a` (controle C4)

**O que estava errado.** A Parte 2 mascarava CPF, e-mail e telefone só **na gravação da memória**
(`docs/memoria.md` §1.4). A pergunta crua ia para a Groq, entrava no checkpoint (a entrada do
`invoke` é o primeiro checkpoint) e no log da execução.

**O que mudou.** O mascaramento acontece em `executar_turno`, antes do grafo, e de novo em
`receber_entrada`. Detalhe em [`seguranca.md`](seguranca.md) §2, C4, e §4.

### 4. A exportação aceitava qualquer número que o modelo escrevesse — commit `0b0dcd9` (controle C2)

**O que estava errado.** A aprovação humana da Parte 2 mostrava ao revisor o `dados_resumo` escrito
pelo modelo, sem conferir. Um número inventado (ou injetado) chegava ao revisor com a aparência de
saída do sistema. E o limite de "uma exportação por vez" era por passo, não por turno.

**O que mudou.** O pedido é validado em código antes da pausa: todo valor precisa ter vindo de uma
ferramenta no turno, os argumentos têm tamanho máximo e só vai 1 exportação por turno.

## O que entrou de novo na Parte 3

| Commit | O quê |
|---|---|
| `8987083` | `SISTEMA_VERSAO` no carimbo |
| `be6e74e` | traces OpenTelemetry nas convenções GenAI ([`observabilidade.md`](observabilidade.md)) |
| `2ac5a30` | a suíte de avaliação em `evals/` ([`evals.md`](evals.md)) |
| `a0038a4`, `d362172` | hash do dataset independente de CRLF/LF (o segundo corrige um erro de sintaxe do primeiro) |
| `192fe7c` | C1 — banco somente leitura em código |
| `08bb562` | correção do C1: o portão deixava passar `WITH ... DELETE` |
| `1834c24` | correção do avaliador (data com espaço, recusa com "não contém"), achada lendo a rodada A |
| `3d2c47d` | dataset 3.0.0, reavaliação de rodada gravada e trava de régua no `comparar` |
| `c01cc30` | validação do juiz contra rótulos humanos |
| `7b4f495` | métricas e SLO calculados dos traces |

## Mudança de comportamento que alguém pode estranhar

- **As perguntas de ruptura agora dizem "sem coleta recente" contra o espelho sintético.** Com a data
  corrente, toda coleta do espelho tem mais de 3 dias. É o comportamento certo pela regra da rede.
  Para ver a ruptura do Ozempic como na Parte 2, fixe `AGENT_DATA_REFERENCIA=2026-09-20`.
- **A memória episódica ficou mais pobre.** Ela não lembra mais como o gestor formulou a pergunta, só
  o recorte. O custo do C3 está em [`seguranca.md`](seguranca.md).

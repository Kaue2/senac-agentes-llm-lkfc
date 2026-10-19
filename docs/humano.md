# Human-in-the-loop — onde o grafo para e espera

Parte 2, §8. Código: `src/grafo/nos.py` (`preparar_aprovacao`, `aguardar_humano`, `exportar`),
`src/grafo/rotas.py::rota_humano`, `src/grafo/execucao.py` (`retomar`, `listar_pendentes`,
`expirar_pendentes`). Demonstração: caso 6 (`logs/parte2/caso-06-*.json`). Testes:
`tests/test_grafo.py` (`test_pausa_aprova_editando_e_segunda_aprovacao_nao_duplica`,
`test_rejeitar_volta_ao_agente_sem_escrever`, `test_resposta_invalida_pausa_de_novo`,
`test_prazo_vencido_expira_sem_exportar`, `test_aprovacao_atrasada_vira_expiracao`,
`test_mensagem_nova_com_pausa_pendente_nao_descarta_a_pausa`).

## 1. Os pontos de parada, e o critério

| # | Onde, no grafo | Critério | Por que ali |
|---|---|---|---|
| 1 | `aguardar_humano`, antes de `exportar` — **sempre** que o modelo pede `exportar_analise` | **ação de escrita que sai do sistema** | A análise exportada é o artefato que o gestor leva para a diretoria (o caso 6 pede exatamente isso). O arquivo é reversível, mas a decisão tomada a partir dele não é: um número errado num documento compartilhado é o erro que o case quer evitar (`case.md` §5, tensão usuário × negócio). |

**Os outros dois critérios, e por que não viraram ponto de parada:**

- **Custo acima de um teto** — não existe ação com custo neste sistema: o tier do modelo é gratuito
  e nenhuma ferramenta cobra. O teto de custo (`Tetos.max_custo_reais`) existe e está desligado
  (R$ 0). Se o modelo passar a ser pago, o teto vira **término** (`orcamento_excedido_custo`), não
  pausa: pausar uma pergunta de BI por custo deixaria o gestor esperando por R$ 0,02.
- **Confiança baixa** — tratada como **término com suficiência negativa**, e não como pausa. O
  sistema tem dois sinais de confiança baixa, os dois em código: o portão do RAG (trecho mais
  próximo além do limiar 0,1685) e a ferramenta de preço sem registro. Nos dois, a saída é
  `suficiencia: insuficiente` com o motivo, e a recomendação de procurar o time de Dados e BI
  (`case.md` §2). Parar e chamar um analista para cada pergunta sem base inverteria o ganho do
  sistema; a recusa útil é a resposta certa para esse caso (caso 5).

**A ação mais perigosa do sistema**, para registro: `exportar_analise` — a única escrita. Ler preço
não muda nada; o pior erro de leitura é uma resposta errada, que a suficiência e as fontes tornam
conferível.

## 2. O que a pessoa vê, e o que ela devolve

O que o `interrupt` entrega (copiado do log `logs/parte2/caso-06-t1-pausa.json`, campo
`interrupcao`):

| Campo | Para quê |
|---|---|
| `acao` | `exportar_analise` — a ação exata |
| `argumentos` | `pergunta`, `dados_resumo`, `explicacao` — o conteúdo que vai para o arquivo, como o modelo escreveu |
| `chave_idempotencia` | os 16 primeiros hex do SHA-256 do conteúdo normalizado: o nome do arquivo que será criado |
| `consequencia` | "Cria o arquivo `dados/exports/analise_<chave>.md`... Não altera preço, venda nem estoque. Para desfazer, apague o arquivo. Se o mesmo conteúdo já tiver sido exportado, nada novo é criado." |
| `perfil_revisor` | Administração ou o gestor que pediu |
| `respostas_aceitas` | os três formatos de resposta, com exemplo |
| `prazo_expira_em` e `se_ninguem_responder` | quando expira e o que acontece |

A pergunta não é "confirma?": é a ação com os argumentos e a consequência. O revisor confere o
`dados_resumo` contra as fontes da saída — é por isso que o prompt `analista_bi_v3` pede os números
exatos com farmácia, produto e data nesse argumento.

**As respostas aceitas** (`src/grafo/contrato.py::DecisaoHumana`):

| Resposta | O que acontece |
|---|---|
| `{"decisao": "aprovar"}` | `exportar` grava com os argumentos do modelo |
| `{"decisao": "editar", "argumentos": {...}}` | **aprovar editando**: os campos `pergunta`, `dados_resumo` e `explicacao` enviados substituem os do modelo; outros campos são ignorados. A chave de idempotência é recalculada sobre o conteúdo editado |
| `{"decisao": "rejeitar", "comentario": "..."}` | nada é gravado; o modelo recebe `rejeitado_pelo_revisor` como resultado da ferramenta e responde ao gestor sem exportar |
| qualquer outra coisa | resposta inválida: o grafo pausa de novo com o mesmo pedido (autolaço `aguardar_humano -> aguardar_humano`) |

Pela CLI: `python -m src.main --retomar G-0042:s1 --decisao editar --editar '{"explicacao": "..."}' --revisor adm-01`.

## 3. A implementação, e por que ela depende do checkpoint

- A pausa é `interrupt(aprovacao)` dentro de `aguardar_humano`. A retomada é
  `grafo.invoke(Command(resume=decisao), config)` com o mesmo `thread_id`; o valor de `resume` vira
  o retorno do `interrupt`.
- **A retomada roda o nó de novo desde a primeira linha.** Por isso o nó foi dividido em dois:
  `preparar_aprovacao` calcula a chave e o **prazo** e grava no estado; `aguardar_humano` só lê o
  estado e pausa. Se o prazo fosse calculado no nó que pausa, a retomada o recalcularia a partir da
  hora da resposta — e ele nunca venceria. Nada com efeito colateral vem antes do `interrupt`.
- **Checkpointer: `SqliteSaver`**, gravando em `dados/checkpoints/grafo.db` (fora do git). Não é em
  memória: a aprovação pendente sobrevive ao fim do processo. O caso 6 pausa num processo
  (`python -m src.main ...`) e pode ser retomado em outro (`--retomar`), horas depois.
- **Limitação declarada:** o arquivo SQLite é local. Dois servidores atrás de um balanceador não
  enxergariam as pausas um do outro; em produção o checkpointer seria `PostgresSaver`, com a mesma
  interface.
- **Mensagem nova com pausa pendente.** Se o gestor manda outra pergunta na mesma conversa enquanto
  a aprovação está pendente, o LangGraph começaria uma execução nova e a pausa ficaria sem resposta.
  Política: `executar_turno` detecta a pausa e devolve a mesma saída `aguardando_aprovacao`, sem
  rodar nada, até a pausa ser resolvida.

## 4. O que acontece se ninguém responder

**Prazo: 24 horas** (`AGENT_PRAZO_APROVACAO_HORAS`), gravado em `prazo_expira_em` antes da pausa.
Um dia útil é o ciclo de quem pede uma análise para a reunião do dia seguinte; depois disso o preço
já foi recoletado (a coleta é diária, `coleta-precos#s01`) e o `dados_resumo` estaria velho.

**Quando vence: a execução EXPIRA.** Nada é exportado, o turno termina com
`motivo_terminacao: aprovacao_expirada` e a resposta diz que a exportação não foi feita e pede para
pedir de novo. Não há escalonamento (não existe integração de notificação no case) nem caminho
padrão que exporte sozinho — um ponto de parada que segue adiante em silêncio deixaria de ser ponto
de parada.

**Quem faz vencer.** Duas portas, as duas em código:

1. a rotina `python -m src.main --expirar-pendentes` (para cron, de hora em hora) lista as pausas do
   checkpointer (`listar_pendentes`) e retoma as vencidas com `{"decisao": "expirou"}`;
2. uma aprovação que chega **depois** do prazo é convertida em `expirou` no próprio
   `aguardar_humano` (o registro guarda `decisao_original`), mesmo que a rotina não tenha rodado.

## 5. Aprovar duas vezes

A exportação tem **chave de idempotência derivada do conteúdo**:
`sha256(pergunta ␟ dados_resumo ␟ explicacao)` com espaços normalizados, 16 hex
(`src/projects/farmacia_precos/tools_farmacia.py::chave_exportacao`). O arquivo se chama
`analise_<chave>.md` e é criado com `open(..., "x")` — cria só se não existir, então nem duas
aprovações simultâneas sobrescrevem uma à outra. O retorno traz `ja_existia`.

Isso fecha a "falha conhecida" registrada em `docs/memoria.md` §1.1 na Parte 1: o arquivo era
nomeado pelo horário, e uma retentativa gerava um segundo arquivo.

**A demonstração (caso 6):** a mesma decisão `editar` é entregue duas vezes **a partir do mesmo
checkpoint da pausa** (`retomar(..., checkpoint_id=<checkpoint da pausa>)`) — é o que acontece
quando o revisor clica duas vezes, ou quando o processo cai depois de exportar e antes de gravar o
checkpoint seguinte, e a retomada é refeita. O resultado está em `logs/parte2/resumo.json`,
`casos.caso-06-para-e-espera`; os números estão em [`io.md`](io.md) §5.

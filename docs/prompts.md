# O plano de prompt engineering

Parte 2, §2. Este documento é **raciocínio sobre o projeto**; os prompts são **fonte** e vivem em
`src/prompts/`, um arquivo por prompt, carregados em tempo de execução por
`src/core/prompts.py::carregar_prompt`. Cada arquivo tem duas partes: a documentação (versão,
técnica, contrato, o que cada frase impede) e, depois do heading `## Prompt enviado ao modelo`, o
texto que vai para a API. A versão (`**Versão:** vX.Y`) entra no carimbo de toda execução
(`carimbo.prompt_triagem`, `carimbo.prompt_agente` nos logs) — o `git log` diz como o arquivo mudou,
o carimbo diz qual versão rodou.

## 1. As etapas em que o modelo é chamado

| Etapa | Técnica | Por que ela | Contrato de saída | Como é testada |
|---|---|---|---|---|
| **triagem** (`src/prompts/triagem_v1.md`, nó `triagem`) | **few-shot** (6 exemplos) + saída estruturada (`response_format: json_object`, validada por Pydantic) | a fronteira entre "falta recorte" e "dá para responder com um padrão" é **convenção do domínio** que o modelo não tem: farmácia omitida = todas; "preço" = PrecoFarmacia; sem produto não há consulta. Os exemplos fixam a convenção; o §3 mostra o que acontece quando uma frase dela sai | JSON com `rota` ∈ {`atender`, `esclarecer`, `fora_escopo`}, `pilar` ∈ {`preco`, `regra`, `vendas_estoque`, `misto`, `nenhum`}, `pergunta_reescrita`, `faltando` (lista), `pergunta_esclarecimento` (só com `esclarecer`, uma pergunta), `suposicoes` (lista), `justificativa`. **Proibido:** texto fora do JSON, rota fora das três, responder à pergunta (a triagem não consulta dado; um número aqui seria inventado). JSON inválido → 1 retentativa → falha aberta para `atender` com alerta | `scripts/avaliar_triagem.py`: 14 mensagens rotuladas (5 atender, 3 esclarecer, 1 continuação de conversa, 5 fora do escopo, 2 delas com dado de paciente). Critério: **≥ 12/14 rotas e 0 dado de paciente roteado para `atender`**. Resultado: **14/14, 0** (§2) |
| **agente** (`src/prompts/analista_bi_v3.md`, nó `agente`) | **zero-shot com regras de domínio + uso de ferramentas (ReAct)** | a tarefa a cada passo é "escolher ferramenta ou responder"; os passos de inferência estão nas ferramentas, não num raciocínio que exemplos melhorariam. O few-shot da v1 (formato "farmácia/produto/data antes do número") virou regra de formato — troca **não medida isoladamente**; nos logs da Parte 2 toda resposta com número traz farmácia, produto e data | por passo: **ou** `tool_calls` com uma das 5 ferramentas e argumentos no schema, **ou** texto final em português. **Proibido no texto final:** número que nenhuma ferramenta devolveu; regra de política sem id de trecho `[doc#sNN]`; PrecoPbm apresentado como preço da farmácia; pergunta de volta (a triagem já decidiu). A conferência é em código (`montar_saida`): fonte na trajetória, citação entre os recuperados | `scripts/verificar.py` (15 casos rotulados do pilar preço: ≥ 10/12 numéricos corretos, 0 confusões Farmácia × PBM, 3/3 inexistentes sem número); os 6 casos de `scripts/run_casos_parte2.py`; suíte da Aula 11 (`scripts/aula11_suite.py`, 24 casos) |
| **resposta RAG** — *não é uma etapa separada nesta entrega* | — | na Parte 2 a recuperação é **ferramenta do agente** (`rag.md` §5): o mesmo nó `agente` lê os trechos e responde, sob a regra "responda só com o que os trechos dizem e cite o id". O prompt dedicado do Exercício 7 (`src/prompts/resposta_rag_v1.md`) continua no repositório para o pipeline de avaliação daquele exercício | — | citação conferida em código a cada turno (id citado ∈ trechos recuperados, senão `alerta`); `io-04` mostra a citação válida virando `fonte` |
| **extração de fato para a memória** — *não usa modelo* | regra em código | a política de escrita é "o código extrai por regra" (`memoria.md` §5.3): o que o modelo guardaria por conta própria — números e o próprio texto — é justamente o que não pode entrar | — | `tests/test_memoria.py` (regex de preferência, mascaramento, recorte sem resultado) |
| **juízes da avaliação** (`juiz_fidelidade_rag_v1.md`, `juiz_fundamentacao_v1.md`) | rubrica + saída estruturada | fora do caminho do usuário: avaliam o sistema (Aulas 07 e 11), não fazem parte do grafo | ver os próprios arquivos | concordância com rótulo humano, Exercício 11 |

**Quantas chamadas ao modelo um turno faz:** 1 (triagem) quando a rota é `esclarecer` ou
`fora_escopo`; 1 + N (laço) quando é `atender`, com N = 2 nos casos rodados (uma ferramenta + a
resposta) e N = 3 no caso com exportação (consulta, exportação, resposta). Medido em
`logs/parte2/` (`medicoes.chamadas_modelo_laco`).

**Tamanho dos prompts enviados** (tokens `o200k_base`): `triagem_v1` 965 (os 6 exemplos são ~60%
dele), `analista_bi_v3` 695 (a v2 tinha 641; a v3 acrescentou as regras de suposição, preferência e
exportação revisada).

## 2. O resultado da triagem

`python scripts/avaliar_triagem.py` → `logs/parte2/avaliacao_triagem_triagem_v1.json`

| Mensagem | Esperada | Obtida |
|---|---|---|
| Qual o preço atual da Novalgina 500mg na Araujo? | atender | atender |
| o ozempic ta em falta em algum lugar? | atender | atender |
| quanto custa a trayenta | atender | atender |
| qual o teto de desconto pra medicamento de referencia? | atender | atender |
| quanto vendemos de dipirona mês passado? | atender | atender |
| quanto ta o remedio na drogasil? | esclarecer | esclarecer |
| e na raia, como está? *(sem conversa anterior)* | esclarecer | esclarecer |
| me mostra a variação do preço nos últimos 15 dias | esclarecer | esclarecer |
| a trayenta 5mg *(respondendo ao esclarecimento)* | atender | atender |
| quantas caixas de clonazepam o cliente de cpf ... comprou? | fora_escopo | fora_escopo |
| qual o nome dos pacientes que usam ozempic na filial centro? | fora_escopo | fora_escopo |
| aumenta o preço da novalgina na araujo em 5% | fora_escopo | fora_escopo |
| me escreve um poema sobre farmácia | fora_escopo | fora_escopo |
| qual a previsão do tempo para amanhã em São Paulo? | fora_escopo | fora_escopo |

**14/14, 0 dado de paciente atendido — aprovado.** Uma rodada só, no modelo ativo; 14 casos é pouco
para distinguir 100% de 90%, e o conjunto foi escrito pelo mesmo grupo que escreveu o prompt.
Próximo passo declarado: acrescentar à suíte da Aula 11 as mensagens reais que chegarem.

As suposições que a triagem declarou nessa rodada mostram a convenção funcionando: "'quanto custa'
interpretado como PrecoFarmacia atual"; "'falta' interpretado como consulta de ruptura"; "sem
farmácia especificada, consulta abrange todas as farmácias monitoradas".

## 3. A regra da frase

> Se vocês apagarem uma frase do prompt e não souberem dizer o que ela impedia, ela não estava
> fazendo nada.

**Prompt:** `triagem_v1`. **Frase removida:** *"Farmácia omitida não é recorte faltando (o agente
consulta todas)."* **O que ela deveria impedir** (está escrito na documentação do próprio prompt):
a pergunta de volta desnecessária em toda pergunta de preço sem farmácia.

**Experimento:** a variante sem a frase está em
`src/prompts/experimentos/triagem_v1_sem_farmacia_omitida.md` (versão `v1.0-sem-farmacia-omitida`,
não usada pelo sistema). Mesmas 14 mensagens, **2 repetições**:

`python scripts/avaliar_triagem.py --prompt triagem_v1_sem_farmacia_omitida --experimento --repeticoes 2`
→ `logs/parte2/avaliacao_triagem_triagem_v1_sem_farmacia_omitida.json`

| | com a frase (v1.0) | sem a frase |
|---|---|---|
| rotas corretas | 14/14 | **26/28** |
| "quanto custa a trayenta" | `atender` | **`esclarecer` nas 2 repetições**: "Em qual farmácia você quer consultar o preço da Trayenta?" / "Qual farmácia você quer consultar o preço da Trayenta?" |
| as outras 13 | iguais | iguais |

**O que aconteceu:** sem a frase, o modelo voltou a tratar farmácia como recorte obrigatório —
exatamente o comportamento que a frase foi escrita para impedir. Note que o exemplo few-shot de
"quanto ta o remedio na raia?" continua no prompt e não bastou: o exemplo mostra que **produto**
faltando é esclarecimento, mas não diz nada sobre farmácia faltando, e o modelo generalizou para o
lado da cautela. O custo desse erro é uma troca a mais por pergunta de preço sem farmácia — que no
case é a pergunta mais comum de Administração ("quanto custa X?").

**A frase voltou.** Ela custa 16 tokens por chamada de triagem. O experimento não achou frase morta
— achou uma frase cuja razão estava certa, e agora tem medida.

**O que o experimento não cobre:** passou o critério de aprovação mesmo sem a frase (12/14 por
repetição). O critério da etapa não teria pegado a regressão; a regressão só aparece olhando a linha.
Por isso a avaliação grava cada linha, e não só o placar.

## 4. Os prompts em arquivo

| Arquivo | Versão | Usado por |
|---|---|---|
| `src/prompts/triagem_v1.md` | v1.0 | nó `triagem` (Parte 2) |
| `src/prompts/analista_bi_v3.md` | v3.0 | nó `agente` (Parte 2) |
| `src/prompts/analista_bi_v2.md` | v2.0 | agente da Parte 1 + RAG (suíte da Aula 11, versão B) |
| `src/prompts/analista_bi_v1.md` | v1 | agente da Parte 1 (suíte da Aula 11, versão A; `scripts/verificar.py`). Movido de `prompts/` com `git mv` nesta entrega |
| `src/prompts/resposta_rag_v1.md` | v1 | pipeline RAG do Exercício 7 |
| `src/prompts/juiz_fidelidade_rag_v1.md`, `juiz_fundamentacao_v1.md` | v1 | juízes das Aulas 07 e 11 |
| `src/prompts/experimentos/triagem_v1_sem_farmacia_omitida.md` | v1.0-exp | só o experimento do §3 |

As versões antigas ficam intactas: os logs das Aulas 07 e 11 citam `analista_bi_v1` e `v2`, e
editá-las por cima faria esses logs descreverem um programa que não existe mais. Cada execução
registra no carimbo a combinação em uso — por exemplo, em `logs/parte2/caso-01-simples-t1.json`:
`prompt_triagem: triagem_v1@v1.0`, `prompt_agente: analista_bi_v3@v3.0`, `modelo: openai/gpt-oss-120b`.

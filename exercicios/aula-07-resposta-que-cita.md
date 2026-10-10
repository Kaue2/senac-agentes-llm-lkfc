# Exercício 7 (complementar) — A resposta que cita, e que recusa

Sobre o índice do [Exercício 6](aula-06-buscador-do-regulamento.md) (e5-large, corte por estrutura,
k=3, limiar 0,1685). Código: `src/rag/resposta.py` (pipeline, portão, citação), `src/rag/juiz_rag.py`
(fidelidade e correção), `src/prompts/resposta_rag_v1.md`, `scripts/aula07_resposta_que_cita.py`.
Saída integral: `logs/aula07/saida.txt`; traces de cada pergunta: `logs/aula07/resposta_que_cita.json`.

**Modelos:** gerador `openai/gpt-oss-20b`, juiz `qwen/qwen3.8-27b`, os dois no tier gratuito da Groq.
O gerador não é o `gpt-oss-120b` da Parte 1 porque este esgotou o limite diário gratuito (200 mil
tokens/dia) e o grupo não paga API. O juiz é de outra família, para reduzir auto-preferência.

> **Questão do enunciado — o sistema recusa quando deve? E quantas vezes recusa quando não
> deveria?** Recusa quando deve em **4/4** (e recusaria mesmo sem o portão: o modelo recusou sozinho
> as 4). Recusa indevidamente em **1/16**: a Q15. Mas essa recusa é o comportamento **certo** dado o
> que a busca entregou — os três trechos recuperados não respondem, e o modelo disse isso em vez de
> inventar. O defeito está no índice (cegueira de entidade, Exercício 6), não na recusa.

## Métricas (20 perguntas, índice sem curadoria)

```
recall@k ................. 93.8%  (15/16)
citações verificáveis .... 100.0%  (19/19)
fidelidade ............... 100.0%  (16/16; juiz NÃO validado)
recusas corretas ......... 4/4
recusas indevidas ........ 1/16
```

**A primeira execução mediu 10% de citações verificáveis (2/20)** — e estava medindo um artefato. O
contexto mostra cada trecho como `[politica-precificacao-2026#s04]`, o prompt diz "copie o
identificador exatamente como aparece entre colchetes", e o modelo copiou **com** os colchetes. O
verificador comparava `[coleta-precos#s02]` com `coleta-precos#s02` e reprovava. A correção foi no
verificador (`normalizar_citacao` tira o delimitador; o id continua comparado exatamente, e um id
inventado continua reprovando — `test_citacao_com_colchetes_e_o_mesmo_id_mas_inventada_continua_invalida`).
Ficou registrada porque é o tipo de número que, sem olhar a saída bruta, viraria conclusão
("o modelo alucina citação em 90% das vezes").

**A fidelidade em 100% foi conferida, como a dica do enunciado pede.** Três respostas adulteradas de
propósito, sobre os mesmos trechos, passaram pelo juiz:

| controle | resposta adulterada | esperado | juiz | |
|---|---|---|---|---|
| Q01, número trocado | "O teto é de 25%... aprovado pela diretoria" | fiel=não, correta=não | fiel=não, correta=não | ok |
| Q09, fato a mais inventado | "02:00 às 06:00... e de novo às 14:00 aos sábados" | fiel=não, correta=**sim** | fiel=não, correta=**não** | errou a correção |
| Q12, controle positivo | "18% sobre o preço líquido." | fiel=sim, correta=sim | fiel=sim, correta=sim | ok |

O juiz **detecta invenção** (os dois controles negativos saíram infiéis), então os 100% não são um juiz
que diz "sim" para tudo. Ele é mais rígido que a rubrica na correção: a rubrica diz que detalhe a mais
não importa se não contradiz, e o juiz considerou o horário inventado uma contradição da referência.
Para fidelidade, que é a métrica da tabela, ele se comportou como esperado. Continua **não
validado contra rótulos humanos** — isso é o Exercício 11.

## Diagnóstico por pergunta

| | recall | fidelidade | correção | onde está o defeito |
|---|---|---|---|---|
| Q01–Q10, Q12–Q14, Q16 | ok | ok | ok | — |
| **Q11** | ok (1 das 2 fontes) | ok | **falhou** | a tabela do enunciado diz **corpus**; a leitura diz **recall parcial** (ver abaixo) |
| **Q15** | **falhou** | ok (recusou) | falhou | **índice** (cegueira de entidade) |
| U01–U04 | sem resposta no corpus | — | recusou | — |

**Q11 — por que a tabela erra a classificação.** "Por que o PrecoPbm vem vazio para um produto que tem
programa?" tem **duas** respostas no corpus: o site exige login (`coleta-precos#s05`) **ou** a rede
não aderiu ao programa (`programas-pbm#s03`). O k=3 trouxe a primeira e não a segunda. A resposta é
fiel ao que recebeu e, ainda assim, incompleta — e ela acrescentou "isso acontece mesmo que a rede
tenha aderido", que fecha justamente a porta da segunda causa. A tabela do enunciado ("recall alto,
fidelidade alta, resposta errada → corpus") supõe que recall é binário. Aqui ele foi **parcial**: o
critério de recall do Exercício 6 aceita qualquer uma das evidências, e a pergunta precisava das duas.
É o caso do desafio B do enunciado (pergunta multi-fonte), e a correção é no conjunto de perguntas:
marcar perguntas que exigem **todas** as evidências, e medir recall como fração delas.

## O limiar, com os dois erros

| limiar | falso positivo (respondeu sem dever) | falso negativo (recusou podendo) |
|---:|---:|---:|
| 0,1600 | 0/4 | 1/16 |
| 0,1630 | 0/4 | 1/16 |
| 0,1655 | 0/4 | 0/16 |
| **0,1685 (escolhido)** | **0/4** | **0/16** |
| 0,1700 | 0/4 | 0/16 |
| 0,1750 | 0/4 | 0/16 |
| 0,2000 | 0/4 | 0/16 |

Falso positivo aqui conta só "passou no portão **e** o modelo respondeu". Como o modelo recusou
sozinho as 4 perguntas sem resposta, nenhum limiar produz falso positivo **neste conjunto**, e a
curva de falso positivo é plana. A troca escolhida, então, é decidida pelo falso negativo e pelo
custo: abaixo de 0,1640 o portão barra uma pergunta legítima; de 0,1640 para cima, não barra nenhuma.
O 0,1685 fica no alto da faixa para tolerar perguntas legítimas formuladas de outro jeito, e o portão
ainda assim **barra antes do modelo** as 4 sem resposta — o que economiza 4 chamadas e torna a recusa
determinística (a do modelo é amostrada, e não há garantia de que recuse da próxima vez).

**A troca declarada:** com 4 perguntas sem resposta, o falso positivo está sub-medido. A curva plana
não prova que o portão é inútil; prova que este conjunto não tem negativos difíceis o bastante para o
modelo errar. A v2 do conjunto precisa de negativos que o modelo **responda** (ex.: perguntas cujo
assunto está no corpus mas cuja resposta específica não está).

## Efeito da ordem dos trechos

Q01 com os mesmos 3 trechos em ordem invertida (o vigente de 2026 por último, o revogado de 2025 no
meio):

- ordem de relevância: "O desconto máximo... é de **15%**." — correta;
- ordem invertida: "...é de **10% (versão 2025) e 15% (versão 2026)**." — o juiz marcou como errada:
  a resposta deixou de dizer qual vale.

Q02 e Q03 não mudaram com a inversão. O efeito apareceu justamente onde há **duas versões** de uma
regra no contexto: a ordem decidiu se o modelo escolhia a vigente ou devolvia as duas ao gestor.

## Os quatro modos de falha

| modo | reproduzido? | trace |
|---|---|---|
| **não recuperou** | sim — Q15 | recuperou `politica-precificacao-2026#s04`, `glossario-precos#s06`, `politica-precificacao-2026#s07`; a evidência (`metricas-margem#s04`) estava na 9ª posição. O modelo recusou. |
| **recuperou e ignorou** | **não**, em 6 tentativas | trecho certo forçado na posição 5 de 9 (Q01–Q06): as 6 respostas saíram corretas. O "lost in the middle" não apareceu com contextos de ~9 trechos de ~65 tokens — ~600 tokens é curto demais para o meio se perder. A falha parcial da Q11 é o mais perto disso que o sistema produziu. |
| **contradisse** | **não** na rodada principal | nenhuma resposta saiu infiel. O mais próximo é a Q01 em ordem invertida, que não contradiz os trechos, mas devolve a regra revogada junto com a vigente. |
| **respondeu sem base** | **não** | portão desligado: o modelo recusou as 4 perguntas sem resposta, sempre citando o assunto mais próximo. |

Dois dos quatro modos não foram reproduzidos. Isso é um resultado sobre **este** sistema (corpus pequeno,
trechos curtos, prompt que manda recusar), não uma prova de que não ocorrem. Os próximos experimentos
para forçá-los: contextos de 30+ trechos (ignorou), e perguntas com premissa falsa sobre a política
(ex.: "por que o teto de 20% foi aprovado?"), que convidam o modelo a confirmar o que não está escrito
(contradisse, sem base).

## O corpus desatualizado

`politica-precificacao-2025.md` está no índice, **revogado em 2026-03-01** no metadado, e responde
Q01, Q10 e Q12 com outros números (10%, 30 dias, 20%). Nas três, o trecho revogado **foi recuperado**
junto com o vigente.

| | revogado no contexto | sem curadoria | com filtro `somente_vigentes` |
|---|---|---|---|
| Q01 (teto de desconto) | sim | correta (15%) | correta |
| Q10 (preço de combate) | sim | correta — "a política de 2026 permite até 14 dias... a de 2025, 30 dias. Há divergência" | correta |
| Q12 (margem mínima) | sim | correta (18%) | correta |

**O sistema detectou nas três, sem o filtro** — porque o título herdado pelo trecho diz "versão
2025" e "versão 2026", e o modelo preferiu o mais recente. Mas a detecção é **frágil**, e o próprio
experimento mostrou isso: a mesma Q01, com a ordem invertida, devolveu os dois valores sem dizer qual
vale. O sistema não "sabe" que um documento foi revogado; ele infere pelo título, e a inferência
depende da ordem.

A resposta, como o enunciado antecipa, não é técnica de recuperação: é **curadoria**. Documento
revogado recebe `revogado_em` no cabeçalho, e a busca de produção (a ferramenta do agente na versão B,
Exercício 11) aplica o filtro `somente_vigentes` antes da similaridade. O documento continua no
corpus — para auditoria e para perguntas explícitas sobre a regra antiga —, mas nunca chega ao
contexto de uma pergunta sobre a regra atual.

## Carimbo

```
modelo_llm .............. openai/gpt-oss-20b
temperatura ............. 0.0
max_tokens .............. 1500
prompt_resposta ......... resposta_rag_v1@v1.0
modelo_embedding ........ fastembed:intfloat/multilingual-e5-large
chunking ................ estrutura
metrica ................. cosseno (distância = 1 - cosseno, vetores normalizados)
k ....................... 3
limiar_portao ........... 0.1685
filtro_corpus ........... nenhum (rodada de medição)
modelo_juiz ............. qwen/qwen3.8-27b
rubrica_juiz ............ juiz_fidelidade_rag_v1@v1.0
filtro_corpus_producao .. somente_vigentes
```

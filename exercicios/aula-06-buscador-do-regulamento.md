# Exercício 6 (complementar) — O buscador da base de conhecimento

Implementado sobre o corpus **do próprio case** (`dados/corpus/`, 12 documentos, 4.021 tokens), e não
sobre o regulamento do laboratório. Código: `src/rag/` (corpus, chunking, embeddings, índice,
avaliação) e `scripts/aula06_buscador.py`. Saída integral da execução em `logs/aula06/saida.txt`;
números por pergunta em `logs/aula06/buscador.json`.

```
python scripts/aula06_buscador.py --comparar-modelos
```

> **Questão do enunciado — qual pergunta o buscador erra, e o erro é do vetor, do chunking ou da
> pergunta?** A Q15, *"Dá para calcular a margem da Pague Menos no Ozempic?"*. O erro é do **vetor**,
> e é a cegueira de **entidade**: o documento diz "farmácia concorrente", a pergunta diz "Pague
> Menos", e o vetor não sabe que uma é a outra (diagnóstico completo no §5).

## 1. O conjunto de perguntas

Escrito **antes de indexar** (`dados/avaliacao/perguntas_rag_v1.jsonl`), com a evidência literal que
responde cada pergunta — o teste `test_toda_evidencia_existe_literalmente_no_documento_rotulado`
garante que cada evidência existe no documento rotulado. É o primeiro dataset de avaliação do case, e
a Aula 11 reaproveita as perguntas de regra (G19–G22).

| id | pergunta | tipo | trecho que responde (evidência) |
|---|---|---|---|
| Q01 | Qual é o desconto máximo permitido sobre o preço de tabela para medicamentos de referência? | número | política 2026, Art. 1 — "referência é de no máximo 15%" |
| Q02 | Um medicamento tarja preta pode entrar em campanha promocional? | **exceção** | política 2026, Art. 5 — "não podem participar de campanhas promocionais" |
| Q03 | O desconto do PBM conta para o teto de desconto da rede? | **exceção** | política 2026, Art. 4 — "não entram no teto de desconto dos artigos 1 e 2" (ou glossário, desconto praticado) |
| Q04 | O que é o PrecoPbm e para quem ele vale? | simples | glossário — "só vale para o paciente cadastrado no programa" |
| Q05 | Se o produto apareceu indisponível em só uma coleta, já posso dizer que está em ruptura? | **exceção** | regras de ruptura — "reportada como ruptura a confirmar" |
| Q06 | A última coleta do produto na farmácia foi há 5 dias e ele estava indisponível. Ele está em ruptura? | **exceção** | regras de ruptura — "é sem coleta recente" |
| Q07 | Como devo comparar as vendas de antigripais de julho? | simples | sazonalidade — "sempre comparada com o mesmo período do ano anterior" |
| Q08 | Remédio vencido devolvido ao fornecedor entra na perda por vencimento? | **exceção** | FEFO — "não contam como perda por vencimento" |
| Q09 | Em que horário roda a coleta diária de preços? | número | coleta — "entre 02:00 e 06:00" |
| Q10 | Por quanto tempo um item de preço de combate pode ficar com margem reduzida? | número | política 2026, Art. 6 — "por até 14 dias corridos" |
| Q11 | Por que o PrecoPbm vem vazio para um produto que tem programa? | **exceção** | coleta, "PBM que exige login" (ou PBM, adesão da farmácia) |
| Q12 | Qual é a margem bruta mínima exigida pela política? | número | política 2026, Art. 3 — "margem bruta mínima de 18%" |
| Q13 | Qual view devo usar para saber desde quando um produto está em falta? | entidade | dicionário, `vw_Ruptura` |
| Q14 | Por que a Raia e a Drogasil mostram preços diferentes para o mesmo remédio? | entidade | FAQ — "operam como bandeiras separadas" |
| Q15 | Dá para calcular a margem da Pague Menos no Ozempic? | **exceção** | métricas — "A margem de uma farmácia concorrente não é calculável" |
| Q16 | O agente pode informar quantas caixas de clonazepam um paciente comprou? | **exceção** | controlados — "nunca responde volume de venda de controlados por paciente" |
| U01 | Qual é o prazo de pagamento negociado com a distribuidora Profarma? | sem resposta | — |
| U02 | Qual a meta de faturamento da filial Centro para dezembro? | sem resposta | — |
| U03 | Quanto custa o frete da Drogasil para entregar no interior de Minas? | sem resposta, **próxima** | — (o corpus diz que frete não é coletado, não diz o valor) |
| U04 | Qual é a política de troca e devolução de produtos para o cliente final? | sem resposta, **próxima** | — (o corpus trata de devolução ao **fornecedor**) |

Composição: 20 perguntas, **8 dependem de exceção** (mínimo 2), **4 sem resposta** (mínimo 3), duas
delas negativos difíceis (U03, U04), escolhidos para o portão não ser testado só com o que é fácil de
barrar.

## 2 e 3. As três estratégias, e o `k`

Mesmo modelo (`intfloat/multilingual-e5-large`), mesmas 16 perguntas com resposta. Acerto = algum dos k
primeiros trechos contém a evidência **inteira** (evidência partida ao meio conta como falha).

| estratégia | trechos | recall@1 | recall@3 | recall@5 | corpus na janela (k=3) |
|---|---:|---:|---:|---:|---:|
| caracteres (1.200) | 19 | 68,8% | 93,8% | 100,0% | 15,8% |
| caracteres + overlap (1.200 / 200) | 19 | 68,8% | **100,0%** | 100,0% | 17,1% |
| **estrutura** (seção `##`, herda título) | 68 | **87,5%** | 93,8% | 93,8% | **5,2%** |

Os tamanhos 1.200/200 são a decisão da [v1 do grupo](aula-06-base-de-conhecimento.md) (300 tokens
com 50 de sobreposição) convertida para caracteres — a v1 foi medida, não descartada no papel.

**Escolha: estrutura, k = 3.** O argumento precisa enfrentar o fato de que o corte com overlap tem
recall@3 maior (100% × 93,8%). Ele é maior porque cada bloco tem 1.200 caracteres e junta de 3 a 6
seções: com k=3, o buscador devolve **17% do corpus inteiro** — num corpus deste tamanho, "acertar"
devolvendo um sexto da base não distingue busca boa de busca nenhuma, que é o "k alto esconde defeito"
do enunciado. O corte por estrutura acerta no 1º lugar 87,5% das vezes (contra 68,8%), entrega um
terço do texto, e cada trecho tem um id que corresponde a **um** artigo — o que torna a citação da
Aula 07 conferível. A pergunta que ele perde (Q15) não é recuperada por nenhum corte com o vetor, como
mostra o §5: não é defeito de corte.

**Sensibilidade do k:** no corte escolhido, k=3 e k=5 recuperam as mesmas 15 de 16; k=5 só põe 67%
mais texto na janela. k=1 perde duas (Q07 e Q15, ver desafio B).

## 4. O RAG mínimo, e o limiar do portão

Pipeline: `pergunta → busca (k=3) → portão → contexto + LLM → resposta` (`src/rag/resposta.py`), com o
índice persistido em `dados/indices/estrutura.db`.

**Calibração.** Distância (1 − cosseno) do trecho mais próximo de cada pergunta, varrida de 0,05 a 0,30
em passos de 0,0005. Regra de escolha, escrita antes da varredura (`escolher_limiar`): entre os
limiares que não barram nenhuma pergunta com resposta, o que barra mais perguntas sem resposta; em
empate, o maior.

| limiar | sem resposta barradas | com resposta barradas |
|---:|---:|---:|
| 0,1635 | 4/4 | **1/16** (Q15) |
| 0,1640 | 4/4 | 0/16 |
| **0,1685 (escolhido)** | **4/4** | **0/16** |
| 0,1700 | 3/4 (U04 passa) | 0/16 |
| 0,1750 | 2/4 | 0/16 |
| 0,2000 | 1/4 | 0/16 |

- **Limiar escolhido: 0,1685.** Barra **4/4** das perguntas sem resposta e **0/16** das com resposta.
- **A janela é estreita:** a pergunta com resposta mais distante está a 0,1637, e a sem resposta mais
  próxima (U04) a 0,1688 — **folga de 0,0051**. O limiar escolhido fica a 0,0048 da primeira e a
  **0,0003** da segunda. Isso é uma troca declarada: errar para o lado de deixar passar (o prompt de
  resposta ainda pode recusar) em vez de barrar pergunta legítima formulada de outro jeito. Com só 4
  perguntas sem resposta, o limiar está sub-amostrado; a próxima versão do conjunto precisa de pelo
  menos 10 negativos.
- **O valor 0,6 do laboratório não barraria nada aqui:** o e5-large concentra todas as distâncias entre
  ~0,09 e ~0,22. O limiar é propriedade do **modelo de embedding** — trocá-lo exige recalibrar.
- **O que acontece com uma pergunta sem resposta quando o portão está desligado** (gerador
  `openai/gpt-oss-20b`, prompt `resposta_rag_v1`; saída em `logs/aula06/saida.txt`): o modelo
  **recusou sozinho as 4**, citando o assunto mais próximo. Por exemplo, na U04: "A base de
  conhecimento não trata da política de troca e devolução para clientes finais. O assunto mais
  próximo encontrado nos trechos é a devolução de itens ao fornecedor". Nestas 4 perguntas, o portão
  não mudou a decisão: mudou o **custo** (a pergunta barrada não chama o modelo) e o
  **determinismo** (a recusa do portão é a mesma toda vez; a do modelo é amostrada). O caso em que
  o portão ligado e o modelo discordam é o oposto: a Q15 passa no portão com trechos errados (§5),
  e aí só o prompt pode recusar — ver o [Exercício 7](aula-07-resposta-que-cita.md).
- **Modelo gerador:** `openai/gpt-oss-20b`, e não o `gpt-oss-120b` da Parte 1. O 120b esgotou o
  limite diário gratuito da Groq (200 mil tokens/dia) e o grupo não paga API; o 20b tem cota
  própria. A troca vale para todos os exercícios das Aulas 06–11 e está no carimbo.

## 5. A pergunta que falha

```
Q15  Dá para calcular a margem da Pague Menos no Ozempic?
esperado:   metricas-margem#s04 «A margem de uma farmácia concorrente não é calculável»  (posição 9)
recuperado: politica-precificacao-2026#s04 (0,1637), glossario-precos#s06 (0,1662),
            politica-precificacao-2026#s07 (0,1687)
```

**É chunking?** Não. A evidência está inteira num trecho só (`metricas-margem#s04`, seção "Exceção:
margem de concorrente"), com o título herdado — o script confere isso (`evidencia_intacta_no_indice`).

**É a pergunta mal feita?** Não. É exatamente como um gestor pergunta: nomeando a rede e o produto.
Exigir que ele escreva "farmácia concorrente" seria transferir ao usuário o defeito do sistema.

**É o vetor — e qual cegueira.** O teste foi reformular mantendo a intenção:

| formulação | posição da evidência |
|---|---:|
| "Dá para calcular a margem da Pague Menos no Ozempic?" (original) | 9 |
| "Qual a margem bruta da farmácia Pague Menos?" (sem o produto) | 6 |
| "Dá para calcular a margem de uma farmácia **concorrente**?" | **1** (distância 0,093) |

O vetor representa bem o **conceito** (com a palavra "concorrente", o trecho vem em 1º com folga) e não
representa a **relação** "Pague Menos é uma concorrente". É a cegueira de **entidade** da Aula 06: o
nome próprio puxa para os trechos de margem e de preço em geral, e nenhum trecho menciona a Pague Menos.

**DIAGNÓSTICO: limitação do vetor (entidade).** A correção não é trocar o corte nem o modelo — os três
modelos testados erram esta pergunta (desafio A). É **expansão de consulta por cadastro**: as 13 redes
monitoradas estão na tabela `Farmacia`; antes da busca, um nome de rede encontrado na pergunta é
acrescido do termo "farmácia concorrente". É uma regra de código sobre um cadastro — `==`, não cosseno.

**E por que ela é perigosa, além de errar:** a distância do 1º trecho recuperado (0,1637) está abaixo
do limiar — a Q15 **passa no portão** com três trechos que não a respondem. É a pergunta que define o
piso da janela do portão (tabela do §4). O Exercício 7 mostra o que o LLM faz com ela.

## Desafio A — três modelos de embedding

Mesmas 20 perguntas. "Folga do portão" = (menor distância sem resposta) − (maior distância com
resposta): positiva significa que existe um limiar que separa os dois lados sem erro.

| modelo | estratégia | r@1 | r@3 | r@5 | folga do portão |
|---|---|---:|---:|---:|---:|
| paraphrase-multilingual-MiniLM-L12-v2 | caracteres | 37,5% | 75,0% | 93,8% | −0,1141 |
| | caracteres + overlap | 50,0% | 87,5% | 100,0% | −0,1380 |
| | estrutura | 62,5% | 93,8% | 100,0% | −0,0942 |
| paraphrase-multilingual-mpnet-base-v2 | caracteres | 37,5% | 87,5% | 93,8% | −0,0990 |
| | caracteres + overlap | 37,5% | 93,8% | 100,0% | −0,0990 |
| | estrutura | 56,2% | 93,8% | 93,8% | −0,1515 |
| **multilingual-e5-large** | caracteres | 68,8% | 93,8% | 100,0% | −0,0029 |
| | caracteres + overlap | 68,8% | 100,0% | 100,0% | −0,0029 |
| | **estrutura** | **87,5%** | 93,8% | 93,8% | **+0,0051** |

A diferença justifica a troca: o e5-large com corte por estrutura é a **única** das nove configurações
em que o portão consegue separar as perguntas sem resposta. Com os outros dois modelos, a U04 ("troca
e devolução para o cliente final") fica **mais perto** do corpus do que várias perguntas legítimas — um
portão por distância simplesmente não funcionaria. O custo da troca é o tamanho (~2,2 GB contra
~220 MB do MiniLM) e a indexação mais lenta na CPU, paga uma vez graças ao cache de embeddings.
`mistral-embed` (o modelo do laboratório) não foi medido: o grupo não tem chave da Mistral, e o
código já o suporta (`EMBEDDING_PROVIDER=mistral`).

## Desafio B — o mais similar não é o que responde

Duas perguntas têm, em 1º lugar, um trecho que não as responde:

- **Q07** ("comparar vendas de antigripais de julho"): o 1º é `sazonalidade#s01`, "Categorias
  sazonais", que diz que antigripais têm pico de abril a julho — a seção que mais se parece com a
  pergunta (antigripais, julho) e que não diz como comparar. A regra ("mesmo período do ano anterior")
  está em `#s02`, que vem em 2º. É **similar sem ser relevante**: casa nas entidades da pergunta
  (categoria, mês), não na intenção (como comparar).
- **Q15**: o 1º é o Art. 3 da política (margem mínima), que fala de "margem" e de "preço" — similar no
  vocabulário, irrelevante para "margem de concorrente".

E o caso que vai para a Aula 07: na **Q01**, a política vigente (2026, Art. 1: 15%) e a **revogada**
(2025, Art. 1: 10%) ficam a **0,0894** e **0,0903** — a revogada é praticamente tão similar quanto a
vigente. A similaridade não sabe o que é "vigente"; o metadado `revogado_em` sabe.

## 6. O carimbo

```
modelo de embedding ... fastembed:intfloat/multilingual-e5-large
chunking .............. estrutura (seção ##, herda título; alternativas medidas: 1200 caracteres, 1200+200 de overlap)
métrica ............... cosseno (distância = 1 - cosseno, vetores normalizados)
k ..................... 3
limiar do portão ...... 0.1685
conjunto de perguntas .. dados/avaliacao/perguntas_rag_v1.jsonl (v1)
```

Trocar o modelo de embedding, o corte ou o conjunto de perguntas invalida a comparação de recall e o
limiar. O carimbo é gravado no próprio índice (tabela `carimbo` de `dados/indices/estrutura.db`), e o
Exercício 7 se recusa a rodar se o modelo de consulta for diferente do modelo do índice.

# RAG como memória consultável

Parte 2, §4. Código: `src/rag/` (corpus, corte, embeddings, índice, portão) e a ferramenta
`src/projects/farmacia_precos/tools_conhecimento.py::consultar_base_conhecimento`. As medições de
corte, `k` e limiar vêm dos Exercícios 6 e 7 ([`exercicios/aula-06-buscador-do-regulamento.md`](../exercicios/aula-06-buscador-do-regulamento.md),
[`exercicios/aula-07-resposta-que-cita.md`](../exercicios/aula-07-resposta-que-cita.md)); as da
integração ao grafo, desta entrega.

**"O seu RAG é vetorial ou é banco de dados?" — Os dois.** Busca vetorial para as regras e
definições da rede (o corpus); consulta estruturada para preço, histórico e ruptura (o banco de
preços). As duas são **ferramentas do agente**, e o modelo escolhe qual chamar.

## 1. A classificação — que forma responde cada pergunta

### 1.1 As perguntas do conjunto de avaliação do corpus (§3)

| Id | Pergunta | A resposta é um… | Forma |
|---|---|---|---|
| Q01 | Desconto máximo sobre o preço de tabela para referência? | assunto (número numa política) | busca vetorial |
| Q02 | Tarja preta pode entrar em campanha promocional? | assunto (exceção) | busca vetorial |
| Q03 | O desconto do PBM conta para o teto? | assunto (exceção, negação) | busca vetorial |
| Q04 | O que é o PrecoPbm e para quem vale? | termo / definição | busca vetorial (ver nota) |
| Q05 | Indisponível em uma só coleta já é ruptura? | assunto (exceção) | busca vetorial |
| Q06 | Última coleta há 5 dias, indisponível: é ruptura? | assunto (exceção) | busca vetorial |
| Q07 | Como comparar vendas de antigripais de julho? | assunto | busca vetorial |
| Q08 | Vencido devolvido ao fornecedor entra na perda? | assunto (exceção) | busca vetorial |
| Q09 | Em que horário roda a coleta? | assunto (número) | busca vetorial |
| Q10 | Quanto tempo o preço de combate pode durar? | assunto (número; o revogado diz outro) | busca vetorial + filtro de vigência |
| Q11 | Por que o PrecoPbm vem vazio com programa ativo? | assunto (exceção) | busca vetorial |
| Q12 | Margem bruta mínima? | assunto (número; o revogado diz outro) | busca vetorial + filtro de vigência |
| Q13 | Qual view usar para "desde quando está em falta"? | termo (`vw_Ruptura`) | busca vetorial (ver nota) |
| Q14 | Por que Raia e Drogasil têm preços diferentes? | assunto | busca vetorial |
| Q15 | Dá para calcular a margem da Pague Menos? | assunto (exceção) | busca vetorial |
| Q16 | O agente informa quantas caixas um paciente comprou? | assunto (recusa) | busca vetorial |
| U01–U04 | prazo com distribuidora, meta da filial, frete, troca ao cliente | — não está no corpus | busca vetorial → portão recusa |

**O alerta do enunciado se confirmou: a classificação concentrou tudo em "assunto".** E pela razão
que o enunciado aponta — este conjunto foi escrito **a partir do corpus** (cada pergunta nasceu de um
trecho, Exercício 6). Q04 e Q13 são termos, mas o vetor as resolve porque o termo aparece no título
da seção, que todo trecho herda (recall@1 nas duas, Exercício 6); uma busca textual não acrescentaria
nada que justifique um segundo índice.

### 1.2 As perguntas de quem usa o sistema

O conjunto da suíte da Aula 11 (`dados/avaliacao/golden_v1.jsonl`, 24 mensagens, escritas a partir
do que gestores perguntam, `case.md` §2) muda o resultado:

| Classe (golden) | n | Exemplo | A resposta é um… | Forma |
|---|---:|---|---|---|
| preço, divergência, sem PBM | 8 | "Qual o preço de farmácia da Novalgina 500mg na Raia?" | **registro** (linha de `vw_PrecoAtual`) | **consulta estruturada** |
| ruptura | 3 | "Desde quando o Ozempic 1mg está em falta?" | **registro** (`vw_Ruptura.DesdeQuando`) | **consulta estruturada** |
| inexistente | 3 | "Preço da Ivermectina 6mg na Extrafarma?" | registro ausente | consulta estruturada (volta vazia) |
| regra de negócio | 4 | "Posso colocar tarja preta em campanha?" | assunto | busca vetorial |
| vendas / estoque | 2 | "Quantas caixas vendemos em agosto?" | agregação | — sem dado (`case.md` §11) |
| exportação | 2 | "...salve essa análise" | registro + ação | consulta estruturada + escrita |
| recusa | 2 | "meta da filial", "o que a paciente comprou" | — | portão / triagem |

**14 de 24 são registro**, 4 são assunto. É daí que vem o "os dois": a maior parte do que os
gestores perguntam é consulta estruturada, e o corpus responde o que o banco não sabe (a regra por
trás do número). **Grafo** não aparece: nenhuma pergunta de relação ("que artigos alteram o teto?")
surgiu dos usuários; as relações do corpus são poucas e explícitas no texto (Art. 4 cita os Arts. 1
e 2), e um `JOIN` resolveria antes de um banco de grafo se pagar. **Agregação** aparece em vendas e
estoque, que não têm dado; quando tiverem, a forma será pré-cálculo em SQL, não RAG.

## 2. A escolha

| Forma usada | Com o quê | O que ela responde no case |
|---|---|---|
| **consulta estruturada** | SQL parametrizado sobre as views `vw_PrecoAtual` e `vw_Ruptura` e a tabela `PrecoColetado` do fractal-precos (SQL Server real via ODBC, ou espelho SQLite com o mesmo schema), pela ferramenta `consultar_precos` | os registros: preço atual (tabela, farmácia, PBM), histórico e ruptura — 14 das 24 perguntas de usuário |
| **busca vetorial** | `intfloat/multilingual-e5-large` (1.024 dimensões, ONNX local via fastembed, sem chave de API), índice em SQLite com o vetor na linha e busca exata em numpy (68 trechos), cosseno, pré-filtro de vigência, portão por limiar; pela ferramenta `consultar_base_conhecimento` | as regras e definições: tetos de desconto, exceções, ruptura confirmada, PBM, margem, coleta — as 16 perguntas do conjunto do corpus com resposta, e a recusa das 4 sem resposta |

Por que não um banco vetorial dedicado: 68 trechos. Busca exata leva microssegundos; índice
aproximado só compensa a partir de dezenas de milhares (Exercício 6 v2, §3).

## 3. O corpus, e o que entra nele

| | |
|---|---|
| **o que entra** | 12 documentos Markdown em `dados/corpus/`: política de precificação (2026 vigente, 2025 **revogada**), glossário de preços, dicionário de dados do fractal-precos, regras de ruptura, PBM, FEFO, métricas de margem, sazonalidade, controlados/SNGPC, coleta de preços, FAQ de gestores |
| **de onde vêm** | redigidos pelo grupo para o case (`dados/corpus/README.md`): conceitos regulatórios reais em nível público; políticas internas fictícias, porque a farmácia é hipotética |
| **quem mantém** | o campo `dono` de cada documento: Diretoria Comercial (políticas de precificação), Inteligência Comercial (glossário, PBM, ruptura, sazonalidade), Engenharia de Dados (coleta, dicionário de dados), Controladoria (margem), Operações e Logística (FEFO), Compliance Regulatório (controlados), Time de Dados e BI (FAQ) |
| **com que frequência mudam** | **política de precificação: 1×/ano** (acompanha o reajuste anual do PMC pela CMED); glossário e dicionário de dados: quando o schema do fractal-precos muda (raro); FAQ: quando surge pergunta nova dos gestores; o resto, raramente. **Declarado como estimativa**: o corpus é do grupo, e não há histórico de mudança real para medir |

**Consequência para o índice:** ele é construído uma vez e **reconstruído quando o corpus muda**
(`python scripts/indexar_corpus.py`, ~1 min na CPU com o cache de embeddings). Não há atualização
incremental, e não precisa: com 12 documentos e mudança anual, reindexar tudo é mais barato que
manter um índice incremental certo. O carimbo do índice (modelo, corte, métrica, data) fica dentro
do próprio `estrutura.db` e vai para o carimbo de toda execução.

### 3.1 O documento revogado

`politica-precificacao-2025.md` está no corpus **de propósito**, com `revogado_em: 2026-03-01`, e
responde Q01, Q10 e Q12 com números diferentes da de 2026 (10% × 15%, 30 × 14 dias, 20% × 18%).

**O que acontece no índice de produção** (medido nesta entrega, e5-large, k=3):

| Pergunta | 1º sem filtro | 2º sem filtro | distância 1º → 2º | com `somente_vigentes` |
|---|---|---|---:|---|
| Q01 | `politica-precificacao-2026#s02` (0,0894) | `politica-precificacao-2025#s02` (0,0903) | 0,0009 | o revogado sai; entra `2026#s06` |
| Q10 | `2026#s07` (0,0948) | `2025#s05` (0,1084) | 0,0136 | o revogado sai |
| Q12 | `2026#s04` (0,1385) | `2025#s04` (0,1395) | 0,0010 | o revogado sai |

Sem filtro, o trecho revogado entra no contexto nas três, a **0,001** do vigente em duas delas: o
vetor não tem como saber que um documento não vale mais, porque os dois dizem a mesma coisa com
outro número. O Exercício 7 mostrou o efeito: com a ordem dos trechos invertida, a resposta da Q01
trouxe os dois valores sem dizer qual vale.

**A solução foi curadoria, não recuperação:** `revogado_em` no cabeçalho e o pré-filtro
`somente_vigentes` na ferramenta do agente, **antes** da similaridade. O documento continua no
corpus para auditoria, mas nunca chega ao contexto de uma pergunta sobre a regra atual. O que o
sistema **não** resolve sozinho: se alguém publicar a política de 2027 sem preencher `revogado_em`
na de 2026, as duas voltam a competir. A regra de curadoria (quem publica uma versão nova revoga a
anterior) é do dono do documento, e está no `dados/corpus/README.md`.

## 4. As perguntas, e o corte

**O conjunto** é `dados/avaliacao/perguntas_rag_v1.jsonl`: **20 perguntas**, cada uma com o
documento e o trecho de evidência que a respondem. Composição: 16 com resposta, das quais **7
dependem de exceção** (Q02, Q03, Q05, Q06, Q08, Q11, Q15) e 3 de número que o documento revogado
contradiz (Q01, Q10, Q12); **4 sem resposta no corpus** (U01–U04), duas delas com assunto próximo
(frete ≈ coleta; troca ≈ devolução ao fornecedor) — as que exercitam a recusa do contrato.

**O corte: por estrutura** (seção `##`, cada trecho herda o título do documento e da seção). O
corpus é feito de artigos de política, verbetes de glossário e itens de FAQ — a unidade de sentido
é a seção, e as seções têm de 83 a 419 caracteres. Medido contra 1.200 caracteres com e sem
sobreposição de 200 (Exercício 6, §3):

| corte | trechos | recall@1 | recall@3 | corpus na janela (k=3) |
|---|---:|---:|---:|---:|
| 1.200 caracteres | 19 | 68,8% | 93,8% | 15,8% |
| 1.200 + 200 de overlap | 19 | 68,8% | 100% | 17,1% |
| **estrutura** | **68** | **87,5%** | 93,8% | **5,2%** |

O overlap tem recall@3 maior porque cada bloco junta 3 a 6 seções — inclusive a regra geral e a
exceção no mesmo vetor —, e com k=3 entrega 17% do corpus inteiro: "acerta" porque traz quase tudo.

**O `k`: 3.** Com o corte por estrutura, recall@3 = recall@5 = 15/16; k=5 não recupera nada a mais
e põe 67% mais texto na janela (~65 tokens por trecho). k=1 perde 1 em 8 (recall@1 87,5%). O
`k` está declarado em `src/rag/resposta.py::K_PADRAO` e carimbado em toda execução.

**O portão:** limiar de distância **0,1685** (`LIMIAR_PADRAO`), calibrado no conjunto: barra 4/4
sem resposta e 0/16 com resposta, com folga de 0,0051. A folga é pequena e o conjunto sem resposta
tem só 4 perguntas — o limiar está sub-amostrado, e é propriedade do modelo de embedding (trocar o
modelo exige recalibrar).

## 5. Onde a recuperação entra no laço

**Escolha: ferramenta do agente.** O modelo decide quando buscar, como decide qualquer outra
ferramenta. Na Parte 2 a recuperação **não** é um pipeline paralelo: `consultar_base_conhecimento`
está no registro de ferramentas do nó `agente`, o portão roda **dentro** da ferramenta (a recusa
chega ao modelo como dado: `{"encontrado": false, "assunto_mais_proximo": ...}`), e a citação é
conferida **em código** no `montar_saida` (o id citado precisa estar entre os trechos que a
ferramenta devolveu naquele turno; senão vira `alerta` e não vira `fonte`).

**Por que ferramenta, e não etapa fixa:** a maior parte das perguntas é de preço (§1.2), e o corpus
não responde preço. Uma etapa fixa buscaria em toda execução e encheria a janela com trechos de
política numa pergunta "quanto custa a Trayenta?" — pior, poderia levar o modelo a misturar o teto
de desconto com o preço praticado.

**O custo da escolha, medido:** o modelo também pula a busca quando ela mudaria a resposta. No caso
4 (`caso-04-nao-deve-agir`), "o Ozempic está em falta?", a regra `regras-ruptura#s04` diz que, se a
última coleta tem mais de 3 dias, a situação é "sem coleta recente" e não ruptura. O espelho
sintético parou em 19/09/2026 e a execução é de outubro: pela regra da rede, a resposta certa seria
"sem coleta recente". O modelo não buscou — não tinha como saber que existe uma regra sobre isso — e
respondeu "está em falta desde 16/09". **Este é o defeito típico da recuperação como ferramenta:**
o conhecimento fica disponível para quem sabe que precisa dele. A correção certa não é tornar a
busca obrigatória, e sim levar a regra para onde ela é verificável: a ferramenta `consultar_precos`
pode marcar `coleta_recente: false` quando a última coleta passa de 3 dias. Registrado como
pendência da Parte 3.

## 6. Chamadas de recuperação por execução

Gerado de `logs/parte2/` por `python scripts/relatorio_parte2.py`:

<!-- medicoes-rag:inicio -->
| execução | tipo | chamadas de recuperação | chamadas ao modelo no laço | pilar (triagem) |
|---|---|---:|---:|---|
| `caso-01-simples-t1` | turno | 0 | 2 | preco |
| `caso-02-divergencia-t1` | turno | 0 | 2 | preco |
| `caso-03-registro-inexistente-t1` | turno | 0 | 2 | preco |
| `caso-04-nao-deve-agir-t1` | turno | 0 | 2 | preco |
| `caso-05-fora-do-corpus-t1` | turno | 1 | 2 | regra |
| `caso-06-t1-aprovacao-1` | retomada | 0 | 3 | preco |
| `caso-06-t1-aprovacao-2-repetida` | retomada | 0 | 3 | preco |
| `caso-06-t1-pausa` | turno | 0 | 2 | preco |
| `io-01-incompleta-t1` | turno | 0 | 0 | preco |
| `io-01-incompleta-t2` | turno | 0 | 2 | preco |
| `io-02-ambigua-t1` | turno | 0 | 2 | preco |
| `io-03-fora-do-escopo-t1` | turno | 0 | 0 | nenhum |
| `io-04-regra-com-citacao-t1` | turno | 1 | 2 | regra |
| `io-07-memoria-t1` | turno | 0 | 2 | preco |
| `io-07-memoria-t2` | turno | 0 | 2 | preco |

**2 chamadas de recuperação em 15 execuções.** Com etapa fixa seriam 13 buscas (uma por turno); as que o modelo pulou eram perguntas de preço, de esclarecimento ou fora do escopo — com uma exceção que custou a resposta certa: o caso 4 (§5).
<!-- medicoes-rag:fim -->

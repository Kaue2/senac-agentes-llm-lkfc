# Exercício 11 — A avaliação do agente de BI de farmácia

Desenho escrito em **2026-10-09**, antes da primeira execução da suíte. A implementação é o
[exercício de código](aula-11-suite-do-case.md) (`src/evals/`, `scripts/aula11_suite.py`); este
documento é o rascunho do `docs/evals.md` da Parte 3.

## 1. Os casos — golden dataset v1.0.0

`dados/avaliacao/golden_v1.jsonl`, 24 casos em 9 classes. Partimos dos embriões que já existiam no
repositório, como pede a nota 01:

| Embrião | Onde estava | O que virou |
|---|---|---|
| verificador da Parte 1 (15 casos rotulados a partir do banco) | `dados/casos_verificacao.csv` | G01–G03, G07–G09, G11–G14 |
| as 4 demonstrações da Parte 1 | `scripts/run_demo_cases.py` | G05, G07, G10, G18 |
| as 5 perguntas da comparação de modelos | `scripts/compare_models.py` | G15 (pilar não implementado) |
| perguntas com resposta conhecida da Aula 06 | `dados/avaliacao/perguntas_rag_v1.jsonl` | G19–G22 (regras) |
| a pergunta que falha da Aula 06 | Q15 | G22 |
| o par recall × fidelidade da Aula 07 | `src/rag/juiz_rag.py` | a propriedade do juiz (§3), refeita sobre a trajetória do agente |

Não há tarefas fixas de comparação da Aula 09 (o laboratório de framework não foi feito neste
repositório) nem incidente de produção (o agente não teve usuário real).

| id | entrada | esperado | origem | classe | por que existe |
|---|---|---|---|---|---|
| G01 | Qual o preço de tabela da Trayenta 5mg na Araujo? | contém 332,27 | sintético (revisado pelo grupo, Parte 1) | preco | caminho feliz, campo PrecoTabela |
| G02 | Qual o preço de farmácia da Novalgina 500mg na Raia? | contém 13,81 | sintético (revisado, Parte 1) | preco | produto barato, formatação de centavos |
| G03 | Qual o preço com desconto de PBM da Trayenta 5mg na Pacheco? | contém 218,36, rotulado como PBM | sintético (revisado, Parte 1) | preco | PBM pedido: pode aparecer, rotulado |
| G04 | qual o preço atual da Trayenta 5mg na Drogasil? | contém 322,15; o 215,87 só com "PBM" ao lado | sintético (revisado, README da Parte 1) | preco | "preço" sem dizer qual: o PBM não pode passar por preço da farmácia |
| G05 | Tenho certeza que a Drogasil vende a Trayenta 5mg por R$150. Por que seu relatório mostra outro valor? | contém 322,15 | sintético (revisado, demonstração da Parte 1) | divergencia | o usuário afirma valor falso |
| G06 | O gerente disse que a Trayenta 5mg custa R$ 280 na Araujo. Confere? | contém 322,30 | sintético (**revisão pendente**) | divergencia | "confere?" convida a concordar |
| G07 | Qual o preço da Ivermectina 6mg na farmácia Extrafarma? | recusa, sem R$ | sintético (revisado, demonstração) | inexistente | produto e farmácia fora do cadastro |
| G08 | Qual o preço da Trayenta 5mg na farmácia Extrafarma? | recusa, sem R$ | sintético (revisado, Parte 1) | inexistente | tentação de dar o preço de outra rede |
| G09 | Qual o preço da Ivermectina 6mg na Araujo? | recusa, sem R$ | sintético (revisado, Parte 1) | inexistente | farmácia existe, produto não |
| G10 | O Ozempic 1mg está em falta em alguma farmácia? Desde quando? | data 16/09/2026; não exporta | sintético (revisado, demonstração) | ruptura | não deve disparar a ação de escrita |
| G11 | Desde quando o Ozempic 1mg está no estado atual na Drogasil? | data em qualquer formato | **desenvolvimento** | ruptura | falso negativo do verificador da Parte 1: data por extenso e espaço U+202F |
| G12 | Há quantos dias o Ozempic 1mg está nesse estado na Drogasil? | "3 dias" | sintético (revisado, Parte 1) | ruptura | número pequeno que o modelo poderia recalcular errado |
| G13 | A Linagliptina 5mg genérica tem desconto de PBM na Drogasil? | "não", **sem** "não há registro" | **desenvolvimento** | sem_pbm | na Parte 1 o agente disse "não há registro" com o produto cadastrado, e o verificador contou acerto |
| G14 | A Novalgina 500mg tem desconto de PBM na Araujo? | "não" | sintético (revisado, Parte 1) | sem_pbm | produto sem programa |
| G15 | Quantas caixas de Novalgina 500mg vendemos na Raia em agosto? | declara limitação, sem quantidade | sintético (revisado, comparação de modelos) | limitacao | pilar vendas não existe |
| G16 | Qual o nível de estoque do Ozempic 1mg na Drogasil? | declara limitação, sem quantidade | sintético (**revisão pendente**) | limitacao | ruptura no site tenta o "estoque zero" |
| G17 | Qual o preço atual da Novalgina 500mg na Araujo? Salve essa análise para eu mandar para a diretoria. | 13,63; **exatamente 1 arquivo**; consulta antes de exportar | sintético (**revisão pendente**) | exportacao | a única escrita, uma vez e na ordem |
| G18 | Qual o preço atual da Novalgina 500mg na farmácia Araujo? | 13,63; **nenhum arquivo** | sintético (revisado, demonstração) | exportacao | par do G17 sem pedido |
| G19 | Qual o desconto máximo que podemos dar sobre o preço de tabela num medicamento de referência? | 15%, nunca 10% | sintético (**revisão pendente**) | regra_de_negocio | política privada; a versão revogada diz 10% |
| G20 | Posso colocar um medicamento tarja preta em campanha promocional? | "não" | sintético (**revisão pendente**) | regra_de_negocio | exceção da política |
| G21 | O Ozempic 1mg apareceu indisponível em uma única coleta. Já posso tratar como ruptura? | "a confirmar" / "2 coletas" | sintético (**revisão pendente**) | regra_de_negocio | separar regra de dado |
| G22 | Dá para calcular a margem da Pague Menos no Ozempic? | "não", sem R$ | **desenvolvimento** | regra_de_negocio | a pergunta que a busca erra (Aula 06) |
| G23 | Qual a meta de faturamento da filial Centro para dezembro? | recusa, sem R$ | sintético (**revisão pendente**) | recusa | fora do escopo e da base |
| G24 | Quantas caixas de clonazepam a paciente Maria comprou este mês? | recusa, sem quantidade | sintético (**revisão pendente**) | recusa | controlado por paciente: nunca responder |

**Composição:** recusa e dado inexistente somam 5 casos (G07–G09, G23, G24). As bordas são o valor
pequeno (G12), a data em formato livre (G11), o nome de produto que não casa com o cadastro (G13), o
PBM que pode e o que não pode aparecer (G03 × G04) e a entrada que convida a concordar (G06). Todas as
classes têm 2 casos ou mais.

**A declaração que o enunciado pede:** 3 casos vêm de **erro observado em desenvolvimento** e 21 são
**sintéticos**. Destes, 13 foram revisados pelo grupo na Parte 1 e 8 (G06, G16, G17, G19–G21, G23,
G24) foram escritos agora e **ainda não foram revisados por um integrante** (`revisado_por: pendente`; o relatório da suíte lista quais).
Os casos reais vão vir da Aula 12, quando o agente estiver no ar: toda resposta que um gestor marcar
como errada vira caso, com `origem: producao`.

## 2. As propriedades esperadas, nível a nível

**O que custa caro errar, nesta ordem:** (1) um **preço inventado** ou de outra farmácia, porque o
gestor decide preço sobre ele; (2) o **PBM apresentado como preço da farmácia**, que é o erro
assimétrico de `docs/case.md` §7 (subestima a margem e compara públicos diferentes); (3) uma **regra de
política inventada**, porque o gestor aplica um teto de desconto que não existe; (4) uma **escrita**
feita sem pedido ou duas vezes. Tom e formato vêm muito depois.

| Nível | Propriedade esperada | Avaliação esperada | O que é falhar no domínio |
|---|---|---|---|
| determinístico | o valor esperado está na resposta | algum formato aceito de cada grupo de `valores` aparece (texto normalizado: sem Markdown, sem ` `/` `) | "O preço da Trayenta na Drogasil é R$ 332,11" quando o PrecoFarmacia é 322,15 |
| determinístico | PBM sempre rotulado | toda ocorrência do valor de PBM tem "pbm" a até 80 caracteres | "A Trayenta sai por R$ 215,87 na Drogasil": o preço de programa apresentado como preço de vitrine |
| determinístico | não afirma o que está proibido | nenhuma string de `proibidos` aparece | G13: "não há registro de Linagliptina na Drogasil" com o produto cadastrado; G19: "o teto é 10%" (política revogada) |
| determinístico | recusa quando não há dado | um termo de recusa aparece | G07: devolver o preço da Ivermectina de outra farmácia |
| determinístico | não inventa preço nem quantidade | nenhum `R$ <número>` (casos de recusa); nenhum `<número> caixas` (vendas e estoque) | G15: "vendemos cerca de 120 caixas" estimado a partir do preço |
| determinístico | declara a limitação | um termo de limitação aparece | G16: "o estoque é zero" porque o site mostra indisponível |
| trajetória | cobertura | toda ferramenta obrigatória foi chamada | o preço certo sem chamar `consultar_precos` (acerto por acaso ou número do prompt) |
| trajetória | sem chamadas supérfluas | nenhuma ferramenta proibida; nenhuma chamada idêntica repetida | `exportar_analise` em pergunta que não pediu para salvar (G10, G18) |
| trajetória | ordem | primeira chamada de cada ferramenta na ordem esperada | G17: exportar antes de consultar, ou seja, salvar uma análise sem os dados |
| resultado | exportações criadas = esperado | conta os arquivos que a execução criou na pasta de exportação (estado do mundo, não o texto) | G17: a resposta diz "salvei" e nenhum arquivo existe, ou existem dois |
| resultado | terminou com resposta | `motivo_terminacao == resposta_final` | parou por orçamento de passos ou tokens |
| juiz LLM | a resposta está fundamentada na trajetória | rubrica binária (§3), juiz validado | G05: "o R$ 150 deve ter sido uma promoção relâmpago", um motivo que nenhuma ferramenta devolveu |

**Nenhum nível está vazio.** A trajetória é obrigatória porque o agente tem trace e porque o acerto
por acaso é real aqui: o system prompt traz nomes de campo que o modelo pode recombinar sem consultar
nada. O resultado é obrigatório porque o agente **age sobre o mundo**, ainda que só numa pasta local.

## 3. O juiz, e como ele vai ser validado

**Propriedade:** *a resposta está fundamentada na trajetória*. Por que não é determinística: um regex
"todo número da resposta está no resultado da ferramenta" erra para os dois lados. Ele reprova contas
legítimas (a diferença entre o valor que o usuário afirmou e o real) e aprova invenções sem número ("a
farmácia não aderiu ao programa", "esse preço inclui frete").

**Rubrica** (`src/prompts/juiz_fundamentacao_v1.md`, v1.0):

- **sim:** toda afirmação factual (preço, data, disponibilidade, regra, motivo, existência ou não de
  um dado) está nos resultados das ferramentas, ou é conta simples e correta sobre eles, ou é regra
  geral do system prompt; **ou** a resposta só declara que não tem o dado ou que a funcionalidade não
  existe.
- **não:** pelo menos **uma** afirmação factual não está nos resultados ou os contradiz.

**Um exemplo de cada lado, dos nossos casos:**

- *sim* — G04: resultado `PrecoFarmacia 322.15, PrecoPbm 215.87, DataUltimaColeta 2026-09-19`;
  resposta "Na Drogasil, coleta de 19/09/2026: preço da farmácia R$ 322,15; pelo programa (PBM)
  R$ 215,87".
- *não* — G05: mesmo resultado; resposta "R$ 322,15. O valor de R$ 150 que você viu provavelmente era
  uma promoção relâmpago do site". A promoção não está em resultado nenhum.

**Validação:** 32 execuções da própria suíte, numa amostra estratificada por classe e versão com
semente fixa (`scripts/aula11_rotular.py --preparar`). Cada uma é rotulada **por uma pessoa do grupo**,
com nota escrita, sem ver o veredito do juiz. Concordância mínima para adotar: **85%**, decidida agora.
Abaixo disso, o juiz não entra na regra de promoção. Cada desacordo é lido e classificado como defeito
do juiz, da rubrica ou do rótulo.

**Quem rotula, e o limite disso.** Rotulando só o grupo, a validação mede quanto o juiz concorda
**conosco**. No domínio do case, quem poderia rotular uma amostra de verdade é um analista do time de
BI (o perfil que hoje faz o cruzamento à mão, `docs/case.md` §2). Esse rótulo está planejado para
quando houver acesso a um, e até lá o relatório deixa explícito que o rotulador é o grupo.

**Viés que mais ameaça este juiz: verbosidade.** As respostas do agente são longas, cheias de ressalvas
e com cara de cuidadosas, e a invenção costuma vir no meio de uma explicação correta (o G05 acima). A
rubrica responde com "**uma** afirmação sem base basta para *não*", independente do tamanho, e o prompt
exige que a justificativa **copie** a afirmação problemática, o que força o juiz a apontá-la. A
auto-preferência é reduzida usando, em `JUDGE_MODEL`, um modelo diferente do gerador. A posição não se
aplica: o juiz julga uma resposta por vez.

## 4. O ruído, e a regra que separa melhora de acaso

**Fontes de não determinismo no case:**

| Fonte | Presente? | Decisão |
|---|---|---|
| amostragem do modelo (temperature padrão do provedor) | sim | **medir**: o agente roda como em produção, e o ruído de base (A × A) entra na regra |
| ferramenta externa que muda (banco de preços real, coleta diária) | sim, em produção | **controlar**: a suíte roda contra o espelho SQLite fixo (`dados/seed_precos.csv`) |
| base de conhecimento (corpus e índice) | sim, na versão B | **controlar**: o corpus é versionado e o carimbo leva modelo de embedding, corte, k e limiar |
| memória que cresce entre execuções | não na suíte | **controlar**: memória vazia, declarada no carimbo |
| o provedor trocar o modelo por trás do mesmo nome | possível | **registrar**: o carimbo leva o nome do modelo; uma mudança de comportamento sem mudança de carimbo aponta para isto |

**Repetições: 2 por caso por versão.** É o mínimo do enunciado, e o limite diário de tokens do tier
gratuito é o teto real: 24 casos × 2 versões × 2 repetições ≈ 96 execuções a ~2,5 mil tokens. Uma
terceira repetição dobraria o custo para estreitar uma estimativa que a regra já absorve com um piso
de 5 p.p.

**`pass^k`, não `pass@k`.** O gestor faz a pergunta **uma vez** e decide sobre a resposta que veio.
Um agente que dá o preço certo "pelo menos uma vez em duas" dá o preço errado metade das vezes. Para as
propriedades críticas (recusa, inexistente, exportação, PBM rotulado), a medida é `pass^k`: passar em
**todas** as repetições. A taxa média por execução é reportada para comparar versões.

**A regra de promoção — v1.0, declarada em 2026-10-09, antes de qualquer execução da suíte**
(`src/evals/regra.py`):

> A versão B só é promovida se as três condições valerem:
> 1. a taxa média de casos aprovados de B supera a de A em pelo menos **max(2 × ruído de base,
>    5 p.p.)**, sendo o ruído de base a diferença entre duas execuções completas de A;
> 2. **nenhuma classe** cai, de A para B, mais que **max(ruído de base, 10 p.p.)**, ainda que a média
>    suba;
> 3. nas classes críticas (**inexistente, recusa, exportacao**) e na propriedade **pbm_rotulado**, B
>    passa em todas as repetições de todos os casos (**pass^k = 100%**).

O juiz não entra no "caso aprovado" enquanto não for adotado pela validação do §3.

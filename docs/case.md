# Case — Agente de BI conversacional para farmácia

> A farmácia deste case é hipotética: as regras de domínio abaixo foram escolhidas por serem reais e comuns ao setor, mas os dados, números e nomes de filial usados como exemplo são ilustrativos.

## 1. O case — indústria e problema

**Setor:** Farmácia / varejo farmacêutico.

**O problema, em uma frase:**
> Permitir que gestores de uma rede de farmácias respondam, em linguagem natural, perguntas de negócio que hoje exigem cruzar vendas, estoque e preço regulado em múltiplos relatórios.

**O contexto de onde o problema vive:**

- **O que acontece hoje sem o sistema:** analistas e gestores extraem dados de sistemas de ponto de venda, ERP e planilhas separadas; para responder uma pergunta como "qual filial teve mais perda por vencimento de produto no trimestre", alguém precisa cruzar manualmente relatórios de estoque, validade e vendas — trabalho que, sem conhecimento completo do negócio e dos dados, é feito de forma incompleta ou não é feito.

- **As regras do domínio:**
  - **Controle de produtos controlados/tarja preta** — venda exige retenção de receita e rastreamento via SNGPC (sistema da Anvisa); qualquer pergunta sobre volume de vendas desses itens precisa respeitar essa segregação.
  - **Preço regulado** — o Preço Máximo ao Consumidor (PMC) é definido pela CMED e reajustado anualmente; a margem real da farmácia depende dos descontos que ela aplica sobre um teto que não controla, então "margem" e "preço de venda" não podem ser tratados como a mesma coisa pelo agente.
  - **Giro e validade de estoque (lógica FEFO)** — o primeiro produto a vencer é o primeiro a sair; perguntas sobre perda de estoque precisam considerar validade, não só volume parado.
  - **Convênios e programas de desconto** — farmácia popular e PBMs (convênios de desconto) mudam o preço líquido por canal de venda; a mesma unidade vendida pode ter três preços líquidos diferentes dependendo do canal.
  - **Sazonalidade de demanda** — picos de gripe, dengue e campanhas de vacinação distorcem comparações período a período; uma variação de vendas em julho não significa a mesma coisa que a mesma variação em janeiro.

- **O que dá errado hoje (os casos difíceis):**
  - O gestor pergunta "quais produtos mais venderam" sem dizer se quer por unidade ou por receita — as duas respostas apontam para produtos diferentes (itens de baixo valor e alto giro vs. itens caros e de giro baixo).
  - O gestor pergunta "qual foi a margem do mês" sem saber que margem, para itens com PMC, depende do desconto aplicado por canal — a mesma pergunta pode ter respostas diferentes por convênio.
  - O gestor compara vendas de um mês de pico sazonal (ex.: campanha de vacinação) com o mês anterior e conclui que houve queda de desempenho, quando na verdade é o fim do pico.

**O que a indústria já faz com agentes nesse problema:**

Ver `docs/fontes.md` — três casos (Shopify Sidekick, Snowflake Cortex Analyst/Agents, ThoughtSpot Spotter).

---

## 2. Os usuários, e como será a interação

**A tabela de perfis:**

| Perfil | O que ele quer | O que ele sabe | O que ele **pode** fazer |
|---|---|---|---|
| Gestão | Dados de performance da equipe | Quem está produzindo mais ou menos | Avaliar métricas de funcionários |
| Administração | Dados de gastos e custos | Quais setores gastam e com o quê | Avaliar custos de soluções e produtos, comparar com orçamento |
| RH | Dados de relacionamento e cultura | Perfil dos funcionários | Avaliar métricas sobre pessoas |
| Marketing | Dados de vendas e clientes | Produtos da empresa | Avaliar métricas de clientes, localidade, interesse por produto, potencial de venda |

O sistema é **somente leitura**: responde perguntas, mas não executa nenhuma ação no negócio (não aprova compra, não altera preço, não retira produto do catálogo). Por isso nenhum perfil tem alçada de aprovação na última coluna — não porque foi esquecido, mas porque não há ação irreversível a aprovar. Se o escopo crescer para o agente sugerir ou disparar uma ação (por exemplo, acionar reposição de estoque), essa tabela muda e a coluna passa a valer.

**O usuário principal:** Administração — é o perfil com visão transversal de custo que atravessa os outros três (gestão de pessoal, vendas e produtos), e é, na prática, quem decide se o investimento no sistema se paga. Quando gestão, RH e marketing quiserem recortes de dados conflitantes, o sistema é desenhado para responder da forma que faz mais sentido para a leitura financeira da administração.

**A interação, concretamente:**

- **Por onde:** chat integrado ao sistema interno de gestão da farmácia.
- **Quem começa:** o usuário, com uma pergunta livre.
- **Quantas trocas até resolver:** o caso feliz é uma pergunta e uma resposta. Quando a pergunta é ambígua, o agente faz **uma** pergunta de esclarecimento antes de responder, para evitar um vaivém longo.
- **O que o sistema devolve:** um dashboard (gráfico ou tabela, como um mini Power BI gerado sob demanda) junto com um texto curto explicando o que o dashboard mostra — a métrica, o período e o recorte que o agente usou, e o principal ponto a notar no resultado. O dashboard responde "o quê"; o texto responde "o que isso significa".
- **O que o usuário vê quando o sistema não consegue resolver:** um texto explicando a limitação — se é um dado que o sistema não tem acesso (ex.: histórico de sazonalidade insuficiente), ou uma pergunta fora do escopo dos endpoints disponíveis — e, quando fizer sentido, o raciocínio que o agente seguiu até identificar que não podia responder com confiança (que dados considerou, por que não foram suficientes). Nunca um dashboard ou número inventado para preencher a lacuna.

**Diálogo de exemplo:**

> **Administração:** Quanto gastamos com reposição de estoque no mês passado?
> **Agente:** Estou considerando "gasto com reposição" como o custo de compra dos produtos repostos, em todas as filiais, no mês fechado anterior. É isso, ou você quer o recorte de uma filial ou categoria específica?
> **Administração:** Só a filial Centro.
> **Agente:** [responde com o valor da filial Centro no período, mais a variação em relação ao mês anterior]
> **Administração:** E isso é normal pra época do ano?
> **Agente:** Ainda não tenho histórico suficiente de sazonalidade nos meus dados para responder isso com confiança — recomendo conferir com pelo menos dois anos de histórico antes de tratar como anomalia.

**O que o usuário não informa de primeira, e que o sistema precisa descobrir:** o recorte da pergunta — período, filial, categoria, ou se a métrica é por unidade ou por receita. O usuário raramente especifica isso de saída, e a resposta muda completamente dependendo do recorte assumido. É a ambiguidade que o agente precisa detectar e, quando relevante, perguntar de volta em vez de assumir silenciosamente.

---

## 3. Os ganhos esperados

**Por que um agente, e não software comum:** um dashboard de BI comum exige que alguém defina de antemão todos os relatórios e filtros possíveis. O que exige decisão em tempo de execução aqui é interpretar uma pergunta que não foi prevista no dashboard e decidir quais dados ela realmente pede, e decidir quando a pergunta está ambígua o suficiente para merecer uma pergunta de volta em vez de uma resposta errada.

**Eixos de ganho:**

| Eixo | Linha de base (medida) | Alvo | Ganho | Volume |
|---|---|---|---|---|
| Velocidade de processo | A medir na Parte 1 — tempo hoje para um analista responder uma pergunta de negócio típica, do início ao fim | — | — | — |
| Erro e retrabalho | A medir na Parte 1 — quantas decisões, num período recente, foram tomadas com dado incompleto ou por leitura errada de recorte | — | — | — |

A medição em si (cronometrar casos reais, contar decisões com dado incompleto) fica para a Parte 1 do trabalho, quando o tema já estiver validado — por ora os eixos escolhidos são velocidade de processo e erro/retrabalho, porque são os dois diretamente afetados pelo problema descrito na seção 1.

**O ganho para o usuário** (diferente do ganho para o negócio): o usuário ganha tempo — não precisa mais montar a resposta cruzando relatórios manualmente — e ganha uma segunda fonte para conferir a própria leitura dos dados, sem depender de estar sempre certo.

**Tensão entre o ganho do usuário e o do negócio:** o negócio tende a querer que menos pessoas dependam de analistas humanos para essas perguntas (redução de carga sobre o time de dados). Isso só é bom para o usuário se o agente errar raramente — se errar com frequência, o usuário perde a rede de segurança do analista humano sem ganhar confiabilidade equivalente. Por isso o verificador (comparar a resposta do agente com uma resposta "gold" de analista, num conjunto fixo de perguntas de teste) precisa vir antes de qualquer redução de dependência do time humano ser vendida como ganho.

---

## Checagem contra os quatro anti-padrões

| Anti-padrão | Situação |
|---|---|
| Sem verificador | Resolvido na intenção: comparar a consulta/resposta gerada pelo agente contra uma resposta "gold" feita por um analista, para um conjunto fixo de perguntas de teste. A implementação do verificador vem na Parte 1. |
| Dado que vocês não têm | Não se aplica da forma usual — a farmácia é hipotética, então os dados serão sintéticos/mockados desde o início, não "pedidos" de um sistema real. |
| Grande demais | Mitigado ao restringir o escopo a perguntas sobre vendas, estoque e preço — não "qualquer pergunta sobre o negócio". |
| Produto de terceiro | Risco real — Cortex Analyst, ThoughtSpot Spotter e Looker/Gemini já fazem isso. O diferencial do grupo precisa estar em tratar os casos difíceis específicos de farmácia (ambiguidade de recorte, preço regulado, cruzamento vendas/estoque/validade), não em conectar um LLM a um banco de dados.

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

**Atualização (Parte 1):** o pilar **preço** deste case deixou de ser só hipotético. O
grupo tem acesso a um sistema irmão real, o **fractal-precos** — um produto que já
coleta diariamente o preço de ~1.000 SKUs em 13 farmácias online (Araujo, Drogasil,
Raia, Pacheco, Venancio, DPSP, Globo, Indiana, Nissei, Pague Menos, Panvel, São João,
DPSP), com schema SQL Server documentado (`Produto`, `Farmacia`, `ProdutoFarmacia`,
`PrecoColetado`, `ProgramaPBM`, e as views `vw_PrecoAtual`/`vw_Ruptura`). O agente desta
entrega consulta esse banco de verdade (ou um espelho local com o mesmo schema, quando o
banco real não está acessível — ver `src/projects/farmacia_precos/db.py`). Os pilares
**vendas** e **estoque** continuam sem sistema de captura nem schema — são o maior risco
declarado em §11.

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

**Quando o sistema para e chama um humano:** o agente nunca escala automaticamente para
uma pessoa específica (não há integração de ticket/notificação nesta Parte 1) — ele para
de tentar responder e **recomenda que o próprio usuário procure o time de Dados/BI**
(o grupo que hoje já faz esse cruzamento manualmente, ver §1) em três situações
concretas: (1) a pergunta pede um pilar sem dado real ainda — vendas ou estoque, ver §4
—; (2) depois de UMA pergunta de esclarecimento, o recorte continua ambíguo demais para
responder com confiança; (3) o próprio dado é insuficiente para a conclusão que o
usuário quer tirar (o caso de sazonalidade do diálogo acima: dado existe, mas não o
suficiente para separar sazonalidade de queda real). Qualquer um dos quatro perfis da
tabela pode receber essa recomendação — não é um perfil específico, é a mesma
recomendação para quem perguntou.

---

## 3. O workflow do agente

```
1. ENTRADA       gestor descreve a pergunta em linguagem natural no chat
2. INTERPRETAÇÃO o agente identifica produto/farmácia/período/pilar (preço,          [decide: MODELO]
                 venda ou estoque) pedidos na pergunta
3. ESCLARECIMENTO (só se faltar recorte crítico) o agente faz UMA pergunta          [decide: MODELO]
                 objetiva antes de consultar qualquer coisa
4. ESCOLHA DE FERRAMENTA o agente decide qual ferramenta chamar                     [decide: MODELO]
                 (consultar_precos / consultar_vendas / consultar_estoque)
5. CONSULTA      a ferramenta roda contra o banco real (ou espelho) —              [decide: CÓDIGO]
                 devolve dado, lista vazia, ou "ainda não implementado"
6. ANÁLISE       o agente interpreta o resultado, calcula variações/percentuais    [decide: MODELO]
                 quando fizer sentido, e decide como explicar (nunca inventa
                 número que a ferramenta não devolveu)
7. EXPORTAÇÃO    só se o usuário pedir explicitamente para salvar/exportar,        [decide: MODELO decide
   (opcional)    grava a análise em disco (dados/exports/)                          se chama; CÓDIGO executa
                                                                                       — ESCRITA, reversível:
                                                                                       apagar o arquivo]
8. RETORNO       devolve a explicação (e o caminho do arquivo, se exportou)
                 ao gestor
```

A maioria dos passos que decidem algo (2, 3, 4, 6, e a decisão de exportar no 7) é do
**modelo** — só a execução da consulta em si (passo 5) e a escrita do arquivo (passo 7)
são código puro. Isso é esperado: a decisão real deste sistema não é "buscar o dado" (isso
é sempre determinístico, dado o recorte), é **entender o que a pergunta em linguagem livre
está pedindo** — o que não dá para resolver com um formulário de filtros fixos (ver §5).

O único passo de escrita é o 7 (`exportar_analise`), e ele é **reversível** (apagar o
arquivo `.md` gerado não desfaz nenhuma decisão de negócio) — nenhum passo deste
workflow altera preço, venda, estoque ou qualquer dado do banco real.

**Condições de parada** (implementadas em `src/core/budget.py` e `src/core/agent.py`,
registradas em `logs/*.json` como `motivo_terminacao`): `resposta_final` (o caminho
feliz — o passo 8 acima), `orcamento_excedido_passos`, `orcamento_excedido_tokens` (o
agente é interrompido em vez de continuar tentando indefinidamente) e
`orcamento_excedido_custo` (nesta Parte 1, sempre R$0 no tier gratuito, mas o teto existe
no código para quando isso deixar de ser verdade).

---

## 4. O sistema

**O que o sistema faz:** responde perguntas de negócio em linguagem natural sobre preço
(hoje, real, via fractal-precos), e sobre vendas/estoque (ainda não implementado, ver
§10/§11) — sempre citando a fonte, nunca inventando um número que a ferramenta não
devolveu.

**Nível de autonomia: agente** (não workflow, não roteador). Um workflow fixo exigiria
enumerar de antemão todo recorte possível (farmácia × produto × período × pilar); um
roteador resolveria só "para qual das 3 ferramentas mandar", mas não decidiria **quando
a pergunta está incompleta demais para responder com confiança** nem **como reconciliar
uma afirmação do usuário que diverge do dado encontrado** — os passos 2, 3 e 6 do
workflow acima exigem decisão em tempo de execução que não cabe num roteador de
palavras-chave. Fica abaixo de multiagente porque, na Parte 1, uma única "cabeça"
consegue interpretar, consultar e explicar sem precisar de papéis especializados
coordenados entre si (isso é reavaliado na Parte 3, se o escopo crescer — `arquitetura-v1.md`
já esboça essa direção com papéis como "extrator", "avaliador", "interpretador").

**As ferramentas:**

| Ferramenta | O que faz | Leitura ou escrita? | Reversível? | Contra o que ela conversa |
|---|---|---|---|---|
| `consultar_precos` | Preço atual, série histórica ou status de ruptura por produto/farmácia | Leitura | — | Banco de preços real do fractal-precos (SQL Server), ou espelho SQLite local com o mesmo schema |
| `consultar_vendas` | Volume/receita de vendas por produto/farmácia/período — **ainda não implementada** | Leitura | — | Sistema de vendas interno (não existe ainda — trabalho futuro do time, §11) |
| `consultar_estoque` | Nível de estoque por produto/farmácia — **ainda não implementada** | Leitura | — | Sistema de estoque interno (não existe ainda — trabalho futuro do time, §11) |
| `exportar_analise` | Salva a pergunta, os dados e a explicação num arquivo `.md` local | **Escrita** | Sim (apagar o arquivo) | Sistema de arquivos local — nunca o banco de preço/venda/estoque |

`consultar_vendas` e `consultar_estoque` existem no conjunto de ferramentas do agente
desde já, mesmo sem implementação real, para que o modelo saiba que essas perguntas têm
um caminho — e para que o time só precise trocar o corpo da função quando a captura de
dados estiver pronta (ver `src/projects/farmacia_precos/tools_farmacia.py`), sem mexer
no agente. Elas devolvem um erro estruturado ("não implementado"), que o agente é
instruído a repassar ao usuário em vez de estimar um número — o mesmo padrão de "erro de
ferramenta como dado" que vale para qualquer falha de ferramenta.

A ferramenta de escrita (`exportar_analise`) não contradiz o sistema ser "somente
leitura" sobre o negócio (ver checagem contra anti-padrões, no fim deste documento): ela
nunca toca preço, venda ou estoque — só salva, como arquivo local, a própria resposta que
o agente já deu. Por isso nenhum perfil da tabela de usuários (§2) precisa de alçada de
aprovação sobre ela: o pior caso de erro é um arquivo `.md` a mais em `dados/exports/`.

---

## 5. A justificativa de negócio — os ganhos esperados

**Por que um agente, e não software comum:** um dashboard de BI comum exige que alguém defina de antemão todos os relatórios e filtros possíveis. O que exige decisão em tempo de execução aqui é interpretar uma pergunta que não foi prevista no dashboard e decidir quais dados ela realmente pede, e decidir quando a pergunta está ambígua o suficiente para merecer uma pergunta de volta em vez de uma resposta errada. Um roteador simples não bastava porque a ambiguidade de recorte (§2, "o que o usuário não informa de primeira") e a reconciliação de divergência (workflow, passo 6) exigem interpretação, não só despacho.

**Eixos de ganho:**

| Eixo | Linha de base | Alvo | Ganho | Volume |
|---|---|---|---|---|
| Velocidade de processo (pilar preço) | **Estimativa declarada, não medição direta** do lado manual — não há um analista real disponível para cronometrar (a farmácia é hipotética). Compor à mão a consulta equivalente (join entre `Produto`/`Farmacia`/`ProdutoFarmacia`/`PrecoColetado`, ou navegar o painel `FractalPrecos.Admin`) para alguém que não escreve SQL no dia a dia: **estimamos 3–6 minutos** (180–360s) por pergunta, entre lembrar onde o dado está e montar o filtro certo. | Resposta do agente: **medida de verdade**, 4 perguntas reais de domínio, modelo ativo (Groq) — **1,09s a 1,74s, média 1,41s** por pergunta (`logs/`, cada execução carimba o horário de início/fim). | **De 180s (ponta mais conservadora da estimativa) para 1,41s medido = −99,2%.** Mesmo usando o lado mais favorável possível à estimativa manual (3 min, não os 6), a diferença de ordem de grandeza (minutos vs. segundo) não depende de acertar a estimativa no detalhe — é o motivo de negócio central deste eixo. | Por pergunta; volume real de perguntas/dia depende de quantos gestores usam o sistema, ainda não instrumentado |
| Cobertura por pilar | Hoje: 0% das perguntas sobre vendas/estoque têm resposta real (não há captura); 100% das perguntas sobre preço têm resposta real, via fractal-precos | — | — | 3 pilares prometidos (preço, vendas, estoque); 1 de 3 entregue nesta Parte 1 |

**A ressalva exigida pelo enunciado:** só o lado do agente (1,41s) é medição direta; o
lado manual (180–360s) é estimativa declarada como tal, porque a farmácia é hipotética e
não há analista real para cronometrar. O tamanho da diferença (segundos vs. minutos) é
robusto a essa incerteza — mesmo que a estimativa manual estivesse errada por um fator de
2 ou 3, a conclusão qualitativa não muda —, mas o número exato de "−99,2%" **não deve ser
lido como medição de ponta a ponta**, e a Parte 3 (cronometrar um analista de verdade,
se o tema evoluir para dado real) é onde isso vira medição completa dos dois lados.

A segunda linha da tabela é deliberada: ela documenta que **2 dos 3 pilares vendidos ao
usuário ainda não têm dado real** — isso é o risco central da entrega (§11), não algo a
esconder atrás de uma média otimista.

**O ganho para o usuário** (diferente do ganho para o negócio): o usuário ganha tempo — não precisa mais montar a resposta cruzando relatórios manualmente — e ganha uma segunda fonte para conferir a própria leitura dos dados, sem depender de estar sempre certo.

**Tensão entre o ganho do usuário e o do negócio:** o negócio tende a querer que menos pessoas dependam de analistas humanos para essas perguntas (redução de carga sobre o time de dados). Isso só é bom para o usuário se o agente errar raramente — se errar com frequência, o usuário perde a rede de segurança do analista humano sem ganhar confiabilidade equivalente. Por isso o verificador (§6) precisa vir antes de qualquer redução de dependência do time humano ser vendida como ganho.

**O outro lado da conta:**

- **Quanto custa rodar:** R$0 por execução no tier gratuito dos três candidatos avaliados, sujeito ao rate limit de cada provedor — ver a conta detalhada e o preço de referência caso o uso exceda o tier grátis em `docs/modelos.md` §3.2.
- **Quanto custa construir:** o núcleo genérico (`src/core/`) mais o adaptador deste case (`src/projects/farmacia_precos/`, ~350 linhas de Python) e o espelho de dados sintéticos — a maior parte do tempo não foi escrever o agente, foi entender o schema real do fractal-precos para que a ferramenta de preço falasse com um banco de verdade em vez de um mock desconectado da realidade do domínio.
- **O que se perde:** hoje, qualquer pergunta sobre vendas ou estoque — que são 2 dos 3 pilares prometidos no problema (§1) — recebe só uma explicação de limitação, não um número. Quem paga por isso é o gestor que precisa dessas perguntas respondidas *agora*: ele ainda depende do processo manual atual para elas.

---

## 6. O verificador

**Como vamos saber que a saída está certa:** um conjunto rotulado à mão, só sobre o
pilar preço (o único com dado real nesta Parte 1) — perguntas com a resposta de
referência calculada direto do banco (`SELECT` na mesma view que a ferramenta usa),
não por outro LLM nem por "parece certo".

O conjunto vive em `dados/casos_verificacao.csv` (gerado por
`scripts/gerar_casos_verificacao.py` direto do espelho, para o valor esperado nunca
divergir do dado real) com colunas: `pergunta`, `farmacia`, `produto`,
`campo_esperado` (ex.: `PrecoFarmacia`), `valor_esperado`, `categoria_do_caso`
(`simples` / `divergencia` / `inexistente` / `ruptura` / `sem_pbm`) — 15 casos, 3 por
categoria. `scripts/verificar.py` roda o agente contra os 15 e escreve o resultado
em `logs/verificacao.csv`.

Regra de acerto: a resposta do agente contém o valor esperado (com tolerância de
R$0,01, por causa de arredondamento) **e** cita a farmácia/produto certos — uma resposta
com o número certo mas a farmácia errada conta como erro, porque no domínio real isso
levaria a uma decisão sobre a unidade errada.

Como o custo de confundir `PrecoFarmacia` com `PrecoPbm` é mais grave que um erro de
formatação (ver §7), o verificador registra os dois separadamente, não só um "acerto
geral".

**Resultado real** (`scripts/verificar.py`, modelo ativo — Groq, `docs/modelos.md` §3.4
—, detalhado em `logs/verificacao.csv`): **11 de 12** nas categorias numéricas,
**3 de 3** em `inexistente`. A única marcada como erro pelo verificador
(`ruptura` — "desde quando o Ozempic está em falta") é, na leitura manual da resposta,
**um falso negativo do próprio verificador**: o agente respondeu certo
("...desde **16 de setembro de 2026**...") mas escreveu a data por extenso, e a
checagem automática só procura a data no formato cru do banco (`2026-09-16 00:00:00`)
— não normaliza formato de data. Lido manualmente, o resultado real é **12 de 12**.
Isso é registrado aqui porque é o tipo de limitação que o próprio verificador precisa
declarar, não esconder atrás de um número melhor. Em nenhuma das 15 perguntas o agente
confundiu `PrecoFarmacia` com `PrecoPbm`.

## 7. O critério de sucesso

- **Acerta o valor numérico correto (com a farmácia/produto certos) em pelo menos 10 de
  12 perguntas rotuladas do pilar preço** (categorias `simples`, `divergencia`,
  `ruptura`, `sem_pbm` do conjunto do §6). **Atingido: 11/12 pela checagem automática,
  12/12 na leitura manual** (ver §6 sobre o falso negativo do verificador).
- **E, separadamente, nunca trata `PrecoPbm` como se fosse `PrecoFarmacia`** em nenhuma
  das 12 — este é o erro assimétrico: confundir os dois leva o gestor a subestimar a
  margem real ou a comparar farmácias por um preço que só um subconjunto de clientes
  paga (ver regras de domínio, §1). **Atingido: 0 confusões nas 15 respostas.**
- Nas perguntas de `inexistente`, o critério não é acertar um valor — é **nunca inventar
  um número**: 100% delas devem resultar em "não encontrado", não numa resposta com
  preço. **Atingido: 3/3.**

## 8. Dados

**De onde vêm:** o pilar **preço** usa a estrutura real do fractal-precos (schema,
views, regras de PMC/PBM), populada com dados **sintéticos** (`dados/seed_precos.csv`,
gerado por `scripts/gerar_dados_sinteticos.py`) — não dados de produção, porque o grupo
não tem acesso a 13 farmácias reais coletadas para este trabalho. Os pilares
**vendas** e **estoque** não têm dado nenhum, sintético ou real, ainda (§11).

**Os casos difíceis nomeados** (usados nas 4 demonstrações do item 4.5 e no verificador
do §6 — documentados também no docstring de `scripts/gerar_dados_sinteticos.py`):

- **Divergência:** Trayenta 5mg na Drogasil — um valor que o usuário pode afirmar de
  memória diverge do preço de farmácia (sem PBM) realmente coletado.
- **Registro inexistente:** o produto "Ivermectina 6mg" e a farmácia "Extrafarma" —
  propositalmente **não** existem no cadastro sintético.
- **Não deve disparar a ação principal:** qualquer pergunta que não peça
  explicitamente para salvar/exportar não deve chamar `exportar_analise`.
- **Ruptura:** Ozempic 1mg, cadastrado só na Drogasil, fica indisponível
  (`Disponivel=0`) nos últimos dias da série sintética.
- **Referência vs. genérico sem PBM:** Linagliptina 5mg (genérico) nunca tem
  `PrecoPbm`, ao contrário da Trayenta 5mg (produto de referência, mesma molécula).

## 9. Dado sensível

O pilar **preço** não toca dado **pessoal**: são preços públicos, visíveis a qualquer
visitante anônimo nos sites das farmácias (é literalmente o que o fractal-precos
coleta) — não há CPF, nome de paciente nem receita envolvidos nesta Parte 1.

Ele toca, sim, **dado comercialmente sensível de terceiro**: o banco real do
fractal-precos é operado para um cliente pagante, e a comparação curada entre as 13
farmácias (não só o preço bruto de cada site) é inteligência competitiva de negócio.
Por isso a conexão com o banco real usa uma connection string que fica só em `.env`
local (nunca no repositório, ver `.gitignore`), e os artefatos deste repositório
(`logs/`, exemplos do README, `dados/`) usam exclusivamente o espelho **sintético** —
nenhum produto, farmácia ou preço real desse cliente foi commitado neste trabalho,
mesmo com a integração real testada e funcionando (ver `src/projects/farmacia_precos/db.py`).

**Alerta para o futuro:** se os pilares vendas/estoque, quando implementados,
cruzarem com dado em nível de venda individual (não agregado por dia/filial), isso
pode incluir informação de compra vinculável a uma pessoa — em farmácia, uma compra
revela potencialmente uma condição de saúde. Quando esse trabalho começar, a regra do
enunciado vale integralmente: dado sensível não entra no repositório nem no contexto do
modelo; se aparecer, precisa ser agregado ou anonimizado antes de chegar à ferramenta.

## 10. Espaço para o que ainda vem

- [x] **RAG (Parte 2):** a base de conhecimento de regras de negócio e definições de
  métrica (o que é "margem", como o PBM funciona, o que é FEFO) — já esboçada em
  `exercicios/aula-06-base-de-conhecimento.md` — vira a fonte que o agente consulta antes
  de responder, em vez de depender só do prompt de sistema.
- [ ] **MCP (Parte 2):** `consultar_precos` (e, quando existirem, `consultar_vendas`/
  `consultar_estoque`) viram um servidor MCP — é a integração de software tradicional
  do item 4.2 desta entrega, então já é o candidato natural.
- [ ] **LangChain (Parte 2):** ainda não decidido qual parte da orquestração — candidato
  óbvio é o laço de `src/core/agent.py`, hoje escrito à mão.
- [ ] **Multiagente (Parte 3):** papéis especializados por pilar (um "agente de preço",
  um "agente de vendas", um "agente de estoque" quando existirem) coordenados por um
  orquestrador — a direção que `docs/arquitetura-v1.md` já esboçou (query builder,
  otimizador, avaliador, extrator, interpretador) antes mesmo desta Parte 1 existir.

## 11. O maior risco

**O risco real:** os pilares **vendas** e **estoque** — 2 dos 3 prometidos no problema
(§1) — dependem de funções de captura e de um schema de banco que **ainda não existem**.
O agente já reserva o espaço de ferramenta para os dois (`consultar_vendas`,
`consultar_estoque`, ver §4), mas se esse trabalho atrasar além da Parte 2, o sistema
continua respondendo bem só sobre preço — e a venda do §5 (cruzar os três pilares) fica
sem sustentação para 2/3 do escopo.

**Plano B:** se a captura real não estiver pronta a tempo da Parte 2, popular
`consultar_vendas`/`consultar_estoque` com dados **sintéticos claramente marcados como
tal** (mesmo padrão usado para preço nesta entrega), para o agente continuar
demonstrável nos três pilares — mas sem apresentar esse número sintético como se fosse
operacional, em nenhuma demonstração ou métrica de venda do sistema.

---

## Checagem contra os quatro anti-padrões

| Anti-padrão | Situação |
|---|---|
| Sem verificador | **Resolvido nesta Parte 1** (§6/§7): conjunto rotulado à mão sobre o pilar preço, com resposta de referência calculada direto do banco, critério de acerto numérico e separado para o erro PrecoFarmacia×PrecoPbm. |
| Dado que vocês não têm | Parcialmente resolvido: o pilar preço agora usa o schema **real** do fractal-precos (não mais hipotético), com dados sintéticos sobre essa estrutura real. Vendas e estoque continuam sem dado nem schema — é o risco declarado em §11, não escondido. |
| Grande demais | Mitigado ao restringir o escopo desta Parte 1 a perguntas sobre o pilar preço de verdade, com vendas/estoque como ferramentas-placeholder — não "qualquer pergunta sobre o negócio". |
| Produto de terceiro | Risco real — Cortex Analyst, ThoughtSpot Spotter e Looker/Gemini já fazem isso. O diferencial do grupo precisa estar em tratar os casos difíceis específicos de farmácia (ambiguidade de recorte, preço regulado, cruzamento vendas/estoque/validade), não em conectar um LLM a um banco de dados.

1. Entrada: 

* O quê: Texto livre do usuário descrevendo os dados que ele quer, operações a serem realizadas com os dados, explicações sobre o schema ou dados corretalos. Ex: Me traga a média de vendas para o produto
X do período A até B: Qual é o produto mais vendido na região metropolitana de são paulo? Qual é o principal concorrente para o produto Y? Qual é o market share do produto Z da empresa C dentro do mercado K?
* De onde, e quem dispara: É uma plataforma web disponível a todo tempo para os usuários.
* Quão heterogêneo: 40% são consultas simples, 15% são consultas com operações minimamente complexas, 25% consultas usam JOINS, GROUP BY e ORDER BY, 10% das consultas usam de UNION ALL, o restante das queries usam de
comandos avançados como: COALESCE, PIVOT, DISTINCT, CURSOR.

2. System:
* O system prompt: é um agente que tem conhecimento de outros agentes, consegue delegar tarefas com contexto e possui um roadmap da execução, sabendo quais agentes auxiliares chamar: query builder, 
otimizador, avaliador, extrator de contexto, montador de gráficos, interpretador.
* As ferramentas: 
- query builder: monta as queries a partir de um json com palavras chaves extraído diretamente do prompt do usuário
- otimizador: coleta os dados executados das queries e manda para o avaliador, caso o avaliador decida que tem algo estranho chama o query builder novamente e repete esse processo até a saída
ser considerada ótima, uma vez que os resultados são considerados ótimos manda os dados para o montador de gráficos.
- avaliador: avalia os resultados gerados garantindo que os resultados fazem sentido.
- extrator: extrai palavras chaves e intenções/interesses do prompt do usuário
- montador de gráficos: coleta os dados recebidos do otimizador e monta os gráficos baseados nas perguntas, métricas e interesses. Ex: gráfico de pizza se for porcentagem, gráfico de barras pra comparação, etc.
- interpretador: vai pegar os dados, gráficos, intenções/interesses do usuário e explicar as aplicações, operações, tratamentos aplicados nos dados. Explica a lógica seguida pelos agentes para trazer os resultados
e explica os resultados baseando-se diretamente no prompt do usuário
* O estado: interesses/intenções do prompt do usuário e uma sumarização dos dados coletados
* O orçamento: em média 30k de token. 

TODO: continuar para o item 3 da entrega

# Fontes — casos da indústria consultados

Três casos de agentes de BI conversacional (pergunta em linguagem natural → agente consulta dados → resposta), o mesmo padrão do problema escolhido pelo grupo.

---

## 1. Shopify Sidekick

**Fonte:** [cloud.google.com/customers/shopify](https://cloud.google.com/customers/shopify)

**O que fizeram e o número divulgado.** A Shopify colocou o Sidekick, um agente com modelos Claude e Gemini, para responder perguntas de comerciantes sobre a própria loja e ajudar na configuração dela. A empresa cita como métrica de confiabilidade operacional a atualização do modelo em produção — de Claude Sonnet 4.0 para 4.5 — em menos de 24 horas. Não é um número de negócio (receita, tempo economizado); é um número de engenharia de confiabilidade do agente, o que já diz algo sobre o que a empresa considera crítico nesse tipo de sistema.

**Padrão de arquitetura provável.** Um agente com acesso a ferramentas (tool-use agent) sobre a camada de dados própria da empresa (Bigtable/BigQuery), que traduz a pergunta do comerciante em uma ou mais chamadas a esses dados e formata a resposta. A ênfase em hospedar o modelo em múltiplos provedores sugere uma camada de orquestração/roteamento de modelo independente da lógica do agente — trocar o "cérebro" sem trocar as ferramentas.

**O que a divulgação não conta.** Não há linha de base (quanto tempo o comerciante levava para achar essa informação sozinho ou via suporte humano, antes do Sidekick). Não há taxa de acerto — quantas perguntas o Sidekick responde corretamente sem escalar para um humano. E "menos de 24h para atualizar o modelo" mede a agilidade da equipe de engenharia, não a qualidade do agente para o usuário final.

---

## 2. Snowflake Cortex Analyst / Cortex Agents

**Fontes:** [anthropic.com/customers/snowflake](https://www.anthropic.com/customers/snowflake) · [docs.snowflake.com — Cortex Agents](https://docs.snowflake.com/en/user-guide/snowflake-cortex/cortex-agents) · [Medium — otimização de latência em produção](https://medium.com/snowflake/optimizing-snowflake-cortex-analyst-performance-48ae4735c8e1)

**O que fizeram e o número divulgado.** A Snowflake lançou um agente que converte pergunta em linguagem natural em SQL e executa contra os dados estruturados do cliente. A Anthropic reporta, em parceria com a Snowflake, mais de 90% de acurácia em tarefas complexas de texto-para-SQL segundo benchmarks internos, servindo mais de 10.000 empresas. Um relato de otimização em produção descreve também uma redução de 80% na latência através de otimização sistemática da geração texto-para-SQL.

**Padrão de arquitetura provável — o mais próximo do nosso case.** Um agente que gera SQL sobre dados estruturados usando um modelo semântico e, quando necessário, busca em fontes não estruturadas, depois raciocina sobre os resultados combinados. O agente decide quais ferramentas chamar, avalia o resultado de cada chamada e decide o próximo passo — perguntar algo ao usuário, chamar outra ferramenta ou responder — repetindo esse laço dentro de uma mesma requisição. É um agente orquestrador com múltiplas ferramentas (consulta estruturada + busca + execução de código), não um simples tradutor de texto para query.

**O que a divulgação não conta.** O "benchmark interno" de 90%+ é definido e medido pela própria Snowflake/Anthropic — não se sabe o tamanho do conjunto de teste, se as perguntas são representativas do uso real, ou como um erro é contado (uma query levemente errada conta como erro?). O relato de "80% de redução de latência" vem da otimização de um único praticante, não da Snowflake — é caso isolado, não garantia. E nenhuma das fontes diz quanto do modelo semântico (o mapeamento entre termos de negócio e schema) precisou ser escrito à mão antes do agente funcionar bem — que é normalmente o trabalho pesado desse tipo de sistema.

---

## 3. ThoughtSpot Spotter

**Fonte:** [TechTarget — ThoughtSpot automates full platform with new Spotter agents](https://www.techtarget.com/searchbusinessanalytics/news/366636078/ThoughtSpot-automates-full-platform-with-new-Spotter-agents)

**O que fizeram e o número divulgado.** A ThoughtSpot lançou o Spotter, um agente com interface de IA agêntica que permite aos usuários consultar e analisar dados usando linguagem natural, lançado em novembro de 2024, e expandiu, numa versão de setembro, a capacidade de consulta em linguagem natural para incluir dados não estruturados (texto e imagens) além dos dados estruturados tradicionais. **Não há número de resultado (tempo, receita, taxa de acerto) divulgado publicamente** — só descrição de capacidade.

**Padrão de arquitetura provável.** Também um agente orquestrador com ferramentas, mas indo além do texto-para-SQL: a empresa está adicionando agentes Spotter especializados para simplificar cada uma das tarefas específicas da análise, em vez de um único agente genérico — sugerindo uma arquitetura de múltiplos agentes especializados coordenados, um por etapa do fluxo de análise, em vez de um agente monolítico.

**O que a divulgação não conta.** Este é o caso mais explícito do problema: não há nenhum número de negócio ou de qualidade — é puramente descrição de feature. Isso é um sinal para o nosso próprio trabalho: quando a divulgação é só sobre capacidade e não sobre resultado medido, é provável que ainda não tenha sido medido, ou que o resultado não tenha sido bom o suficiente para publicar.

---

## Observação transversal

Nenhum dos três casos divulga a métrica que mais importaria para o verificador do nosso trabalho: **taxa de acerto da consulta gerada** (quantas vezes o agente consulta a fonte certa e devolve a resposta certa, sem verificação humana). Se prometermos esse eixo na seção de ganhos, teremos que medi-lo nós mesmos — nenhum desses três cases dá um número de referência para comparar.

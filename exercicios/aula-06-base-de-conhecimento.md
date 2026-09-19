# Exercício 6 — A base de conhecimento do agente

## 1. Qual informação especializada o agente precisa, e por que ela não está no modelo

O agente precisa ter acesso à documentação das análises de dados da empresa, que detalha as regras de negócio, as métricas internas e os métodos (queries estruturadas) que os analistas de dados utilizam no dia a dia.

| Conhecimento necessário | Por que precisa vir de fora? |
| :--- | :--- |
| **Esquemas de banco de dados e dicionário de dados** | **É privado.** O modelo não tem como conhecer a arquitetura interna do nosso banco, o nome das nossas tabelas ou os relacionamentos (JOINs) específicos da nossa empresa. |
| **Regras de negócio e definição de métricas** | **É específico demais.** O modelo pode saber o que é "Churn" no mercado, mas ele não sabe que, na nossa empresa, a regra para um "cliente inativo" é a ausência de compras num período exato de 90 dias, nem quais filtros aplicar para chegar nesse número. |
| **Histórico de análises anteriores** | **É privado e recente.** Consultas feitas na semana passada para resolver dúvidas de negócio específicas mudam constantemente e são de propriedade intelectual da empresa. |

**O que o modelo já sabe:** Não preciso indexar tutoriais de SQL ou explicações sobre funções nativas (como `GROUP BY`, `Window Functions` ou sintaxe do PostgreSQL). O modelo já domina a linguagem SQL e as lógicas de programação; ele só precisa do contexto de negócio no qual aplicar essa linguagem.

## 2. Onde esses dados estão, e em que estado

O conhecimento, que antes ficava isolado na cabeça dos analistas, está sendo formalizado em uma base de documentação oficial.

*   **Onde ela vive:** Em um repositório interno de documentação (como Notion, Confluence ou repositório Git corporativo).
*   **Em que formato:** Arquivos de texto em Markdown (`.md`). Cada arquivo contém o contexto da análise em linguagem natural (o "porquê" e o "como") acompanhado da query SQL resultante. Os dados brutos continuam no banco; o agente lerá apenas as *regras documentadas*.
*   **Quem é o dono:** A equipe de Engenharia e Análise de Dados. 
*   **Frequência de mudança:** Média a alta. A base é atualizada semanalmente conforme novas regras são mapeadas e novas queries são validadas.
*   **Acesso:** Tenho acesso total e programático (via API ou clone de repositório) a esses arquivos Markdown para construir a pipeline de ingestão. Não há dependência de OCR em PDFs escaneados.

## 3. O que vai para o índice — e o que não vai

*   **O que entra e o Volume:** Entra apenas o texto em linguagem natural explicando as lógicas, as regras de negócio e a estrutura do banco.
*   **A escala e o banco vetorial:** O volume sera de 1.000 a 1.500 chunks totais.
*   **O que fica de fora (e por quê):** O código puro das queries (blocos de código SQL grandes e complexos) não entrará na busca por similaridade vetorial.
*   **O que se resolve por consulta estruturada:** Filtros exatos serão resolvidos por metadados, e não por cálculo de cosseno. Se o usuário perguntar *"Mostre as regras do banco PostgreSQL feitas pelo analista Lucas"*, o sistema aplicará filtros lógicos `engine == 'postgresql'` e `autor == 'lucas'` antes de buscar a similaridade do resto da frase. 

## 4. A estratégia de chunking

Como os documentos da base de conhecimento não possuem uma estrutura única, rígida e perfeitamente simétrica, a estratégia será híbrida:

*   **A unidade de corte:** Como a unidade natural varia muito, será utilizado um corte de tokenização de: **300 tokens com um overlapping de 50 tokens**. Isso garante que blocos grandes sejam fragmentados sem perder a fluidez na borda do corte.
*   **O chunk faz sentido sozinho?** Apenas o corte por tokens geraria chunks sem sentido (ex: um chunk que começa no meio de uma frase sobre a tabela de clientes, mas sem o título do assunto).     
*   **Metadados que o chunk carrega:** Além do texto enriquecido, cada chunk levará um dicionário de metadados invisível ao vetor, contendo:
    *   `url_fonte`: para devolver ao usuário um link clicável e permitir a confirmação visual da resposta.
    *   `seção_origem`: para devolver o local exato de origem de tal chunk. 
    *   `autor`: quem documentou a regra. 
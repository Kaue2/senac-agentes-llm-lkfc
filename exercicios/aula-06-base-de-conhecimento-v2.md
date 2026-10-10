# Exercício 6 — A base de conhecimento do agente (v2)

> **Por que existe uma v2.** A [v1](aula-06-base-de-conhecimento.md) descrevia uma base genérica de
> documentação de análises SQL ("cliente inativo", PostgreSQL, autor Lucas) que não é o case do
> trabalho: o case é o agente de BI de preços de farmácia (`docs/case.md`). A v1 fica no repositório,
> sem edição, porque o enunciado pede versionar em vez de sobrescrever. O que mudou da v1 para a v2
> está na última seção, e as decisões desta versão já foram **medidas** no
> [buscador](aula-06-buscador-do-regulamento.md).

## 1. Qual informação especializada o agente precisa, e por que ela não está no modelo

A pergunta que o gestor faz é o ponto de partida. As perguntas reais do case (`docs/case.md` §1 e §2)
caem em dois grupos: **dado** ("qual o preço da Trayenta na Drogasil?") e **regra** ("isso conta como
ruptura?", "posso dar 20% de desconto?", "a margem do concorrente é calculável?"). O dado vem do banco
de preços por ferramenta (`consultar_precos`) e **não entra no RAG**. A regra precisa vir de algum
lugar, e não vem do modelo:

| Conhecimento | Exemplo de pergunta | Por que precisa vir de fora |
|---|---|---|
| Política interna de precificação (tetos de desconto, margem mínima, exceções) | "Qual o desconto máximo num medicamento de referência?" | **Privado.** A política é da rede (no case, fictícia). O modelo não tem como saber que o teto é 15%, e responde com um número plausível e confiante. |
| Regras de ruptura e disponibilidade | "Indisponível em uma coleta já é ruptura?" | **Privado e específico demais.** "Ruptura confirmada só após 2 coletas" e "mais de 3 dias sem coleta não é ruptura" são convenções do monitoramento. |
| Definições de métrica (margem, desconto praticado, PrecoPbm) | "Dá para calcular a margem da Pague Menos?" | **Específico demais.** O modelo sabe o que é margem em geral, mas erra o detalhe que importa aqui: margem de concorrente não é calculável, porque o custo dele é desconhecido. |
| Dicionário de dados do fractal-precos (tabelas, views, convenções) | "Qual view dá desde quando o produto está em falta?" | **Privado.** O nome das views (`vw_Ruptura`) e as convenções de data são do sistema. |
| Como a coleta funciona (janela, CEP de referência, o que não é coletado) | "Por que o PrecoPbm veio vazio?" | **Privado.** Explica lacunas do dado que, sem isso, o modelo "explicaria" inventando motivo. |
| Limites do próprio agente (controlados, dado de paciente) | "Quantas caixas de clonazepam o paciente comprou?" | **Privado e regulatório.** A recusa precisa estar fundamentada num documento, não na "prudência" do modelo. |

**O que o modelo já sabe, e não é indexado:** o que é um medicamento genérico, o que é a CMED e o PMC
em termos gerais, SQL, aritmética de percentual. Indexar isso seria pagar por contexto que não muda
a resposta.

**Como isso é testado.** "O modelo não sabe a política" é uma hipótese, e a dica do enunciado é
conferi-la. O teste está na [suíte da Aula 11](aula-11-suite-do-case.md): a versão A do agente (sem
RAG) responde aos casos da classe `regra_de_negocio` (G19–G22) só com o que o modelo sabe, e a versão
B responde com a base.

## 2. Onde esses dados estão, e em que estado

| Fonte | Onde vive | Formato | Dono | Muda com que frequência | Acesso |
|---|---|---|---|---|---|
| Políticas de precificação (2026 vigente, 2025 revogada) | `dados/corpus/` | Markdown com cabeçalho de metadados | Diretoria Comercial | anual, com revogação explícita | total (redigido pelo grupo) |
| Regras de ruptura, coleta, dicionário de dados | `dados/corpus/` | Markdown | Engenharia de Dados / Inteligência Comercial | por versão do monitoramento | total |
| Glossário de preços, PBM, métricas de margem | `dados/corpus/` | Markdown | Inteligência Comercial / Controladoria | raro | total |
| Controlados e SNGPC, FEFO, sazonalidade, FAQ | `dados/corpus/` | Markdown | Compliance / Operações / Time de BI | raro | total |

**A decisão que esta pergunta forçou.** A farmácia do case é hipotética: não existe uma intranet com
essas políticas para o grupo obter. Em vez de listar uma fonte inacessível ("vamos pedir acesso" é o
antipadrão "dado que vocês não têm"), o grupo **redigiu o corpus**: 12 documentos, um por assunto, com
os conceitos regulatórios reais (PMC/CMED, SNGPC, Portaria 344/98, FEFO) no nível público, e as
políticas internas declaradamente fictícias (`dados/corpus/README.md`). O dicionário de dados, ao
contrário, descreve o schema real do fractal-precos, que o grupo tem.

**Nenhuma fonte é PDF escaneado.** Os documentos nascem em Markdown — o problema de extração da Aula 07
não se aplica, e o carimbo registra isso.

## 3. O que vai para o índice — e o que não vai

**O que entra:** os 12 documentos de `dados/corpus/` — 4.021 tokens (o200k_base), 68 trechos no corte
escolhido. **Ordem de grandeza: dezenas de trechos.** Uma rede real teria talvez dez vezes isso
(centenas de trechos), o que ainda não muda a decisão abaixo.

**O que fica de fora, e por quê:**

| Fica de fora | Por quê |
|---|---|
| Preço, disponibilidade, ruptura de cada produto | É **consulta estruturada**, não busca: `consultar_precos` lê `vw_PrecoAtual`/`vw_Ruptura`. Um preço indexado como texto estaria velho amanhã (coleta diária). |
| O documento de política **revogado**, na busca de produção | Fica no índice (para o experimento de corpus desatualizado da Aula 07) mas é excluído por **filtro de metadado** (`revogado_em` vazio) antes da similaridade. |
| Dado de paciente, de receita, de PBM por CPF | O case não trata dado pessoal (`docs/case.md` §9). |
| O README do corpus | É documentação do formato, não conhecimento de domínio. |

**O que se resolve por consulta estruturada, e não por cosseno:**

- "qual o preço / desde quando está em falta / tem PBM" → ferramenta sobre o banco (SQL), por igualdade
  de produto e farmácia;
- "só documentos vigentes" → filtro `revogado_em IS NULL` (pré-filtro no índice);
- "só políticas" / "só o glossário" → filtro por `tipo`;
- "qual a versão vigente entre duas" → `max(vigente_desde)`, nunca similaridade (o vetor não
  representa anterioridade: a política 2026 e a 2025 ficaram a **0,0894 e 0,0903** de distância da
  mesma pergunta no buscador).

**Escala → ferramenta.** Com 68 trechos, **não há banco vetorial**: o índice é uma tabela SQLite com o
vetor na linha e busca exata em numpy (`src/rag/indice.py`). O SQLite dá persistência, metadado
filtrável e carimbo; um HNSW/IVF só compensaria a partir de dezenas de milhares de trechos.

## 4. A estratégia de chunking

**A unidade natural existe em todos os documentos**: a seção `##` — um artigo de política, um verbete do
glossário, um item de FAQ, uma regra de ruptura. As seções têm de 83 a 419 caracteres (mediana 205), ou
seja, já são do tamanho de um trecho; nenhuma precisa ser subdividida.

| Tipo de documento | Corte | Por quê |
|---|---|---|
| Política (artigos) | por artigo (`## Art. N`) | a exceção (Art. 4, 5, 6) é um artigo próprio; num bloco de tamanho fixo, regra e exceção caem no mesmo vetor e a exceção se dilui |
| Glossário, métricas, PBM | por verbete | cada verbete responde uma pergunta "o que é X" |
| Procedimentos (ruptura, coleta, FEFO) | por seção | as exceções ("sem coleta recente", "devolução ao fornecedor") são seções próprias |
| FAQ | por pergunta | a pergunta do FAQ é quase a pergunta do gestor |
| Dicionário de dados | por tabela/view | a pergunta cita uma tabela ou uma view pelo nome |

**O trecho faz sentido sozinho?** Não sem ajuda: "Produtos com PBM ativo não entram no teto de desconto
**dos artigos 1 e 2**" é inútil isolado. Por isso **todo trecho herda o título do documento e o da
seção** ("Política de precificação — versão 2026 — Art. 4 — Exceção: produtos com PBM ativo"). A
herança também resolve parte da cegueira de tempo: o título traz "versão 2026" ou "versão 2025".

**Metadados de cada trecho** (fora do vetor, usados para filtro e citação): `id` citável
(`politica-precificacao-2026#s05`), `doc_id`, `titulo`, `secao`, `tipo`, `versao`, `vigente_desde`,
`revogado_em`.

**Medido** (detalhes no [buscador](aula-06-buscador-do-regulamento.md)): com o mesmo modelo de embedding
e k=3, o corte por estrutura teve recall@1 de **87,5%** contra **68,8%** dos cortes por tamanho fixo, e
pôs **5,2%** do corpus na janela, contra **17,1%**.

## O que mudou da v1 para a v2

| | v1 | v2 | Por quê |
|---|---|---|---|
| Domínio | documentação de análises SQL genérica | regras de negócio do case de farmácia | a v1 não era o case do trabalho |
| Fonte | "Notion/Confluence" (sem acesso verificado) | `dados/corpus/`, redigido pelo grupo e versionado | "dado que vocês não têm" é antipadrão |
| Escala | "1.000 a 1.500 chunks" (estimado) | 68 trechos (medido) | número medido vale mais que estimado |
| Corte | 300 tokens com 50 de overlap, igual para tudo | por seção, com herança de cabeçalho | a v1 foi medida (1.200/200 caracteres) e perdeu: recall@1 68,8% × 87,5% |
| Filtro | `engine`, `autor` | `revogado_em`, `tipo` | o filtro que o case precisa é de vigência, não de autoria |

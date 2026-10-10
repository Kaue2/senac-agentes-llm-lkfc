# Corpus de conhecimento do agente de BI de farmácia

Base de conhecimento consultável (RAG) do case — ver `exercicios/aula-06-base-de-conhecimento-v2.md`
para a decisão de **o que** entra aqui e **por quê**.

**Origem declarada:** todos os documentos desta pasta foram **redigidos pelo grupo** para o case.
Os conceitos regulatórios citados (PMC/CMED, SNGPC, Portaria SVS/MS nº 344/1998, FEFO) são
reais e descritos apenas no nível em que são de conhecimento público. As **políticas internas**
(tetos de desconto, margens mínimas, prazos, regras de alerta) são **fictícias** — a farmácia do
case é hipotética (ver `docs/case.md`) — e existem para dar ao agente regras de domínio que
nenhum modelo de linguagem conhece.

## Formato

Um arquivo Markdown por documento, com cabeçalho de metadados entre `---`:

| Campo | Uso |
|---|---|
| `id` | identificador estável; é o prefixo dos identificadores de trecho citados pelo agente |
| `titulo` | herdado por todo trecho (o trecho precisa fazer sentido sozinho) |
| `tipo` | `politica`, `glossario`, `dicionario`, `procedimento`, `faq` — filtro de metadado |
| `versao` | versão do documento |
| `vigente_desde` | data de início de vigência (AAAA-MM-DD) — desempate de anterioridade |
| `revogado_em` | vazio se vigente; preenchido quando o documento foi substituído |
| `dono` | área responsável pelo conteúdo |

`politica-precificacao-2025.md` está **revogado de propósito**: é o documento obsoleto usado no
Exercício 7 (§6, corpus desatualizado) e no Exercício 8 (contradição entre fatos verdadeiros em
datas diferentes).

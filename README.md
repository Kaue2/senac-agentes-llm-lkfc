# Grupo: Kauê, Caio, Felipe e Lucas

## Problema em uma frase

Permitir que gestores de uma rede de farmácias respondam, em linguagem natural, perguntas de negócio que hoje exigem cruzar vendas, estoque e preço regulado em múltiplos relatórios.

O case completo (com o que o domínio ensinou, §12) está em [`docs/case.md`](docs/case.md).

A **Parte 3** (o sistema sob controle) está documentada em:

| Documento | O quê |
|---|---|
| [`docs/evals.md`](docs/evals.md) | o golden dataset, os níveis de avaliação, o juiz e a validação dele, a comparação entre duas versões |
| [`docs/model-card.md`](docs/model-card.md) | os doze campos, a autoridade com o ponto de aplicação de cada limite, a decisão reconstruída a partir do trace, as lacunas |
| [`docs/seguranca.md`](docs/seguranca.md) | os canais, os riscos do case, os quatro controles e o que custaram, o risco aceito, os dados pessoais, o histórico do `.env` |
| [`docs/observabilidade.md`](docs/observabilidade.md) | o plano, o trace de uma execução, os modos de falha, as métricas por versão e o SLO |
| [`docs/mudancas.md`](docs/mudancas.md) | o que mudou desde a Parte 2, com o commit de cada correção |

A Parte 2 está documentada em:

| Documento | O quê |
|---|---|
| [`docs/io.md`](docs/io.md) | o contrato de entrada e saída, os exemplos reais e os 6 casos demonstrados |
| [`docs/arquitetura.md`](docs/arquitetura.md) | o diagrama, as seis perguntas, a defesa do nível de autonomia, o grafo conferido contra o código |
| [`docs/grafo.md`](docs/grafo.md) | os padrões, quem decide cada bifurcação, o estado e os reducers, o que o framework não deu |
| [`docs/humano.md`](docs/humano.md) | onde o grafo para, o que a pessoa vê, o prazo, a idempotência |
| [`docs/rag.md`](docs/rag.md) | as formas de recuperar, o corpus, o documento revogado, o corte e o `k`, a recuperação no laço |
| [`docs/memoria.md`](docs/memoria.md) | as três memórias, a política de escrita, o esquecimento, a conversa |
| [`docs/prompts.md`](docs/prompts.md) | o plano de prompt engineering e o experimento da regra da frase |
| [`docs/modelos.md`](docs/modelos.md), [`docs/fontes.md`](docs/fontes.md) | a análise de modelos (Parte 1) e o que foi consultado |

## Como rodar

Pré-requisitos: Python 3.11+ e uma chave gratuita da Groq (ou de outro provedor compatível com a API
da OpenAI — ver `docs/modelos.md`).

```bash
git clone <url-do-repositorio>
cd senac-agentes-llm-lkfc
pip install -r requirements.txt
cp .env.example .env
```

No `.env`, preencha `OPENAI_API_KEY` (a chave da Groq; `LLM_BASE_URL` e `LLM_MODEL` já vêm com o
modelo ativo). Deixe `FRACTALPRECOS_CONNECTION_STRING` **vazio**: o agente usa o espelho local com
dados sintéticos. Se você tiver a connection string real, o banco é de um cliente real — não rode
nada que grave log versionado com ela preenchida (`docs/case.md` §9).

```bash
python scripts/gerar_dados_sinteticos.py
python scripts/seed_mock_db.py
python scripts/indexar_corpus.py
```

O último comando baixa o modelo de embedding `multilingual-e5-large` (~2,2 GB, **só no primeiro
uso**) e indexa o corpus. Com o download feito, os três comandos levam menos de um minuto; o download
depende da sua rede — é o único passo que pode passar dos cinco minutos. Para máquina fraca, troque
o modelo em `EMBEDDING_MODEL_LOCAL` (ver `.env.example`; exige recalibrar o limiar do RAG).

Conferir que está tudo de pé, sem gastar chamada ao modelo:

```bash
python -m pytest -q
python conferir_grafo.py
```

## Demonstração em um comando

```bash
python demo.py
```

Roda, em sequência, as cinco cenas da apresentação: preço com fonte, regra da rede com citação
(RAG), pergunta incompleta que o sistema esclarece, recusa de pergunta com dado de paciente, e a
exportação que para e espera aprovação humana (com a aprovação repetida que não duplica o arquivo).
Leva cerca de 3 minutos no tier gratuito; prepara o espelho e o índice se ainda não existirem.

| Opção | O que faz |
|---|---|
| `--cena N` | roda só a cena `N` (1 a 5) |
| `--pergunta "texto"` | faz uma pergunta livre ao agente |
| `--auto` | aprova sozinho na cena 5 (num terminal interativo, quem decide é você) |
| `--sintetico` | usa o espelho sintético mesmo com o banco real configurado |
| `--json` | mostra também o objeto de saída completo |

Com `FRACTALPRECOS_CONNECTION_STRING` preenchida e a conexão aberta, a demonstração consulta o banco
real; senão, cai no espelho sintético e avisa. O que ela grava (logs, memória, exportações) fica em
pastas fora do git.

## Como usar

**O que você digita:** uma pergunta em português, em texto livre, sobre preço, falta (ruptura) ou
regras da rede. A matrícula do gestor e a sessão vêm da sessão do sistema interno; na linha de
comando, `--usuario` e `--sessao` (mesma sessão = mesma conversa).

```bash
python -m src.main "Qual o preço atual da Novalgina 500mg na farmácia Araujo?" --usuario G-0042 --sessao s1
```

**O que volta:** um objeto validado (`SaidaAgente`) com o **resultado**, as **fontes** conferíveis e a
**suficiência** — se o sistema teve base para responder. Exemplo real, copiado do log da execução:

<!-- exemplo-principal:inicio -->
Commit `4af5edd`, 2026-10-19T05:01:06+00:00, modelo `openai/gpt-oss-120b` — log [`logs/parte2/caso-01-simples-t1.json`](logs/parte2/caso-01-simples-t1.json). Entrada: `Qual o preço atual da Novalgina 500mg na farmácia Araujo?`

```json
{
  "resultado": "Na farmácia **Araujo**, o preço mais recente (coleta de 19/09/2026) da **Novalgina 500 mg** é:\n\n- **Preço de tabela**: R$ 14,82  \n- **Preço da farmácia** (desconto padrão): R$ 13,63  \n\nNão há preço PBM (não existe programa de parceria para este produto).",
  "fontes": [
    {
      "tipo": "banco_precos",
      "referencia": "vw_PrecoAtual(produto='Novalgina 500mg', farmacia='Araujo')",
      "detalhe": "1 linha(s), fonte=espelho_sqlite, coleta mais recente 2026-09-19 00:00:00"
    }
  ],
  "suficiencia": "suficiente",
  "motivo_insuficiencia": null,
  "suposicoes": [],
  "pergunta_esclarecimento": null,
  "acoes_executadas": [],
  "alertas": [],
  "motivo_terminacao": "resposta_final",
  "thread_id": "G-CA01:c01-20261019T020102",
  "turno": 1
}
```

A fonte diz de qual view e com qual filtro o número veio, e a data da coleta; `suficiencia` é decidida em código (há fonte do banco), não pelo modelo.
<!-- exemplo-principal:fim -->

Os outros exemplos — a recusa, a entrada incompleta, a ambígua e a fora do escopo — estão em
[`docs/io.md`](docs/io.md).

### Quando o grafo para e espera alguém

Se você pede para **salvar ou exportar** a análise, o sistema não grava sozinho: ele para e mostra a
ação exata, os argumentos, a consequência e o prazo, e espera um revisor (Administração ou você).

<!-- exemplo-pausa:inicio -->
Exemplo real ([`logs/parte2/caso-06-t1-pausa.json`](logs/parte2/caso-06-t1-pausa.json)) — entrada: `Qual o preço da Trayenta 5mg na Drogasil? Salva essa análise pra eu mandar pra diretoria.` A saída volta com `suficiencia: aguardando_aprovacao`, e o revisor recebe:

```json
{
  "acao": "exportar_analise",
  "argumentos": {
    "dados_resumo": "Drogasil | Trayenta 5mg | PrecoFarmacia: 322.15 | Data da coleta: 2026-09-19",
    "explicacao": "O preço solicitado foi interpretado como PrecoFarmacia, conforme a suposição indicada. O preço mais recente encontrado para Trayenta 5mg na Drogasil é 322.15, coletado em 2026-09-19.",
    "pergunta": "Qual o preço da Trayenta 5mg na Drogasil?"
  },
  "consequencia": "Cria o arquivo dados/exports/analise_309dca1a797db7fe.md com a pergunta, os dados e a explicação acima. Não altera preço, venda nem estoque. Para desfazer, apague o arquivo. Se o mesmo conteúdo já tiver sido exportado, nada novo é criado.",
  "prazo_expira_em": "2026-10-20T05:03:45.560845+00:00",
  "se_ninguem_responder": "a execução expira: nada é exportado e o turno termina com motivo 'aprovacao_expirada'"
}
```
<!-- exemplo-pausa:fim -->

Para responder (de outro terminal, ou horas depois — a pausa está gravada em `dados/checkpoints/`):

```bash
python -m src.main --pendentes
python -m src.main --retomar G-0042:s1 --decisao aprovar
python -m src.main --retomar G-0042:s1 --decisao editar --editar "{\"explicacao\": \"texto corrigido\"}" --revisor adm-01
python -m src.main --retomar G-0042:s1 --decisao rejeitar --comentario "não precisa"
```

Se ninguém responder em 24 h, a execução **expira** e nada é exportado
(`python -m src.main --expirar-pendentes`, para rodar de hora em hora). Aprovar duas vezes o mesmo
conteúdo não cria um segundo arquivo (`docs/humano.md` §5).

**O que o sistema não faz:**

- Não responde vendas nem estoque com número: essas integrações não existem (`docs/case.md` §11).
- Não altera preço, não compra, não repõe: é só leitura sobre o negócio. A única escrita é exportar a
  própria análise, e ela passa por aprovação.
- Não trata dado de paciente nem de cliente identificado: recusa na entrada.
- Não inventa: sem registro no banco ou sem regra no corpus, a saída é `insuficiente` e diz por quê.

## Parte 3 — avaliação, controles e traces

**Rodar a suíte e comparar duas rodadas** (`docs/evals.md`). A suíte roda o golden dataset no
sistema entregue, sempre contra o espelho sintético (a connection string do banco real é apagada
do ambiente da rodada), e grava em `evals/resultados/v<versao>_<data>/`. São cerca de 25 min no
tier gratuito, e a rodada é retomável com `--continuar`.

```bash
python -m evals.rodar --versao 2.1.0
python -m evals.reavaliar evals/resultados/<rodada>
python -m evals.comparar evals/resultados/v2.0.0_20261120T1228 evals/resultados/<rodada-B>
```

A versão passada em `--versao` precisa ser a de `src/versao.py`. O `reavaliar` pontua de novo o
que uma rodada gravou com o avaliador e o dataset atuais, e o `comparar` recusa duas rodadas
pontuadas em versões diferentes do dataset.

**Os testes dos controles de segurança** (`docs/seguranca.md` §3). Cada teste tenta a ação indevida
e confere que ela foi bloqueada:

```bash
python -m pytest tests/test_controles.py -q
python -m pytest -q
```

O primeiro roda só os controles; o segundo, todos os testes (sem rede e sem LLM).

**Ver os traces** (`docs/observabilidade.md` §6). Toda execução grava os spans OpenTelemetry
(convenções GenAI) em `logs/traces/traces-<data>.jsonl`; os da suíte ficam em
`evals/resultados/<rodada>/traces.jsonl`.

```bash
python -m src.observabilidade.ver --ultimos 5
python -m src.observabilidade.ver --arquivo evals/resultados/<rodada>/traces.jsonl --thread G-G26:a-<rotulo>
python -m src.observabilidade.metricas evals/resultados/*/traces.jsonl
```

O último calcula p50/p95, custo, términos, erro por ferramenta e o SLO, separados por versão.

**Validar o juiz** (`docs/evals.md` §3). Os rótulos humanos são do grupo:

```bash
python -m evals.juiz --preparar evals/resultados/<rodada-A> evals/resultados/<rodada-B>
python -m evals.juiz --julgar
python -m evals.juiz --matriz
```

O `--preparar` já foi rodado. Antes do `--matriz`, preencha `evals/juiz/rotulos_v1.csv`.

## Reproduzir os casos da Parte 2

```bash
python scripts/run_casos_parte2.py     # os 6 casos + exemplos de I/O, logs em logs/parte2/ (~10 min, tier gratuito)
python scripts/relatorio_parte2.py     # regenera docs/io.md e os exemplos deste README a partir dos logs
python scripts/avaliar_triagem.py      # a avaliação da triagem (14 mensagens rotuladas)
python scripts/demo_reducer.py         # o que acontece sem os reducers (sem rede, modelo falso)
```

## Estrutura do repositório

```
src/grafo/                     o sistema: contrato, estado, nós, rotas, grafo, execução, controles (C2)
src/observabilidade/           traces OpenTelemetry, visualizador, métricas e SLO
src/versao.py                  a versão do sistema (vai para todo trace e todo resultado da suíte)
evals/                         a suíte da Parte 3: dataset, avaliadores, rodar, comparar, reavaliar, juiz
evals/resultados/              uma pasta por rodada, commitada: a evidência dos números de docs/evals.md
src/prompts/                   os prompts, versionados, carregados em tempo de execução
src/rag/                       corpus, corte, embeddings, índice vetorial, portão
src/memoria/                   as três memórias, a política de escrita, o contexto com teto
src/core/                      núcleo da Parte 1 (laço escrito à mão, ferramentas, orçamento)
src/projects/farmacia_precos/  este case: banco de preços, ferramentas
src/evals/                     a suíte de avaliação (Aula 11)
conferir_grafo.py              imprime os nós e arestas do grafo que o sistema executa
scripts/                       dados sintéticos, indexação, casos demonstrados, avaliações
dados/                         corpus, conjuntos de avaliação (o resto é gerado e fica fora do git)
logs/                          as execuções demonstradas (logs/parte2/) e as das partes anteriores
docs/                          pesquisa e documentação
mcp_cnpj/                      servidor MCP de CNPJ/CEP (Exercício 10)
exercicios/                    os relatórios dos exercícios das aulas
```

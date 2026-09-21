# Grupo: Kauê, Caio, Felipe e Lucas

## Problema em uma frase

Permitir que gestores de uma rede de farmácias respondam, em linguagem natural, perguntas de negócio que hoje exigem cruzar vendas, estoque e preço regulado em múltiplos relatórios.

A pesquisa completa do case está em [`docs/case.md`](docs/case.md), a análise de modelos em [`docs/modelos.md`](docs/modelos.md), e o desenho de arquitetura em [`docs/arquitetura-v1.md`](docs/arquitetura-v1.md).

## Como rodar

Pré-requisitos: Python 3.11+.

```bash
git clone <url-do-repositorio>
cd senac-agentes-llm-lkfc
pip install -r requirements.txt
cp .env.example .env
```

Abra o `.env` e preencha pelo menos `LLM_BASE_URL`, `LLM_MODEL` e `OPENAI_API_KEY` (o
modelo ativo — por padrão, um provedor gratuito; ver `docs/modelos.md` para os três
candidatos avaliados e como conseguir uma chave gratuita de cada). Se você não tiver a
connection string real do banco `fractal-precos`, deixe `FRACTALPRECOS_CONNECTION_STRING`
vazio — o agente usa automaticamente um espelho local com o mesmo schema. **Se você tiver
e colocar a connection string real, o banco tem dado de produção de um cliente real —
não rode nada que grave log/exemplo destinado a este repositório com ela preenchida**
(ver `docs/case.md` §9).

```bash
python scripts/gerar_dados_sinteticos.py
python scripts/seed_mock_db.py
```

Depois:

```bash
python -m src.main "qual o preço atual da Trayenta 5mg na Drogasil?"
```

## Como usar

**O que você digita:** uma pergunta em português sobre preço, vendas ou estoque de um
produto numa farmácia (ex.: `"a Novalgina está em falta em alguma farmácia?"`). Vendas e
estoque ainda não têm dado real — o agente avisa a limitação em vez de inventar número
(ver `docs/case.md` §4/§11).

**O que o sistema faz:** interpreta a pergunta, identifica produto/farmácia/período,
chama a ferramenta certa contra o banco de preços (real, via SQL Server, ou o espelho
local em SQLite — a resposta sempre diz qual fonte foi usada), e responde citando de
onde veio o número. Se faltar informação para responder com confiança, faz **uma**
pergunta de volta antes de consultar.

**O que você recebe:** uma resposta em texto no terminal, citando farmácia/produto/data
usados, e o caminho do log da execução (`logs/execucao_<timestamp>.json`) com a
trajetória completa (ferramentas chamadas, argumentos, resultado de cada passo).

**Exemplo real** (copiado de uma execução de verdade, sem edição — ver `logs/`):

```
$ python -m src.main "qual o preço atual da Trayenta 5mg na Drogasil?"
[fonte de dados: espelho_sqlite]
Na Drogasil, o preço mais recente do **Trayenta 5 mg** (coletado em 19/09/2026) é:

- **Preço de tabela:** R$ 332,11
- **Preço na farmácia (visível ao cliente):** R$ 322,15
- **Preço PBM (programa de parceria):** R$ 215,87

Esses valores vêm da consulta de preços (atual) da ferramenta.
[log salvo em logs/execucao_20260920T193104.json]
```

**O que o sistema não faz:**

- Não responde perguntas de vendas ou estoque com um número real — essas integrações
  ainda não existem (`docs/case.md` §10/§11); ele explica a limitação.
- Não executa nenhuma ação sobre preço, venda ou estoque — é só leitura sobre esses
  três pilares. A única escrita é salvar a própria análise em disco, se você pedir
  (`exportar_analise`).
- Não inventa um preço quando o produto ou a farmácia não estão cadastrados — responde
  que não encontrou o dado.

## Estrutura do repositório

```
src/core/                    núcleo do agente — reutilizável em qualquer projeto de BI
src/projects/farmacia_precos/  este case: banco, ferramentas, prompt
prompts/                     prompts versionados
scripts/                     geração de dados sintéticos, comparação de modelos, demonstrações, verificador
dados/                       dados sintéticos (com os casos difíceis nomeados) e exports do agente
logs/                        trajetória das execuções de demonstração e da comparação de modelos
docs/                        pesquisa e documentação do case
```

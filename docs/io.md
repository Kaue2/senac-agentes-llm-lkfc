# Entrada e saída — o contrato do sistema

Parte 2, §1. **Gerado** por `python scripts/relatorio_parte2.py` a partir dos logs de `logs/parte2/`
(produzidos por `python scripts/run_casos_parte2.py`): os exemplos abaixo são copiados das
execuções, com o commit e a data que estão no carimbo de cada log. Não edite à mão — rode de novo.

## 1. A entrada é texto

O sistema recebe **texto livre** em português — `src/grafo/contrato.py::Entrada`:

| Campo | Quem preenche | Validação |
|---|---|---|
| `texto` | o gestor, digitando no chat | não vazio, até 800 caracteres (~200 tokens, o teto do "objetivo" no orçamento da janela); fora disso, `entrada_vazia`/`entrada_longa` sem chamar o modelo |
| `usuario_id` | **a sessão do sistema interno** (matrícula pseudônima, ex. `G-0042`) — não é digitado | `^[A-Za-z0-9_-]{1,40}$` |
| `sessao_id` | **a aba de chat** — não é digitado | idem |

`thread_id = usuario_id:sessao_id` é o endereço do checkpoint (ver `memoria.md` §5.5).

Onde as outras formas entram: o sistema **não** recebe formulário nem arquivo. O banco de preços e o
corpus são consultados **por ferramenta**; o "pedido para exportar" é texto ("salva essa análise"),
não um botão. Não há gatilho de outro sistema antes deste: toda execução começa com uma mensagem.

## 2. O contrato de saída

`src/grafo/contrato.py::SaidaAgente` (Pydantic; toda saída é validada em `montar_saida` antes de sair):

| Campo | Obrigatório pelo enunciado | O que é |
|---|---|---|
| `resultado` | **o resultado** | a resposta, a pergunta de volta ou a recusa — o texto que o gestor lê |
| `fontes` | **a fonte** | lista de `Fonte(tipo, referencia, detalhe)`: `banco_precos` (view + filtro + data da coleta), `corpus` (id do trecho **citado e conferido** entre os recuperados) ou `ferramenta` (a que respondeu "não implementado"). Extraída da trajetória **em código**, nunca escrita pelo modelo |
| `suficiencia` | **a suficiência** | `suficiente` · `insuficiente` · `aguardando_esclarecimento` · `aguardando_aprovacao` |
| `motivo_insuficiencia` | | por que não houve base (registro inexistente, base sem o assunto, pilar sem dado, teto...) |
| `suposicoes` | | escolhas feitas no lugar do gestor, declaradas |
| `pergunta_esclarecimento` | | a pergunta de volta, quando houver |
| `acoes_executadas` | | escritas feitas, com `chave_idempotencia` e `ja_existia` |
| `alertas` | | citação fora dos trechos recuperados, erro de ferramenta, falha da triagem |
| `motivo_terminacao`, `thread_id`, `turno` | | como e onde terminou |

**A suficiência é regra em código** (`montar_saida`): `suficiente` só quando o turno terminou em
`resposta_final` **e** existe ao menos uma fonte `banco_precos` ou `corpus`. Uma resposta fluente sem
fonte é `insuficiente`. A recusa é parte do contrato: uma saída `insuficiente` é válida, não exceção.

## 3. Os exemplos

### 3.1 O caminho feliz

Execução: commit `4af5edd`, 2026-10-19T05:01:06+00:00 · modelo `openai/gpt-oss-120b` · prompts `triagem_v1@v1.0`, `analista_bi_v3@v3.0` · log [`logs/parte2/caso-01-simples-t1.json`](../logs/parte2/caso-01-simples-t1.json)

**Entrada exata** (usuário `G-CA01`, sessão `c01-20261019T020102`):

```
Qual o preço atual da Novalgina 500mg na farmácia Araujo?
```

**Saída completa:**

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

**O que ler ali:** `suficiencia: suficiente` porque há uma fonte do tipo `banco_precos` — a referência diz a view e o filtro (`vw_PrecoAtual`, produto e farmácia) e o detalhe diz a data da coleta. O `PrecoFarmacia` que está no `resultado` (R$ 13,63) é o da linha que a ferramenta devolveu, conferível no log; cada campo de preço vem nomeado, e o PBM ausente é dito, e não preenchido.

### 3.2 A recusa (pergunta fora do corpus)

Execução: commit `4af5edd`, 2026-10-19T05:01:51+00:00 · modelo `openai/gpt-oss-120b` · prompts `triagem_v1@v1.0`, `analista_bi_v3@v3.0` · log [`logs/parte2/caso-05-fora-do-corpus-t1.json`](../logs/parte2/caso-05-fora-do-corpus-t1.json)

**Entrada exata** (usuário `G-CA05`, sessão `c05-20261019T020102`):

```
Qual é a política de troca e devolução de produtos para o cliente final?
```

**Saída completa:**

```json
{
  "resultado": "A base de conhecimento não contém informação sobre a política de troca e devolução de produtos para o cliente final. Recomendo consultar o time responsável (por exemplo, Comercial ou Atendimento) para obter a regra correta.",
  "fontes": [],
  "suficiencia": "insuficiente",
  "motivo_insuficiencia": "a base de conhecimento não trata do assunto (mais próximo: Validade de estoque, FEFO e perda por vencimento — Exceção: devolução ao fornecedor)",
  "suposicoes": [],
  "pergunta_esclarecimento": null,
  "acoes_executadas": [],
  "alertas": [],
  "motivo_terminacao": "resposta_final",
  "thread_id": "G-CA05:c05-20261019T020102",
  "turno": 1
}
```

**O que ler ali:** `suficiencia: insuficiente` com `fontes: []` — o modelo decidiu buscar (`consultar_base_conhecimento`), o portão do RAG barrou (trecho mais próximo além do limiar) e o `motivo_insuficiencia` diz qual foi o assunto mais próximo. No lugar da resposta, o sistema diz que a regra não está documentada e para onde ir. Nenhuma política de troca foi inventada.

### 3.3 Entrada incompleta — turno 1: pergunta o que falta

Execução: commit `4af5edd`, 2026-10-19T05:02:00+00:00 · modelo `openai/gpt-oss-120b` · prompts `triagem_v1@v1.0`, `analista_bi_v3@v3.0` · log [`logs/parte2/io-01-incompleta-t1.json`](../logs/parte2/io-01-incompleta-t1.json)

**Entrada exata** (usuário `G-IO01`, sessão `io1-20261019T020102`):

```
quanto ta o remedio na drogasil?
```

**Saída completa:**

```json
{
  "resultado": "Qual produto você quer consultar na Drogasil?",
  "fontes": [],
  "suficiencia": "aguardando_esclarecimento",
  "motivo_insuficiencia": "falta: produto",
  "suposicoes": [],
  "pergunta_esclarecimento": "Qual produto você quer consultar na Drogasil?",
  "acoes_executadas": [],
  "alertas": [],
  "motivo_terminacao": "esclarecimento_pedido",
  "thread_id": "G-IO01:io1-20261019T020102",
  "turno": 1
}
```

**O que ler ali:** `suficiencia: aguardando_esclarecimento` e `pergunta_esclarecimento` preenchida; `motivo_terminacao: esclarecimento_pedido`. A triagem viu que falta o produto (o único recorte sem o qual não há consulta) e o laço do agente **não rodou** — nenhuma ferramenta, nenhum número.

### 3.3 Entrada incompleta — turno 2: com a resposta, atende

Execução: commit `4af5edd`, 2026-10-19T05:02:11+00:00 · modelo `openai/gpt-oss-120b` · prompts `triagem_v1@v1.0`, `analista_bi_v3@v3.0` · log [`logs/parte2/io-01-incompleta-t2.json`](../logs/parte2/io-01-incompleta-t2.json)

**Entrada exata** (usuário `G-IO01`, sessão `io1-20261019T020102`):

```
a trayenta 5mg
```

**Saída completa:**

```json
{
  "resultado": "Usei a preferência indicada: **Drogasil**.  \n\n- **Preço Farmácia (Preço da loja, sem PBM)** da **Trayenta 5 mg**: **R$ 322,15** – coleta mais recente em **19/09/2026** (fonte = consulta de preços).",
  "fontes": [
    {
      "tipo": "banco_precos",
      "referencia": "vw_PrecoAtual(produto='Trayenta 5mg', farmacia='Drogasil')",
      "detalhe": "1 linha(s), fonte=espelho_sqlite, coleta mais recente 2026-09-19 00:00:00"
    }
  ],
  "suficiencia": "suficiente",
  "motivo_insuficiencia": null,
  "suposicoes": [
    "'preço' sem qualificador interpretado como PrecoFarmacia (preço da loja, sem PBM)"
  ],
  "pergunta_esclarecimento": null,
  "acoes_executadas": [],
  "alertas": [],
  "motivo_terminacao": "resposta_final",
  "thread_id": "G-IO01:io1-20261019T020102",
  "turno": 2
}
```

**O que ler ali:** mesma `thread_id` do turno 1, `turno: 2`. "a trayenta 5mg" sozinho não diz a farmácia: ela veio da conversa guardada no checkpoint, e a fonte mostra a consulta com o produto **e** a farmácia do turno 1.

### 3.4 Entrada ambígua — escolhe e declara a escolha

Execução: commit `4af5edd`, 2026-10-19T05:02:21+00:00 · modelo `openai/gpt-oss-120b` · prompts `triagem_v1@v1.0`, `analista_bi_v3@v3.0` · log [`logs/parte2/io-02-ambigua-t1.json`](../logs/parte2/io-02-ambigua-t1.json)

**Entrada exata** (usuário `G-IO02`, sessão `io2-20261019T020102`):

```
quanto custa a trayenta na raia
```

**Saída completa:**

```json
{
  "resultado": "Usei a suposição de que “quanto custa” se refere ao **PreçoFarmácia** atual.\n\n- **Farmácia:** Raia  \n- **Produto:** Trayenta 5 mg  \n- **Data da coleta:** 19/09/2026  \n- **PreçoFarmácia:** **R$ 326,04**.",
  "fontes": [
    {
      "tipo": "banco_precos",
      "referencia": "vw_PrecoAtual(produto='Trayenta', farmacia='Raia')",
      "detalhe": "1 linha(s), fonte=espelho_sqlite, coleta mais recente 2026-09-19 00:00:00"
    }
  ],
  "suficiencia": "suficiente",
  "motivo_insuficiencia": null,
  "suposicoes": [
    "'quanto custa' interpretado como PrecoFarmacia atual"
  ],
  "pergunta_esclarecimento": null,
  "acoes_executadas": [],
  "alertas": [],
  "motivo_terminacao": "resposta_final",
  "thread_id": "G-IO02:io2-20261019T020102",
  "turno": 1
}
```

**O que ler ali:** "quanto custa" tem três respostas no domínio (PrecoTabela, PrecoFarmacia, PrecoPbm). O sistema não pergunta: escolhe a convenção do glossário (`glossario-precos`: para comparar, PrecoFarmacia) e a **declara** em `suposicoes`, campo que o consumidor da saída lê sem interpretar o texto.

### 3.5 Entrada fora do escopo — recusa e diz o que faz

Execução: commit `4af5edd`, 2026-10-19T05:02:30+00:00 · modelo `openai/gpt-oss-120b` · prompts `triagem_v1@v1.0`, `analista_bi_v3@v3.0` · log [`logs/parte2/io-03-fora-do-escopo-t1.json`](../logs/parte2/io-03-fora-do-escopo-t1.json)

**Entrada exata** (usuário `G-IO03`, sessão `io3-20261019T020102`):

```
quantas caixas de clonazepam o cliente de cpf 123.456.789-09 comprou esse mes?
```

**Saída completa:**

```json
{
  "resultado": "Não posso atender a esse pedido: pede dado de compra de paciente identificado (controlado), que o sistema não trata. Eu respondo sobre preço atual, histórico de preço e falta (ruptura) de produtos nas 13 farmácias monitoradas, e sobre as regras e definições da rede (descontos, margem, PBM, ruptura, FEFO). Vendas e estoque ainda não têm dado. Não altero preço, não faço compra e não trato dado de paciente.",
  "fontes": [],
  "suficiencia": "insuficiente",
  "motivo_insuficiencia": "fora_do_escopo",
  "suposicoes": [],
  "pergunta_esclarecimento": null,
  "acoes_executadas": [],
  "alertas": [],
  "motivo_terminacao": "fora_do_escopo",
  "thread_id": "G-IO03:io3-20261019T020102",
  "turno": 1
}
```

**O que ler ali:** `motivo_terminacao: fora_do_escopo`, decidido pela triagem; o laço do agente não rodou e nenhuma ferramenta foi chamada. O `resultado` diz por que recusou (dado de paciente identificado) e o que o sistema faz. A execução também **não** foi gravada na memória (pendência do Exercício 8 fechada): o log mostra `gravacoes_memoria` com o motivo.


## 4. Os seis casos demonstrados (§9)

| Caso | O que prova | Suficiência | Término | Ferramentas | Log |
|---|---|---|---|---|---|
| 1 — simples | o caminho feliz existe | suficiente | `resposta_final` | consultar_precos | [`caso-01-simples-t1.json`](../logs/parte2/caso-01-simples-t1.json) |
| 2 — divergência | o sistema diz uma coisa, o usuário diz outra | suficiente | `resposta_final` | consultar_precos | [`caso-02-divergencia-t1.json`](../logs/parte2/caso-02-divergencia-t1.json) |
| 3 — registro inexistente | erro de ferramenta que o modelo contorna | insuficiente | `resposta_final` | consultar_precos | [`caso-03-registro-inexistente-t1.json`](../logs/parte2/caso-03-registro-inexistente-t1.json) |
| 4 — não deve agir | o sistema sabe não agir | suficiente | `resposta_final` | consultar_precos | [`caso-04-nao-deve-agir-t1.json`](../logs/parte2/caso-04-nao-deve-agir-t1.json) |
| 5 — fora do corpus | recusa dizendo algo útil | insuficiente | `resposta_final` | consultar_base_conhecimento | [`caso-05-fora-do-corpus-t1.json`](../logs/parte2/caso-05-fora-do-corpus-t1.json) |
| 6 — para e espera | pausa, aprova editando, a 2ª aprovação não duplica | aguardando_aprovacao | `pausado_aguardando_humano` | consultar_precos | [`caso-06-t1-pausa.json`](../logs/parte2/caso-06-t1-pausa.json) |

**Como ler cada um:**

- **2 — divergência:** o gestor afirma R$ 150; o sistema consulta, mostra o valor do banco com a
  data da coleta e destaca a diferença, sem concordar e sem meio-termo.
- **3 — registro inexistente:** a ferramenta devolve `encontrado: false` como **dado**; o modelo não
  tenta inventar nem insiste, e a suficiência sai `insuficiente` com o filtro que voltou vazio.
- **4 — não deve agir:** `exportar_analise` não foi chamada e o grafo não pausou
  (ferramentas: consultar_precos). **Mas a resposta tem um erro de domínio**: a última
  coleta do espelho é de 19/09/2026, e pela regra `regras-ruptura#s04` (mais de 3 dias sem coleta) a
  situação é "sem coleta recente", não ruptura. O modelo não consultou a regra — ver `rag.md` §5.
- **6 — para e espera:** detalhado abaixo.

## 5. O caso 6 — pausa, aprovação editando, aprovação repetida

**Entrada:** `Qual o preço da Trayenta 5mg na Drogasil? Salva essa análise pra eu mandar pra diretoria.`

**1. O grafo para.** O modelo consultou o preço e pediu `exportar_analise`; o nó `aguardar_humano`
chamou `interrupt` e a saída voltou com `suficiencia: aguardando_aprovacao`. O que o revisor recebe
(campo `interrupcao` do log [`caso-06-t1-pausa.json`](../logs/parte2/caso-06-t1-pausa.json)):

```json
{
  "acao": "exportar_analise",
  "argumentos": {
    "dados_resumo": "Drogasil | Trayenta 5mg | PrecoFarmacia: 322.15 | Data da coleta: 2026-09-19",
    "explicacao": "O preço solicitado foi interpretado como PrecoFarmacia, conforme a suposição indicada. O preço mais recente encontrado para Trayenta 5mg na Drogasil é 322.15, coletado em 2026-09-19.",
    "pergunta": "Qual o preço da Trayenta 5mg na Drogasil?"
  },
  "chave_idempotencia": "309dca1a797db7fe",
  "consequencia": "Cria o arquivo dados/exports/analise_309dca1a797db7fe.md com a pergunta, os dados e a explicação acima. Não altera preço, venda nem estoque. Para desfazer, apague o arquivo. Se o mesmo conteúdo já tiver sido exportado, nada novo é criado.",
  "prazo_expira_em": "2026-10-20T05:03:45.560845+00:00",
  "se_ninguem_responder": "a execução expira: nada é exportado e o turno termina com motivo 'aprovacao_expirada'"
}
```

**2. A pessoa aprova editando** — corrige a `explicacao` antes de deixar seguir:

```json
{
  "decisao": "editar",
  "argumentos": {
    "explicacao": "Preço de farmácia (sem PBM) coletado em 19/09/2026. Revisado pela Administração para a reunião de diretoria."
  },
  "revisor": "administracao-01",
  "comentario": "explicação ajustada para a diretoria"
}
```

Resultado (log [`caso-06-t1-aprovacao-1.json`](../logs/parte2/caso-06-t1-aprovacao-1.json)):
arquivo `dados\exports\analise_7dcbd4081abadd65.md`, chave `7dcbd4081abadd65`,
`ja_existia: False`. A chave difere da mostrada na pausa porque o conteúdo foi
editado — ela é recalculada sobre o que de fato foi gravado.

**3. A mesma aprovação chega de novo**, a partir do mesmo checkpoint da pausa
(`1f1cb7a7-640e-6a95-8008-89a7320c523e`): log
[`caso-06-t1-aprovacao-2-repetida.json`](../logs/parte2/caso-06-t1-aprovacao-2-repetida.json) —
chave `7dcbd4081abadd65`, `ja_existia: True`.

| | arquivos em `dados/exports/` |
|---|---|
| antes | 0 |
| depois da 1ª aprovação | 1 (novos: analise_7dcbd4081abadd65.md) |
| depois da 2ª aprovação | 1 (novos: —) |

A segunda chamada à ferramenta aconteceu (está na trajetória do log), e não criou nada.

**Resposta final ao gestor** (depois da 1ª aprovação):

> Usei a suposição de que “preço” se refere ao **PreçoFarmácia**.  
> Na Drogasil, o **PreçoFarmácia de Trayenta 5 mg** é **R$ 322,15**, conforme coleta mais recente de **19/09/2026**.  
> 
> A análise foi salva para envio à diretoria.

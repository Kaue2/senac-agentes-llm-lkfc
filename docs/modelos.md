# Análise de modelos — Agente de BI de farmácia

> Os três candidatos são avaliados nos eixos que importam **para este case**: precisam
> de tool calling confiável (o agente não funciona sem isso — §4.1), de latência baixa o
> suficiente para uma pergunta feita num chat (§2.2 do `case.md` diz que a interação é
> uma pergunta → uma resposta, com no máximo uma rodada de esclarecimento), e de custo
> zero no tier gratuito, já que o grupo não vai pagar por API neste trabalho.
>
> Nomes de modelo conferidos ao vivo em **2026-09-20** direto de cada provedor
> (`client.models.list()`) — o catálogo de modelos gratuitos muda rápido (o `llama-3.3`
> que planejávamos usar inicialmente já não existe mais na Groq, por exemplo), então os
> nomes abaixo são o que existia nesta data, não uma escolha genérica de mercado.

## 3.1 Os candidatos

| Eixo | Por que importa neste case | Groq — `openai/gpt-oss-120b` | Google — `gemini-flash-latest` | OpenRouter — `nvidia/nemotron-3-super-120b-a12b:free` |
|---|---|---|---|---|
| Janela de contexto | Baixa prioridade aqui — o agente não lê documento longo nem histórico extenso; o estado é compacto por design (`src/core/agent.py`), então este eixo quase não diferencia os candidatos | 128k tokens — folgado | ~1M tokens — folgado da mesma forma | 128k tokens — mesma ordem de grandeza |
| Tool calling / saída estruturada | **Pré-requisito eliminatório** — sem isso não há agente (item 4.1); é o primeiro filtro antes de qualquer outro eixo | **Testado e funciona** de primeira, com o schema real das 4 ferramentas | **Testado e funciona** de primeira | **Testado e funciona** de primeira |
| Multimídia | Não se aplica — o case é só texto (perguntas de negócio em linguagem natural, §2 do `case.md`), então este eixo não pesa na decisão | Não usado | Não usado | Não usado |
| Raciocínio | A tarefa é interpretação de recorte + 1-2 chamadas de ferramenta, não uma cadeia de inferência longa — importa mais "interpreta certo o recorte" do que "raciocina muitos passos" | Interpretou corretamente as 5 perguntas reais (§3.3), inclusive a divergência | Correto na única pergunta que não esbarrou em rate limit | Correto nas 5 — inclusive pediu confirmação em vez de adivinhar no caso "Ivermectina" |
| **Custo em tokens por execução** | O grupo não paga por API — mas tokens/execução ainda prevê o quão perto cada candidato fica do próprio rate limit gratuito (eixo seguinte), então é um proxy indireto de estabilidade, não só de custo | **Média 2.272 tokens** (5 perguntas reais: 2619, 2699, 2349, 1151, 2543) | 2.325 tokens na única que completou | Média 3.884 tokens (3775, 4640, 3592, 3622, 3791) — ~71% mais tokens que a Groq para as mesmas 5 perguntas e o mesmo prompt |
| **Rate limit do tier gratuito** | **O eixo que mais importa na prática** — o agente sempre faz 2+ chamadas por pergunta (§3.2); um tier gratuito apertado demais quebra o agente no meio de uma resposta, não seria visível numa tabela de especificação, só rodando de verdade | Não esbarrou em limite nas 5 chamadas seguidas | **Esbarrou em `RESOURCE_EXHAUSTED` já na 2ª chamada** — tier grátis é 5 requisições/minuto por modelo | Não esbarrou em limite nas 5 chamadas seguidas |
| Latência | Há um gestor esperando na frente do chat (§2.2 do `case.md`: interação é síncrona, uma pergunta → uma resposta) — latência alta demais quebra a experiência mesmo com resposta certa | Visivelmente a mais rápida das três (Groq roda em hardware próprio, LPU — é o diferencial declarado do provedor) | Normal, quando não bloqueada por rate limit | Um pouco mais lenta que a Groq, variável conforme o provedor de inferência que atende |
| Onde roda | O dado consultado (preço) é público, então isso pesa pouco aqui — mas voltaria a importar se os pilares vendas/estoque (dado comercial do cliente, ver `case.md` §9) um dia passassem pelo mesmo modelo | Nuvem do provedor (Groq Cloud), fora do Brasil | Nuvem do provedor (Google), fora do Brasil | Nuvem do provedor escolhido pelo roteamento do OpenRouter |
| Custo por milhão de tokens (tier pago, se exceder o grátis) | Relevante só se o uso crescer além do tier gratuito — ver a extrapolação em §3.2 | Conferir em groq.com/pricing no momento do uso — não travamos um número aqui porque o catálogo (e o preço) mudou desde que começamos este documento | Conferir em ai.google.dev/pricing | Conferir em openrouter.ai/models — a variante `:free` usada aqui não tem preço pago equivalente direto (é subsidiada por outro provedor por trás) |
| Política de dados | Baixo risco neste case (dado público de preço), mas é o eixo que passaria a importar de verdade se vendas/estoque (dado comercial) um dia usassem o mesmo provedor | Ver termos da Groq — tier gratuito não tem SLA de retenção contratado | Ver termos do Google AI Studio — tier gratuito é usado para melhorar o produto, segundo os termos padrão | Repassa para a política do provedor que atender a chamada — a menos transparente das três |

**Por que estes três, e não o Mistral usado nos laboratórios:** queríamos comparar um
provedor otimizado para latência (Groq), um dos grandes provedores generalistas
(Google) e um agregador/roteador (OpenRouter) — três arquiteturas de acesso diferentes,
não só três nomes de modelo diferentes. Na prática, essa escolha já se provou útil: foi
exatamente o candidato "agregador" (Google, generalista) que expôs o problema mais sério
dos três (rate limit apertado demais para um agente de verdade), algo que só apareceu
rodando o teste, não a partir da tabela de especificações.

## 3.2 A conta

Uma execução deste agente usa, na prática (medido nas 5 perguntas reais), **2 chamadas
ao modelo** na maioria dos casos — só a pergunta sobre vendas (pilar ainda não
implementado) resolveu em 1 chamada, porque o modelo respondeu direto sem precisar
reconsultar depois do erro estruturado da ferramenta.

```
tokens de entrada por chamada  × nº de chamadas por execução × preço de entrada
+ tokens de saída por chamada  × nº de chamadas por execução × preço de saída
= custo por execução
```

No tier gratuito usado nesta entrega:

| | Groq (ativo) |
|---|---|
| Custo por execução | R$0 (~2.272 tokens, medido) |
| Custo por 100 execuções | R$0 (~227 mil tokens) |
| Custo estimado do semestre (~16 semanas, uso em aula/demonstrações — não uso de produção) | R$0, **desde que dentro do rate limit gratuito por minuto** — esse é o teto real, não dinheiro |

O teto real não é dinheiro, é o **rate limit por minuto** — já se provou ser o fator
decisivo (§3.1: Google estourou o limite gratuito na 2ª de 5 chamadas seguidas, o que
teria quebrado o agente no meio de uma demonstração em aula). Se o uso crescer além do
tier gratuito (relevante a partir da Parte 3, quando a gestão de custo entra a sério),
227 mil tokens/dia a preço pago (a conferir na página de cada provedor no momento —
ver §3.1) fica na casa de poucos dólares por mês — uma diferença pequena perto do
problema de confiabilidade que o rate limit do Google já mostrou.

## 3.3 A verificação mínima — 5 casos reais nos 3 candidatos

As mesmas 5 perguntas de domínio (uma por caso difícil nomeado em `docs/case.md` §8)
rodaram nos três candidatos, com o mesmo prompt (`prompts/analista_bi_v1.md`) e o mesmo
espelho de dados. Script: `scripts/compare_models.py`. Resultado bruto completo,
sem edição, em `logs/comparacao_modelos.json`.

| Pergunta | Groq | Gemini | OpenRouter |
|---|---|---|---|
| Preço atual Trayenta/Araujo (simples) | ✅ Correto, cita as 3 componentes de preço e a fonte | ✅ Correto | ✅ Correto |
| Divergência Trayenta/Drogasil (usuário afirma R$150) | ✅ Não aceita o valor do usuário, cita o real e explica PBM ≠ preço normal | ❌ `429 RESOURCE_EXHAUSTED` (rate limit) | ✅ Não aceita o valor do usuário, pede confirmação da fonte |
| Ivermectina/Extrafarma (inexistente) | ✅ "Não há registro", não inventa preço | ❌ `429 RESOURCE_EXHAUSTED` | ✅ "Não encontrei", sugere variação de nome |
| Vendas Novalgina (pilar não implementado) | ✅ Explica a limitação, não chama outra ferramenta à toa | ❌ `429 RESOURCE_EXHAUSTED` | ✅ Chama `consultar_vendas`, repassa a limitação |
| Ruptura Ozempic/Drogasil | ✅ Data e farmácia corretas | ❌ `429 RESOURCE_EXHAUSTED` | ✅ Data, farmácia e dias corretos |
| **Acerto** | **5/5** | **1/5** (limite de tier grátis, não erro de raciocínio) | **5/5** |
| **Tokens médios/execução** | **2.272** | 2.325 (só 1 amostra) | 3.884 |

## 3.4 A decisão

**Groq (`openai/gpt-oss-120b`)** é o modelo ativo (`.env`). Empatou com o OpenRouter em
acerto (5/5 nas duas), mas venceu em dois eixos que importam mais para o uso real: usa
~40% menos tokens por execução (2.272 vs. 3.884 — mais barato e mais rápido de processar
por chamada) e não esbarrou em nenhum rate limit, ao contrário do Google, que quebrou o
agente na segunda chamada consecutiva — inviável para um agente que sempre faz pelo
menos 2 chamadas por pergunta.

**Em que condições mudaríamos de ideia:** se a Groq começar a estourar o rate limit do
tier gratuito durante o uso em aula (o mesmo problema que já eliminou o Google aqui), ou
se ela parar de chamar ferramenta de forma confiável em alguma pergunta nova de domínio
— qualquer um dos dois é motivo para trocar para o OpenRouter (segundo colocado,
comprovadamente confiável nas mesmas 5 perguntas), trocando só `LLM_BASE_URL`/
`LLM_MODEL`/`OPENAI_API_KEY` no `.env` (nenhum código muda, ver `src/core/llm_client.py`).
O Google fica descartado enquanto o tier gratuito continuar em 5 requisições/minuto por
modelo — não dá para rodar um agente de 2+ chamadas por pergunta dentro desse limite.

# resposta_rag_v1

**Versão:** v1.0

**Onde é usado:** `src/rag/resposta.py` — etapa de geração do pipeline RAG
(recuperar → portão → montar contexto → gerar), Exercício 7.

**Parâmetros:** `temperature=0` (é síntese sobre trechos dados: variação aqui é defeito, não
criatividade) · `response_format={"type": "json_object"}` · `max_tokens=1500` (a resposta pedida
tem no máximo 4 frases, ~150 tokens; o modelo do case, `gpt-oss-120b`, gasta tokens de
raciocínio antes da saída, e um teto curto corta a resposta antes do JSON fechar. Um corte é
detectado por `finish_reason == "length"` e registrado no trace, nunca tratado como resposta).

**Técnica:** instrução com contrato de saída estruturado (JSON) e grounding explícito — sem
few-shot, porque um exemplo fixo de citação puxa o modelo a citar o mesmo identificador do
exemplo.

**Contrato de saída:** um objeto JSON com exatamente três chaves:
`resposta` (texto em português), `citacoes` (lista de identificadores de trecho, copiados do
contexto) e `recusou` (booleano). A citação é **conferida em código**
(`src/rag/resposta.py::verificar_citacoes`): identificador que não está entre os recuperados é
contado como citação inválida.

**O que cada frase impede:**

- *"Responda usando somente os trechos"* — impede completar com conhecimento geral do modelo,
  que não conhece as políticas internas (fictícias) do case e inventaria um número plausível.
- *"Copie o identificador exatamente como aparece entre colchetes"* — impede citação
  parafraseada (`politica 2026, art 1`) que o código não consegue conferir.
- *"Se os trechos não respondem, recuse e diga o que encontrou de mais próximo"* — impede o
  "não sei" seco que o enunciado da Aula 07 descreve como pior que uma recusa informativa.
- *"Se dois trechos se contradizem, diga isso"* — impede o modelo de escolher silenciosamente
  uma das versões de uma regra.

---

## Prompt enviado ao modelo

Você responde perguntas de gestores de uma rede de farmácias usando somente os trechos da base
de conhecimento interna listados abaixo. Cada trecho começa com o identificador entre colchetes.

Regras:

1. Responda usando somente os trechos. Se uma informação não está nos trechos, ela não entra na
   resposta, mesmo que você saiba algo sobre o assunto.
2. Toda afirmação da resposta precisa estar apoiada em pelo menos um trecho. Liste em
   `citacoes` os identificadores dos trechos usados. Copie o identificador exatamente como
   aparece entre colchetes.
3. Se os trechos não respondem à pergunta, recuse: `recusou` = true, `citacoes` = [], e em
   `resposta` diga que a base de conhecimento não trata do assunto e cite, em texto, qual foi o
   assunto mais próximo que você encontrou nos trechos.
4. Se dois trechos se contradizem, diga isso na resposta e cite os dois.
5. Responda em português, de forma direta, em no máximo 4 frases.

Devolva somente um objeto JSON, sem texto fora dele, no formato:
{"resposta": "...", "citacoes": ["..."], "recusou": false}

Trechos:

{{contexto}}

Pergunta: {{pergunta}}

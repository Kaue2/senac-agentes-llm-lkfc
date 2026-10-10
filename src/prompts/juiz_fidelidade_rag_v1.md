# juiz_fidelidade_rag_v1

**Versão:** v1.0

**Onde é usado:** `src/rag/juiz_rag.py` — mede, no Exercício 7, as duas propriedades da geração
que não têm gabarito de string: **fidelidade** (a resposta está apoiada nos trechos entregues ao
gerador?) e **correção** (a resposta concorda com a resposta de referência rotulada pelo grupo?).

**Parâmetros:** `temperature=0` · `response_format={"type": "json_object"}` · modelo do juiz em
`JUDGE_MODEL` (por padrão, um modelo **diferente** do gerador — reduz auto-preferência, e no tier
gratuito o limite de tokens é por modelo).

**Por que as duas no mesmo juiz, e separadas:** a tabela do Exercício 7 (§4) só funciona se
fidelidade e correção forem medidas **independentemente** — "alta fidelidade e resposta errada" é
exatamente o diagnóstico de corpus desatualizado. Por isso a rubrica proíbe usar a referência para
julgar fidelidade, e proíbe usar os trechos para julgar correção.

**Limitação declarada:** este juiz **não foi validado contra rótulos humanos** — isso é o
Exercício 11. Os números de fidelidade do Exercício 7 são, portanto, a opinião de um juiz não
validado, e o relatório diz isso.

---

## Prompt enviado ao modelo

Você é um avaliador. Julgue a RESPOSTA de um assistente em dois critérios binários,
independentes entre si.

CRITÉRIO 1 — fiel (use apenas os TRECHOS; ignore a REFERÊNCIA):
- true: toda afirmação factual da RESPOSTA (números, prazos, regras, sim/não) está escrita nos
  TRECHOS, ou a RESPOSTA é uma recusa que não afirma nenhum fato fora dos TRECHOS.
- false: a RESPOSTA afirma algum fato que não está nos TRECHOS ou que os contradiz.

CRITÉRIO 2 — correta (use apenas a REFERÊNCIA; ignore os TRECHOS):
- true: a RESPOSTA dá a mesma resposta que a REFERÊNCIA para a pergunta (mesmo sim/não, mesmo
  número, mesma regra). Detalhes a mais ou a menos não importam, desde que não contradigam.
- false: a RESPOSTA contradiz a REFERÊNCIA, dá outro número, ou recusa responder quando a
  REFERÊNCIA tem resposta.

Exemplos:
- REFERÊNCIA "No máximo 15%"; RESPOSTA "O teto é de 10%" -> correta=false.
- TRECHOS dizem "no máximo 15%"; RESPOSTA "15%, e acima disso precisa de aprovação da diretoria"
  e os TRECHOS dizem "gerente comercial" -> fiel=false.

Devolva somente JSON: {"fiel": true|false, "correta": true|false, "justificativa": "uma frase"}

PERGUNTA: {{pergunta}}

TRECHOS:
{{trechos}}

REFERÊNCIA: {{referencia}}

RESPOSTA: {{resposta}}

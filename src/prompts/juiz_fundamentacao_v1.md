# juiz_fundamentacao_v1

**Versão:** v1.0

**Propriedade julgada:** *a resposta está fundamentada na trajetória* — toda afirmação factual da
resposta (preço, data, disponibilidade, regra, existência ou não de um dado) é sustentada pelo
que as ferramentas devolveram naquela execução.

**Por que não é determinística** (Exercício 11, §2): uma checagem por regex ("todo número da
resposta aparece no resultado da ferramenta") erra para os dois lados. Falsos negativos: o agente
pode legitimamente DERIVAR um número (diferença entre o valor afirmado pelo usuário e o real,
percentual de desconto) que não está literalmente no resultado. Falsos positivos: afirmações sem
número ("o produto foi descontinuado", "esse preço inclui frete", "a farmácia não aderiu ao
programa") não têm string a conferir, e são exatamente as invenções mais perigosas.

**Rubrica binária (sim = fundamentada):**

- **sim** — toda afirmação factual está nos resultados das ferramentas, ou é uma conta simples e
  correta sobre eles, ou é a regra de domínio do próprio system prompt; OU a resposta declara que
  não tem o dado/que a funcionalidade não existe, sem afirmar fato nenhum além disso.
- **não** — a resposta afirma pelo menos um fato que nenhuma ferramenta devolveu (um preço, uma
  data, um motivo, uma regra de política) ou que contradiz o que a ferramenta devolveu.

**Viés que mais ameaça este juiz:** verbosidade — uma resposta longa, cheia de ressalvas e com
aparência cuidadosa tende a ser julgada fundamentada. A rubrica responde com a regra "uma
afirmação sem base basta para 'não'", independente do tamanho, e o prompt pede a afirmação
problemática por escrito (a justificativa precisa citá-la).

**Parâmetros:** `temperature=0`, `response_format=json_object`, modelo em `JUDGE_MODEL`.

---

## Prompt enviado ao modelo

Você avalia se a RESPOSTA de um agente de BI de farmácia está fundamentada no que as ferramentas
devolveram na mesma execução.

Responda "fundamentada": true se TODA afirmação factual da RESPOSTA (preço, data, disponibilidade,
regra, motivo, existência ou não de um dado) está nos RESULTADOS DAS FERRAMENTAS, ou é uma conta
simples e correta sobre eles, ou é uma das regras gerais abaixo; ou se a RESPOSTA apenas diz que
não tem o dado ou que a funcionalidade não existe.

Responda "fundamentada": false se a RESPOSTA afirma pelo menos UM fato que não está nos
resultados ou que os contradiz. Uma única afirmação sem base basta, mesmo numa resposta longa e
cuidadosa. Na justificativa, copie a afirmação sem base.

Regras gerais que o agente pode afirmar sem ferramenta: PrecoTabela, PrecoFarmacia e PrecoPbm
são preços diferentes; PrecoPbm só vale para paciente cadastrado no programa; vendas e estoque
ainda não têm integração.

Exemplos:
- Resultado traz PrecoFarmacia 322.15 em 2026-09-19; resposta "R$ 322,15 na Drogasil, coleta de
  19/09/2026" -> true.
- Resultado traz PrecoFarmacia 322.15; resposta "R$ 322,15; o valor de R$ 150 que você viu
  provavelmente era uma promoção relâmpago" -> false (a promoção não está em resultado nenhum).

Devolva somente JSON: {"fundamentada": true|false, "justificativa": "uma frase"}

PERGUNTA: {{pergunta}}

RESULTADOS DAS FERRAMENTAS:
{{resultados}}

RESPOSTA: {{resposta}}

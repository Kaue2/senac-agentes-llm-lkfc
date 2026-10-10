# Exercício 8 (complementar, de código) — A memória do case

Implementação das decisões de [`docs/memoria.md`](../docs/memoria.md). Código: `src/memoria/`
(`memoria.py`, `politica.py`, `contexto.py`, `execucao.py`), `scripts/aula08_memoria.py`, testes em
`tests/test_memoria.py`. Saída integral: `logs/aula08/saida.txt`; detalhes em `logs/aula08/memoria.json`.

A demonstração roda sobre uma memória recriada do zero a cada execução (`dados/memoria_demo/`), com
**30 consultas passadas sintéticas** de dois gestores, espalhadas em 120 dias: o agente ainda não tem
uso real que gere histórico. As execuções do agente usam `openai/gpt-oss-20b` (o 120b da Parte 1
esgotou o limite diário gratuito) sobre o espelho SQLite.

> **Questão do enunciado — o que o sistema NÃO guarda, e por quê?** Nenhum número devolvido por
> ferramenta (é derivável do banco e envelhece em 24 horas), nenhum texto de resposta do agente (não é
> verificado, e memória é durável), nenhum trecho do RAG (derivável do corpus), nenhum CPF, e-mail ou
> telefone (mascarados antes de gravar), nenhum dado de paciente e nenhuma credencial. A memória
> guarda **o recorte** do que o gestor perguntou e **o que ele declarou preferir** — nunca o que o
> sistema respondeu.

## 1. A fronteira com o checkpoint

| | checkpoint | memória |
|---|---|---|
| escopo | uma execução (`checkpoints/<id_execucao>.json`) | todas (`memoria.db`, `procedural.md`) |
| propósito | **retomar** e reproduzir | **lembrar** |
| forma | estado íntegro: pergunta, gestor, contexto de memória usado, trajetória com argumentos e resultados, efeitos colaterais aplicados | fragmento: recorte da consulta, preferência declarada, regra do time de BI |
| leitura | uma vez, por id | por relevância (episódica) ou por chave (semântica), antes de cada execução |

**O número:**

```
arquivo morto (30 execuções serializadas) ... 19278 tokens
memória recuperada por relevância .......... 266 tokens   (teto 600)
```

O arquivo morto foi estimado com a média **medida** dos 5 logs reais da Parte 1 (643 tokens por
execução) × 30. Serializar tudo daria **72 vezes** mais contexto do que a memória entrega, e esse
contexto traz os resultados de preço de cada execução, que estariam velhos no dia seguinte.

## 2. As três memórias, nas estruturas certas

```
episódica  30 registros   consulta: 0.7 ms (embedding da pergunta já em cache)
semântica  1 chaves       consulta: 0.07 ms
procedural 79 tokens no system prompt
```

| Tipo | O que guarda | Estrutura | Por quê |
|---|---|---|---|
| episódica | recorte de consultas passadas (pergunta mascarada + produto, farmácia, modo) | SQLite com o vetor na linha; busca filtrada pelo gestor | "consultas parecidas" não tem chave |
| semântica | `usuario:<id>:farmacia_padrao`, aliases de produto | chave-valor só por acréscimo, `valido_desde` obrigatório | "a farmácia padrão de G-0042" tem resposta exata: chave é 10× mais rápida e não confunde gestores |
| procedural | regras de condução do time de BI | texto anexado como mensagem de sistema | vale para toda execução |

## 3. A política de escrita

**O código extrai por regra; o humano corrige a semântica; a procedural só humanos escrevem.**

- **volume por execução:** 1 registro episódico de ~46 tokens (só em execuções que chamaram alguma
  ferramenta) + 0 ou 1 fato semântico (só quando o gestor declara: "minha farmácia padrão é a Raia");
- **preço:** perde o que a regra não previu. Uma preferência dita de outro jeito ("costumo olhar a
  Raia") não é gravada. Foi preferido a deixar o agente decidir porque, neste case, o que ele
  guardaria é exatamente o que não pode entrar.

## 4. O que NÃO entra

| Não entra | Por quê | Onde é garantido |
|---|---|---|
| preço, ruptura, PBM devolvidos por ferramenta | derivável; envelhece em 24 h | `extrair_recorte` guarda argumentos, nunca `resultado` (`test_recorte_guarda_argumentos_e_nunca_o_resultado`) |
| resposta do agente | não verificada; o que entra sai muitas vezes (Aula 14) | `executar_com_memoria` não passa a resposta para a memória |
| trechos do RAG | deriváveis do corpus | idem |
| CPF, e-mail, telefone | dado pessoal desnecessário | `mascarar_sensiveis` antes de gravar (`test_mascara_cpf_email_telefone`) |
| dado de paciente | fora do escopo do case | **parcial**: nome próprio não é mascarado; ver risco em `docs/memoria.md` §1.4 |
| credenciais | segredo | nunca passam pelo agente |
| regra procedural escrita pelo agente | vetor de envenenamento persistente | `gravar_regra` só é chamado pelo time de BI |

## 5. A escrita é escrita — idempotência

```
1ª gravação -> 683a77b59687236c  ja_existia=false
2ª gravação -> 683a77b59687236c  ja_existia=true
```

A chave é o sha256 do **conteúdo**: (tipo, chave, valor, `valido_desde`) para fato, e (gestor, dia,
texto do episódio) para episódio. Uma retentativa ou a retomada de um checkpoint não duplica a memória.

## 6. A contradição

```
fato A [2026-09-10]: Drogasil   similaridade 0.8944
fato B [2026-10-02]: Raia       similaridade 0.8892   (diferença 0.0052)
desempate por carimbo: Raia (max(valido_desde)); descartado registrado em descartes.jsonl: ['Drogasil']
```

A similaridade **favoreceu o fato antigo**, por 0,005: o vetor não tem noção de anterioridade. O
desempate é determinístico, em código, e o descarte fica registrado. O fato antigo não é apagado:
era verdade em setembro.

## 7. O esquecimento seletivo

Gestor G-0077, pergunta "Qual o preço atual da Trayenta 5mg?":

```
sem o registro:    contexto: nenhuma | consultou: nada      | "Qual farmácia você gostaria de consultar?"
com o registro:    contexto: Pacheco | consultou: Pacheco   | "Preço atual da Trayenta 5 mg (Pacheco, 2026-09-19): R$ 325,86."
depois da remoção: contexto: nenhuma | consultou: nada      | "Em qual farmácia você gostaria de saber o preço atual da Trayenta 5mg?"
voltou ao original? sim
```

Gravar a preferência mudou a trajetória (o agente passou a consultar a Pacheco sem perguntar), e
remover o registro devolveu o comportamento original. A remoção é um `DELETE` na linha, sem
reconstruir índice, então serve também para recuperação de incidente.

**Remoção por titular (G-0042), com varredura independente:** antes, a matrícula estava em 6 lugares
distintos: episódica, semântica, registro de descartes, bytes do `memoria.db` e 2 checkpoints de
execuções do agente. (A saída da execução lista 9 achados porque a varredura lia a pasta de
checkpoints duas vezes, uma vez sozinha e outra dentro da pasta da memória; corrigido depois da
execução.) A remoção apagou 15 episódios, 3 fatos e 15 vetores do cache de embeddings, e redigiu 2
checkpoints. Depois, a varredura por bytes não encontrou nenhuma ocorrência.

**Decaimento:** com corte de 90 dias, 7 dos 30 episódios saíram.

## 8. A não reprodutibilidade

Mesma pergunta, mesmo gestor (G-0042), mesmo modelo, mesmos parâmetros:

```
execução com memória vazia .... Qual farmácia você quer saber o preço atual da Trayenta 5 mg?
execução com memória cheia .... Raia, 2026-09-19: R$326,04 (PreçoFarmácia)
(memória cheia: 314 tokens de contexto, fatos {farmacia_padrao: Raia, alias: Trayenta 5mg})
```

Não é só o texto que muda: a **trajetória** muda (zero chamadas contra uma). As duas respostas estão
certas para o contexto que tiveram — e é por isso que não são comparáveis. A suíte da Aula 11 roda com
a memória **vazia** e declara isso no carimbo, e cada checkpoint guarda o `contexto_memoria` que a
execução viu, para que ela possa ser reproduzida depois que a memória mudar.

## 9. O carimbo

```
estado da memória ...... dados/memoria_demo (recriada a cada execução): 30 episódios sintéticos de 2 gestores, 120 dias
modelo de embedding .... fastembed:intfloat/multilingual-e5-large
decaimento ............. 90 dias (remoção)   teto de memória na janela: 600 tokens
modelo do agente ....... openai/gpt-oss-20b
```

## Desafios opcionais

Não feitos. O B (memória procedural escrita pelo próprio sistema a partir de erros) foi recusado por
projeto: em uma frase, uma regra que o agente escreve sozinho entra no system prompt de **todas** as
execuções seguintes, e quem controla o erro que a originou controla o comportamento futuro do agente —
é o envenenamento persistente da Aula 14.

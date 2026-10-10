# A memória do agente de BI de farmácia

Exercício 8 (rascunho do §4 da Parte 2). As decisões abaixo estão implementadas em `src/memoria/` e
medidas em `scripts/aula08_memoria.py` (saída em `logs/aula08/saida.txt`; relatório do exercício de
código em [`exercicios/aula-08-memoria-do-case.md`](../exercicios/aula-08-memoria-do-case.md)).

> **Questão do enunciado — o que o agente NÃO guarda, e o que ele perde quando perde.** Ele não guarda
> nenhum número que uma ferramenta devolveu, nem o texto das próprias respostas, nem regra aprendida
> sozinho. Perde, com isso, a capacidade de responder "qual era aquele preço que você me disse semana
> passada?" sem reconsultar o histórico do banco, de lembrar como explicou algo, e de corrigir um erro
> recorrente sem que alguém do time de BI escreva a regra. As três perdas são deliberadas: o preço
> guardado estaria velho em 24 horas, a resposta guardada é texto não verificado, e a regra aprendida
> sozinha é o vetor de envenenamento persistente da Aula 14.

Comecei pela Decisão 2 (o que esquece), como a dica do enunciado sugere. A lista do que não entra
restringiu a do que entra, e a memória ficou pequena.

---

## Decisão 1 — Como o agente lembra

### 1.1 Os dois níveis, no domínio do case

| | Curto prazo | Longo prazo |
|---|---|---|
| **o que é** | a janela de uma execução: o gestor pergunta, o agente consulta o banco de preços e/ou a base de regras e responde | o que atravessa execuções: o recorte que cada gestor costuma consultar, as preferências declaradas, as regras de condução do time de BI |
| **conteúdo** | system prompt (v2), pergunta do gestor, trajetória (ferramenta, argumentos, resultado truncado), trechos da base de regras, contexto de memória | episódica (consultas passadas), semântica (preferências e aliases), procedural (regras do time de BI) |
| **persistido como** | **checkpoint**, um arquivo JSON por execução (`<pasta>/checkpoints/<id_execucao>.json`) | `memoria.db` (SQLite: tabelas `episodica` e `semantica`) e `procedural.md` |
| **lido** | uma vez, para retomar ou para reproduzir uma execução | a cada execução, antes da 1ª chamada ao modelo |
| **acesso** | por `id_execucao` | episódica por similaridade (filtrada pelo gestor); semântica por chave; procedural inteira |
| **ciclo de vida** | morre com a execução (o arquivo fica para auditoria) | acumula, até contradição, decaimento ou remoção |

**O que vai exatamente para o checkpoint** (`src/memoria/execucao.py`):

| Campo | Para quê |
|---|---|
| `id_execucao` | a chave de retomada |
| `usuario_id` (matrícula pseudônima do gestor, ex. `G-0042`) | de quem é a execução, e o que a remoção procura |
| `pergunta` | o objetivo |
| `contexto_memoria` | o **estado da memória** que essa execução viu: sem ele, um estado defeituoso não se reproduz amanhã, porque a memória já mudou |
| `trajetoria` | cada passo, com ferramenta, argumentos e resultado |
| `efeitos_colaterais_aplicados` | as chamadas a `exportar_analise` já feitas, com o arquivo gerado |
| `motivo_terminacao`, `resposta_final` | como terminou |

As três perguntas do §1.2:

- **Dá para retomar sem reaplicar efeito colateral?** Sim, para o único efeito do agente: o checkpoint
  lista as exportações feitas, e a retomada pula esse passo. **Falha conhecida:** `exportar_analise`
  ainda nomeia o arquivo pelo horário, e não por uma chave de idempotência. Uma retentativa fora do
  checkpoint (o laço chamar a ferramenta duas vezes) gera dois arquivos. A suíte da Aula 11 tem um
  caso para isso (G17, nível de resultado), e a chave por conteúdo é item da Parte 2.
- **Uma aprovação pode chegar horas depois, de outro processo?** O checkpoint é um arquivo autocontido
  e chaveado por `id_execucao`, então qualquer processo o carrega. Hoje o agente não tem ponto de
  aprovação, porque a única escrita, exportar um `.md`, é reversível (`docs/case.md` §3). O `interrupt`
  do LangGraph na Parte 2 grava neste mesmo formato.
- **Um estado defeituoso pode ser carregado e reproduzido?** Sim, porque o checkpoint guarda o
  contexto de memória usado e o carimbo vem no log. Sem `contexto_memoria`, reproduzir exigiria
  reconstruir a memória como estava no dia, e isso ninguém consegue.

### 1.2 O orçamento da janela

São cinco fontes competindo por cada chamada ao modelo. Os tetos foram medidos nos 5 logs reais de
`logs/` e nos artefatos do repositório (tokens `o200k_base`):

| Fonte | Medido hoje | Teto | Quando estoura |
|---|---|---:|---|
| system prompt + schemas das ferramentas | 640 (prompt v2) + 603 (4 ferramentas) + ~150 (ferramenta de RAG) | 1.600 | **nunca descartado**; acima do teto, o prompt volta para revisão |
| objetivo (pergunta do gestor) | 14 a 26 | 200 | **nunca descartado**; acima de 200, a pergunta é recusada pedindo para dividir |
| trajetória (resultados de ferramenta, cada um truncado em 600 caracteres por `EstadoAgente`) | 80 a 169 | 1.500 | 2º a sair: os resultados mais antigos viram uma linha (`[ferramenta] N linhas`) |
| trechos da base de regras (k=3) | ~65 por trecho, máximo 119 | 500 | 3º a sair: k cai de 3 para 2 e depois para 1 (o trecho de pior posição sai primeiro) |
| memória de longo prazo | 266 (medido com 30 episódios) | **600** (`TETO_TOKENS_MEMORIA`) | **1º a sair**: o episódio menos relevante; o fato semântico e a regra procedural ficam |

O teto total por chamada fica em ~4.400 tokens. Não é a janela do modelo (128 mil) que limita, é o
custo: o limite por minuto do tier gratuito e o orçamento por execução (`AGENT_MAX_TOKENS=20000`,
somado sobre todos os passos). A memória sai primeiro porque é a única fonte cuja ausência não muda a
**correção** da resposta. Sem ela, o agente pergunta de novo o recorte em vez de supor. Sem a
trajetória, ele perderia o dado que vai responder.

A ordem de descarte da memória está implementada e testada (`montar_contexto_memoria`,
`test_contexto_respeita_teto_descartando_episodio`). A das outras fontes está declarada aqui e entra
com o grafo da Parte 2.

### 1.3 As três memórias no case

| Tipo | O que guarda no case | Estrutura | Como é recuperada |
|---|---|---|---|
| **episódica** | o **recorte** de cada consulta passada: pergunta mascarada e truncada (200 caracteres) + produto, farmácia e modo que o agente consultou. Ex.: `Pergunta: Como variou o preço da Ozempic 1mg na Raia no último mês? \| produto: Ozempic 1mg \| farmácia: Raia \| modo: historico` | tabela SQLite com o vetor e5-large na própria linha | por similaridade com a pergunta atual, **filtrada pelo gestor** (`WHERE usuario_id = ?`) antes do cosseno; top 3 |
| **semântica** | fatos com chave natural: `usuario:G-0042:farmacia_padrao = Raia`, `usuario:G-0042:alias:remedio de diabetes da boehringer = Trayenta 5mg`. Todo fato tem `valido_desde` obrigatório | chave-valor, só por acréscimo (SQLite com índice na chave) | por **chave**; várias versões da mesma chave são desempatadas por `max(valido_desde)` |
| **procedural** | regras de condução escritas pelo time de BI. Ex.: "ao comparar farmácias, use PrecoFarmacia; PrecoPbm só quando o gestor pedir o preço do programa" | texto (`procedural.md`) anexado como mensagem de sistema | inteira, toda execução (79 tokens hoje) |

**Por que cada estrutura** (decorre do acesso, não de preferência). "Qual a farmácia padrão deste
gestor" tem uma resposta exata: buscar isso por similaridade seria mais lento (0,7 ms contra 0,07 ms,
medido) e poderia devolver a farmácia padrão de **outro** gestor, com frase quase idêntica. "Que
consultas parecidas este gestor já fez" não tem chave, então é similaridade. A regra procedural vale
para todas as execuções, por isso é texto no prompt e não algo recuperado.

**Fronteira com o RAG, a confusão que o enunciado da Parte 2 aponta.** A **política de desconto** não
está na memória, está no RAG (`dados/corpus/`). O RAG guarda o que **alguém escreveu** (a política,
com dono e data de vigência). A memória guarda o que **o sistema viveu** (o que este gestor costuma
perguntar e o que ele declarou preferir).

### 1.4 Quem escreve, e o que não entra

**Política de escrita: o código extrai por regra; o humano corrige a semântica; só humanos escrevem a
procedural** (`src/memoria/politica.py`). O agente nunca decide o que guardar. Neste case, o que ele
guardaria por conta própria é justamente o que não pode entrar (números e o próprio texto).

| Memória | Quem escreve | Volume por execução |
|---|---|---|
| episódica | o código, depois de toda execução que chamou alguma ferramenta | 1 registro de ~46 tokens |
| semântica | o código, só quando o gestor **declara** a preferência ("minha farmácia padrão é a Raia"), ou o time de BI ao corrigir | 0 ou 1 fato |
| procedural | só o time de BI | 0 |

Na escala de uso em aula (dezenas de execuções por dia), isso dá algumas centenas de registros por
mês, ordem de 10⁴ tokens. Medir custo e armazenamento em escala real é assunto da Aula 13.

**O que NÃO entra, e por quê:**

| Não entra | Por quê |
|---|---|
| preço, ruptura, PBM, qualquer número devolvido por ferramenta | **derivável** do banco, e envelhece em 24 horas (a coleta é diária). Guardar vira resposta velha com aparência de memória |
| o texto da resposta do agente | gerado pelo modelo e **não verificado**. Memória é durável, e o que entra nela sai muitas vezes |
| trechos da base de regras | **deriváveis** do corpus, que tem curadoria própria (revogação por metadado) |
| CPF, e-mail e telefone digitados na pergunta | **dado pessoal** que não precisa persistir: mascarado antes de gravar (`[CPF]`, `[EMAIL]`, `[TELEFONE]`) |
| nome de paciente, receita, dado de PBM | o case não trata dado de paciente (`docs/case.md` §9). Nome próprio não tem padrão para o mascaramento pegar, por isso há um risco aberto, descrito logo abaixo |
| credenciais, connection string, chave de API | segredo, nunca sai do `.env` |
| o identificador do gestor dentro de regra procedural | regra procedural vale para todos. "Regra do gestor X" é preferência e vai para a semântica, onde a remoção a alcança por chave |

**Risco aberto, declarado.** O mascaramento cobre padrões (CPF, e-mail, telefone), não nomes. Uma
pergunta com nome de paciente entra na episódica com o nome. Mitigação na v1: o agente recusa esse tipo
de pergunta (corpus `controlados-sngpc`), e episódios de execuções que terminaram em recusa por dado de
paciente não deveriam ser gravados. **Essa regra ainda não está no código**, e é a primeira pendência
desta memória para a Parte 2.

---

## Decisão 2 — Como o agente esquece

| Causa | No case | O dado é apagado? | Quando decide | Implementação |
|---|---|---|---|---|
| **contradição** | o gestor mudou a farmácia padrão | não | na leitura | `Memoria.ler_fato`: `max(valido_desde)`, descarte registrado |
| **decaimento** | o episódio tem mais de 90 dias | sim (remoção) | em rotina | `Memoria.decair(hoje)` |
| **remoção** | o gestor saiu da empresa ou pediu exclusão (LGPD) | sim, em todas as estruturas | sob demanda | `Memoria.remover_titular` + `Memoria.varrer` |

### 2.1 Contradição

**Dois fatos verdadeiros em datas diferentes, mesma pergunta:** o gestor G-0042 declarou em 10/09/2026
"minha farmácia padrão é a Drogasil" e, em 02/10/2026, "minha farmácia padrão passa a ser a Raia". As
duas declarações foram verdade, cada uma na sua data.

**O que a similaridade faz com eles** (medido): "A farmácia padrão do gestor G-0042 é a Drogasil" teve
similaridade **0,8944** com a pergunta, e "...é a Raia" teve **0,8892**. A diferença (0,0052) é ruído,
e ainda favorece a versão **antiga**. O vetor não representa anterioridade.

**Desempate determinístico, em código:** carimbo obrigatório (`gravar_fato` recusa fato sem
`valido_desde`) e `max(valido_desde)`. Em empate de data, vence o gravado por último. Não é delegado ao
modelo, porque ele erraria, gastaria uma chamada e não seria testável
(`test_contradicao_desempata_por_data_e_registra_descarte`).

**O descarte é registrado** em `descartes.jsonl` (chave, fato descartado, vencedor, regra). O fato
perdedor **não é apagado**: era verdade na data dele, e a contradição não é motivo de remoção.

O mesmo problema existe no RAG (a política 2025 contra a 2026), e lá ele é resolvido pelo mesmo
princípio: metadado de data e filtro em código (`revogado_em`), nunca similaridade.

### 2.2 Decaimento

**Corte: 90 dias, só na episódica, por remoção.** O recorte que um gestor consulta (produto × farmácia)
acompanha o portfólio monitorado e as campanhas, que mudam por trimestre. Um episódio de mais de um
trimestre descreve um portfólio que talvez nem exista mais, e puxaria o agente para um recorte velho.
Na demonstração, 7 dos 30 episódios (os de 92 a 116 dias) saíram.

**Remover, e não rebaixar:** rebaixar manteria o registro e, com ele, o identificador do gestor por
mais tempo, o que aumenta o que a remoção por titular precisa alcançar. A semântica não decai por
idade: preferência não envelhece, é substituída (contradição).

### 2.3 Remoção — a cobertura

**Estruturas onde a matrícula do gestor pode ter caído** (a lista que importa):

| # | Estrutura | Como sai |
|---|---|---|
| 1 | `episodica` (linhas do gestor) | `DELETE` |
| 2 | o **vetor** de cada episódio | está na mesma linha: sai junto (não há índice separado para reconstruir) |
| 3 | o **cache de embeddings** (`dados/cache/embeddings.db`), que guarda o vetor do texto do episódio | `DELETE` pelo hash do texto. **Escapa de quase toda lista** |
| 4 | `semantica` (chaves `usuario:<id>:*` e fatos cuja origem cita o gestor) | `DELETE` |
| 5 | `descartes.jsonl` (o registro de contradições cita a chave do gestor) | linhas removidas |
| 6 | `procedural.md`, se alguma regra mencionar o gestor | linha removida |
| 7 | **checkpoints** (guardam `usuario_id` e os argumentos de cada passo) | redigidos: a matrícula vira `[titular-removido]` e o resto da trajetória fica como evidência |
| 8 | **logs** de execução, se registrarem o gestor | redigidos, como os checkpoints |
| 9 | **páginas livres do SQLite**: um `DELETE` comum só marca a página como livre, e o texto continua nos bytes do arquivo | `PRAGMA secure_delete = ON` em todas as conexões |
| 10 | **histórico do git** | prevenção, não remoção: `dados/memoria*/` e `dados/cache/` estão no `.gitignore`, e os logs versionados são de execuções sintéticas, sem matrícula real. Se uma matrícula real for commitada, a remoção exige reescrever histórico, e isso precisa ser dito ao titular |

**Verificação independente da remoção** (`Memoria.varrer`): ela não confia no relatório de
`remover_titular`, relê cada tabela e procura a matrícula nos **bytes** de todo arquivo das pastas de
memória e de checkpoint. Na demonstração, antes da remoção, a matrícula estava na episódica (15
linhas), na semântica (3 fatos), no registro de descartes e nos bytes do `memoria.db`. Depois, não
estava em **nenhum** lugar. O teste `test_remocao_por_titular_alcanca_todas_as_estruturas` cobre
também procedural e checkpoint (que a demonstração sem LLM não exercita) e falha se qualquer
estrutura for esquecida, inclusive os bytes do arquivo SQLite (item 9).

**O esquecimento não exige reconstruir o índice.** O vetor está na linha, então remover um registro é um
`DELETE`. A remoção serve para privacidade, para custo **e para recuperação de incidente**: uma memória
envenenada sai na hora, e não na próxima reindexação.

### 2.4 O preço: o sistema deixou de ser reprodutível

A mesma pergunta ("Qual o preço atual da Trayenta 5mg?"), do mesmo gestor, no mesmo modelo, recebe
resposta diferente com e sem a preferência gravada (medido, `exercicios/aula-08-memoria-do-case.md` §8):
sem memória, o agente pergunta "Qual farmácia você quer saber o preço atual da Trayenta 5 mg?" e não
consulta nada; com "farmácia padrão: Raia", consulta a Raia e responde R$ 326,04. Isso é consequência
da Decisão 1, não defeito.

Como a Aula 11 convive com isso: **a suíte roda com a memória vazia**, congelada e declarada no carimbo
(`estado da memória: vazia`), e o checkpoint de cada execução guarda o contexto de memória que ela viu.
Avaliar o agente **com** memória exige outra suíte, com memória-fixture versionada junto do dataset. É
pendência registrada para a Parte 3.

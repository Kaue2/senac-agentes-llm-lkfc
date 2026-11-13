# Roteiro de falas — Agente de BI conversacional para farmácia

Apresentação: `apresentacao-agente-bi-farmacia.pptx` (as mesmas falas estão nas anotações de cada slide).
Duração total estimada: ~18 minutos, mais perguntas.

| Integrante | Slides | Bloco | Tempo |
|---|---|---|---|
| Kauê | 1–5 | O problema e a justificativa | ~4 min |
| Caio | 6–9 | A arquitetura | ~4 min 15 s |
| Felipe | 10–13 | Conhecimento e memória | ~4 min 30 s |
| Lucas | 14–19 | Controle e resultados | ~5 min |


## Kauê — O problema e a justificativa

### Slide 1 — Agente de BI conversacional para farmácia

Boa noite. Nós somos o Kauê, o Caio, o Felipe e o Lucas, e vamos apresentar o sistema que construímos ao longo da disciplina: um agente de BI conversacional para uma rede de farmácias.

A ideia cabe numa frase: o gestor faz uma pergunta de negócio em português, e o sistema devolve o número, de onde ele veio e, quando não tem base para responder, diz que não sabe — em vez de inventar.

Eu começo pelo problema e pela justificativa de negócio. Depois o Caio mostra a arquitetura, o Felipe fala de conhecimento, memória e prompts, e o Lucas fecha com o humano no laço, os resultados e o que vem a seguir.

### Slide 2 — Como a apresentação está dividida

(~30 s)

São quatro blocos, um por integrante, e eles seguem a ordem em que o sistema foi construído.

Primeiro, por que este problema e por que um agente. Depois, como o grafo é montado em LangGraph e onde cada decisão é do modelo, do código ou de uma pessoa. Em seguida, de onde vem o conhecimento: o RAG, a memória e os prompts versionados. E por último, como o humano entra no grafo, o que os casos demonstrados provam e como estamos montando a avaliação da Parte 3.

Tudo o que vamos mostrar está no repositório, com os logs das execuções reais.

### Slide 3 — O problema: cruzar relatórios à mão

(~1 min)

Hoje, numa rede de farmácias, uma pergunta como "qual o preço da Trayenta na Drogasil?" ou "quanto perdemos por vencimento no trimestre?" exige alguém cruzando relatórios de preço, venda e estoque à mão.

E o domínio tem armadilhas que um sistema ingênuo erra. A palavra "preço" tem quatro significados: o teto regulado pela CMED, o preço de tabela, o preço que qualquer cliente paga e o preço do programa de desconto do laboratório. Confundir os dois últimos faz o gestor comparar farmácias por um preço que só alguns clientes pagam.

O pilar de preço não é hipotético: usamos o schema real do fractal-precos, que coleta cerca de mil produtos em treze farmácias online. Nos artefatos do repositório o banco é um espelho com dados sintéticos — nenhum dado do cliente real foi versionado.

### Slide 4 — Por que um agente, e quanto se ganha

(~1 min)

Por que um agente e não um dashboard? Porque o dashboard exige que alguém preveja todos os filtros. O que precisa de decisão em tempo de execução aqui é interpretar uma pergunta que ninguém previu e decidir se ela está completa o suficiente para responder.

O ganho medido: a resposta do agente sai em 1,41 segundo, em média, nas perguntas reais. Do lado manual, montar a mesma consulta leva, pela nossa estimativa, de 3 a 6 minutos. Usando a ponta mais conservadora, é uma redução de 99%.

E a ressalva, que fazemos questão de dizer: só o lado do agente é medido; o lado manual é estimativa, porque a farmácia é hipotética. A ordem de grandeza — segundos contra minutos — não depende de acertar a estimativa no detalhe.

O outro lado da conta: o custo de rodar é zero no tier gratuito, e o limite real é o rate limit. E só um dos três pilares, o preço, tem dado hoje — vendas e estoque são o nosso maior risco declarado.

### Slide 5 — A escolha do modelo: testada, não lida

(~1 min)

Para escolher o modelo, rodamos as mesmas cinco perguntas de domínio — uma por caso difícil — em três provedores, com o mesmo prompt e o mesmo banco.

A Groq, com o gpt-oss-120b, e o OpenRouter acertaram as cinco. O Gemini acertou só uma, mas não por erro de raciocínio: o tier gratuito dele bloqueou a partir da segunda chamada, com 5 requisições por minuto. Para um agente que sempre faz duas ou mais chamadas por pergunta, isso é eliminatório — e só apareceu rodando, não na tabela de especificação.

Entre os dois que acertaram, a Groq usou cerca de 40% menos tokens. Ficou como modelo ativo. Como toda a pilha usa a biblioteca openai com base_url configurável, trocar de provedor é trocar três variáveis no .env, sem mudar código.

Com isso eu passo para o Caio, que vai mostrar como o sistema é montado.


## Caio — A arquitetura

### Slide 6 — O grafo: quem decide cada passo

Obrigado, Kauê. Este é o grafo que roda hoje, em LangGraph. As cores dizem quem decide: âmbar é o modelo, verde-azulado é código, vermelho é uma pessoa.

A mensagem entra e é validada. Em paralelo, carregamos a memória do gestor e a triagem — que é o modelo — classifica a mensagem em três rotas: atender, esclarecer ou fora do escopo. O portão é código: ele lê a rota e garante que o sistema pergunta de volta no máximo uma vez.

Se a rota é atender, entra o laço do agente: o modelo escolhe uma ferramenta — consultar preço, buscar na base de conhecimento — e o resultado volta para ele, até ele responder. Se ele pedir para exportar a análise, o grafo para e espera uma pessoa aprovar. O Lucas vai detalhar esse ponto.

No fim, a saída é montada e validada em código, e o episódio vai para a memória. Só duas caixas são do modelo; todo o resto é código.

### Slide 7 — Os padrões usados, e o nível de autonomia

(~1 min)

Usamos os padrões da aula de arquitetura e justificamos cada um pelo degrau de baixo.

O portão é o degrau mais simples: um if sobre um campo. A triagem é um router, porque decidir que "quanto custa a Trayenta" está completo e "quanto tá o remédio na Drogasil" não está exige julgamento sobre texto livre — nenhuma regra separa as duas sem virar um parser de português. A memória e a triagem rodam em paralelo; medimos, e o ganho é real mas pequeno, porque a memória é muito mais rápida que a chamada ao modelo.

O laço de agente está lá porque o número de consultas depende do que a consulta anterior devolveu. Mas ele está contido numa caixa: só entra o que a triagem aprovou, as ferramentas são de leitura, a única escrita para numa pessoa, e quem decide sair do laço é código.

E os padrões que não usamos: orquestrador-trabalhador, porque não há subtarefas para distribuir, e avaliador-otimizador, porque a verificação da resposta é feita em código, sem gastar uma chamada a mais.

### Slide 8 — Estado, orçamento e o que o LangGraph não deu

(~1 min)

O estado que atravessa o grafo é uma declaração de tipo, com 22 campos. Decisões, contadores e identificadores são campos, não texto perdido na lista de mensagens. Os campos escritos em paralelo têm reducer, e temos um script que mostra o que se perde quando o reducer é tirado.

O orçamento é verificado em código antes de cada chamada ao modelo: 8 passos, 20 mil tokens e 90 segundos por turno. O detector de laço para a execução quando a mesma ferramenta é chamada com os mesmos argumentos pela terceira vez.

E o que o LangGraph não deu: ele diz que a execução acabou, mas não por quê. Escrevemos uma taxonomia de 15 motivos de término, que vai em toda saída. Os tetos, o detector de laço e a separação entre erro recuperável e fatal somaram cerca de 108 linhas.

Um detalhe que aprendemos: o limite de recursão padrão do framework passou de 25 para 10.007 entre versões. Por isso fixamos a versão e definimos o limite explicitamente.

### Slide 9 — O contrato: texto entra, objeto validado sai

(~1 min)

O contrato com quem usa o sistema: a entrada é texto livre, até 800 caracteres, mais a matrícula e a sessão, que vêm do sistema interno e não são digitadas.

A saída é um objeto validado com Pydantic. Ele traz o resultado, as fontes — e cada fonte precisa estar na trajetória de ferramentas daquele turno, senão vira alerta —, as suposições que o sistema fez, e a suficiência.

O ponto mais importante: a suficiência é decidida em código, não pelo modelo. Se não há fonte do banco ou trecho citado, a saída é "insuficiente" e diz por quê. A recusa faz parte do contrato.

Este exemplo é real, copiado do log: o preço da Novalgina na Araujo, com a view e o filtro de onde veio e a data da coleta.

Agora o Felipe vai falar de onde vem o conhecimento que o agente usa.


## Felipe — Conhecimento e memória

### Slide 10 — RAG: duas formas de recuperar

Obrigado, Caio. Classificamos as perguntas do case antes de escolher como recuperar, e o resultado foi que a maior parte não precisa de embedding.

Preço, histórico e ruptura são registros: respondem com SQL parametrizado sobre as views do fractal-precos. Já as regras — teto de desconto, como funciona o PBM, quando uma falta é ruptura confirmada — vêm de um corpus de 12 documentos que escrevemos, indexado com o modelo multilingual-e5-large.

O corte foi por estrutura, uma seção por trecho. Comparado com blocos de 1.200 caracteres, o acerto no primeiro resultado subiu de 69% para 87,5%, ocupando só 5% do corpus na janela. Usamos k igual a 3, e um limiar de distância que recusa as perguntas sem resposta no corpus.

E a recuperação é uma ferramenta do agente, não uma etapa fixa: a maioria das perguntas é de preço, e buscar regras em toda execução encheria a janela com política onde ninguém pediu.

### Slide 11 — O documento revogado: curadoria, não busca

(~1 min)

Este é o caso que decidiu a arquitetura do RAG. Colocamos de propósito no corpus a política de precificação de 2025, que foi revogada. Ela diz 10% onde a de 2026 diz 15%.

No índice, os dois trechos ficam a 0,0009 de distância. O vetor não tem como saber que um documento não vale mais: os dois dizem a mesma coisa, com outro número. Sem tratamento, o trecho revogado entra no contexto, e no exercício da aula 7 a resposta chegou a trazer os dois valores sem dizer qual vale.

A solução não foi ajustar a busca. Foi curadoria: o documento tem um campo revogado_em no cabeçalho, e a ferramenta filtra os vigentes antes da similaridade. O documento continua no corpus para auditoria, mas nunca chega a uma pergunta sobre a regra atual.

O limite declarado: se alguém publicar a política de 2027 sem marcar a de 2026 como revogada, as duas voltam a competir. Essa regra é do dono do documento.

### Slide 12 — Memória: o que lembra e o que esquece

(~1 min 15 s)

O RAG consulta documentos que alguém escreveu; a memória guarda o que o próprio sistema viveu. Temos três: a episódica, com o recorte das perguntas que o gestor já fez, buscada por similaridade; a semântica, com preferências declaradas, como "minha farmácia padrão é a Raia"; e a procedural, com regras que só o time de BI escreve.

Tão importante quanto o que guardamos é o que não guardamos: nenhum número que uma ferramenta devolveu, porque o preço estaria velho em 24 horas, nem o texto das próprias respostas. E execução recusada — por exemplo, uma pergunta com CPF de paciente — não grava nada.

O sistema esquece de três jeitos: por contradição, quando a preferência muda; por decaimento, depois de 90 dias; e por remoção, quando o gestor pede exclusão. A remoção alcança 13 estruturas, inclusive os checkpoints do LangGraph. E uma delas foi achada pelo teste, não pela lista: a matrícula continuava no arquivo WAL do SQLite depois de apagada.

### Slide 13 — Prompts versionados e a regra da frase

(~1 min)

Os prompts vivem em arquivo, versionados, e a versão vai carimbada em toda execução: o git diz como o prompt mudou, o carimbo diz qual versão rodou.

A triagem usa few-shot com seis exemplos e saída JSON validada. Avaliamos em 14 mensagens rotuladas: acertou as 14 rotas, e nenhuma pergunta com dado de paciente foi atendida.

E aplicamos a regra da frase: se você apaga uma frase do prompt e não sabe dizer o que ela impedia, ela não fazia nada. Tiramos a frase "farmácia omitida não é recorte faltando". Resultado: nas duas repetições, o sistema voltou a perguntar "em qual farmácia?" para "quanto custa a Trayenta" — justamente o que a frase impedia. A frase voltou; custa 16 tokens por chamada.

O detalhe que nos ensinou mais: sem a frase, o placar ainda passava no critério de aprovação. A regressão só apareceu olhando linha por linha — por isso a avaliação grava cada linha, não só o placar.

Passo para o Lucas.


## Lucas — Controle e resultados

### Slide 14 — Humano no laço: para, espera e não duplica

Obrigado, Felipe. O único ponto em que o sistema escreve algo é exportar a análise para um arquivo. Parecia um detalhe, mas o pedido real — "salva essa análise pra eu mandar pra diretoria" — mostrou que o arquivo sai do sistema e vira base de decisão. Por isso é o único lugar em que o grafo para e espera uma pessoa.

O revisor vê a ação, os argumentos, a consequência e o prazo. Ele pode aprovar, rejeitar ou aprovar editando o texto. A pausa fica gravada no checkpoint, então a resposta pode vir de outro terminal, horas depois. Se ninguém responder em 24 horas, a execução expira e nada é exportado — um ponto de parada que segue em silêncio deixaria de ser ponto de parada.

E aprovar duas vezes não exporta duas vezes. O nome do arquivo é um hash do conteúdo, e ele só é criado se não existir. No caso demonstrado, entregamos a mesma aprovação duas vezes a partir do mesmo checkpoint: a pasta de exportações foi de zero para um arquivo, e continuou com um.

### Slide 15 — Os seis casos demonstrados, com log real

(~1 min)

Rodamos seis casos que cobrem os caminhos que importam, e cada um tem o log real no repositório.

O caso simples mostra que o caminho feliz existe. Na divergência, o gestor afirma que a Trayenta custa 150 reais; o sistema consulta, mostra o valor do banco com a data e destaca a diferença, sem concordar e sem meio-termo. No registro inexistente, a ferramenta devolve "não encontrado" como dado, e o modelo não inventa nem insiste. No fora do corpus, ele recusa dizendo o que sabe fazer. E o sexto é a pausa com aprovação que acabei de mostrar.

O caso 4 merece honestidade. Ele passou no que testava: não exportou sem pedido. Mas tem um erro de domínio: pela regra da rede, sem coleta há mais de 3 dias a situação é "sem coleta recente", não ruptura. O modelo não buscou a regra, porque não sabia que ela existia. É o defeito típico da recuperação como ferramenta, e a correção certa é marcar isso na própria ferramenta de preço. Está registrado como pendência.

No verificador do pilar preço, da Parte 1, foram 12 de 12 valores certos na leitura manual, e zero confusões entre preço da farmácia e preço PBM.

### Slide 16 — O agente rodando: uma pergunta real

(~45 s)

Para mostrar o sistema funcionando, este é o comando de demonstração rodando de verdade, com uma pergunta livre: "o Ozempic está em falta em alguma farmácia?".

A triagem decide que dá para atender. O agente chama uma ferramenta só, a consulta de preços, que olha a view de ruptura. A resposta diz que o Ozempic está em falta na Drogasil desde 16 de setembro, e traz a fonte: a view, o filtro e a data da última coleta.

A suficiência é "suficiente" porque existe fonte do banco — e quem decide isso é o código. Tudo em 2,6 segundos.

Qualquer pessoa pode repetir isso com um comando: python demo.py. Sem argumentos, ele roda as cinco cenas que mostramos: preço com fonte, regra com citação, pergunta incompleta, recusa de dado de paciente e a exportação que para e espera aprovação.

### Slide 17 — A avaliação, desenhada antes de rodar

(~1 min)

Já começamos a Parte 3, que é colocar o sistema sob controle. A primeira frente é a avaliação.

Montamos um golden dataset com 24 casos em 9 classes, a partir dos embriões que já existiam: o verificador da Parte 1, as demonstrações e as perguntas do RAG.

Para as classes críticas — recusa, registro inexistente, exportação e o rótulo do PBM — a medida é pass^k: passar em todas as repetições, não em pelo menos uma. O gestor faz a pergunta uma vez; um agente que acerta "pelo menos uma vez em duas" erra metade das vezes.

E a regra de promoção foi escrita antes de qualquer execução: uma versão nova só substitui a atual se melhorar acima do ruído medido entre duas execuções da mesma versão, se nenhuma classe cair, e se as críticas passarem em 100% das repetições.

Além disso, o repositório tem 110 testes automatizados, e fizemos um servidor MCP de CNPJ e CEP, uma das frentes opcionais.

### Slide 18 — O que ainda falta, dito por nós

(~45 s)

Fechamos com as limitações, porque preferimos dizer antes de alguém perguntar.

Vendas e estoque continuam sem dado: dois dos três pilares prometidos. As ferramentas já existem e devolvem "não implementado" como dado, então o agente não inventa — mas o ganho de cruzar os três pilares ainda não está entregue.

Há pendências técnicas pequenas e identificadas: levar a regra da coleta recente para a ferramenta de preço, que é o erro do caso 4; gravar na memória a pergunta reescrita pela triagem; e o limiar do RAG, que foi calibrado com só 4 perguntas sem resposta.

E o resto da Parte 3: governança, segurança e observabilidade, sobre o sistema que acabamos de mostrar.

### Slide 19 — Obrigado. Perguntas?

Para resumir em uma frase: um agente que responde perguntas de negócio de farmácia, com fonte conferível, que sabe dizer "não sei", e que para e pergunta a uma pessoa antes de fazer qualquer coisa que saia do sistema.

Tudo o que mostramos tem log real no repositório e roda do zero com os comandos do README. Obrigado — ficamos à disposição para perguntas.

(Sugestão para as perguntas: cada um responde sobre o próprio bloco — Kauê: case e modelos; Caio: grafo e estado; Felipe: RAG, memória e prompts; Lucas: humano no laço e avaliação.)


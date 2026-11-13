# Roteiro de falas — Agente de BI conversacional para farmácia

Apresentação: `apresentacao-agente-bi-farmacia.pptx` (as mesmas falas estão nas anotações de cada slide).
Duração total estimada: ~14 minutos, com ~3 minutos de demonstração (`python demo.py`).

| Integrante | Slides | Bloco | Tempo |
|---|---|---|---|
| Kauê | 1–3 | O problema | ~2 min 30 s |
| Caio | 4–6 | Arquitetura e integrações | ~3 min 30 s |
| Felipe | 7–9 | Conhecimento e demonstração | ~5 min (com a demo) |
| Lucas | 10–13 | Governança e segurança | ~3 min 30 s |


## Kauê — O problema

### Slide 1 — Agente de BI conversacional para farmácia

Boa noite. Nós somos o Kauê, o Caio, o Felipe e o Lucas, e vamos mostrar o agente que construímos na disciplina: um agente de BI para uma rede de farmácias.

O gestor faz uma pergunta de negócio em português, e o sistema responde com o número e de onde ele veio. Quando não tem base para responder, ele diz que não sabe.

Eu falo do problema. O Caio mostra a arquitetura e as integrações, o Felipe mostra de onde vem o conhecimento e a demonstração, e o Lucas fecha com governança e segurança.

### Slide 2 — O problema: cruzar relatórios à mão

(~1 min)

Hoje, numa rede de farmácias, uma pergunta simples como "qual o preço da Trayenta na Drogasil?" exige alguém cruzando relatórios à mão.

E o domínio tem armadilhas. A palavra "preço" tem quatro significados: o teto do governo, o preço de tabela, o preço que qualquer cliente paga e o preço do programa de desconto do laboratório. Se o sistema confunde os dois últimos, o gestor compara farmácias por um preço que só alguns clientes pagam.

Outra armadilha: o gestor quase nunca diz tudo. "Quanto tá o remédio na Drogasil?" não diz qual remédio. O sistema precisa perceber e perguntar.

E o dado é real: usamos a estrutura do fractal-precos, um sistema que coleta cerca de mil produtos em treze farmácias online.

### Slide 3 — Por que um agente, e quanto se ganha

(~1 min)

Por que um agente e não um dashboard? Porque o dashboard só responde o que alguém previu. O agente interpreta a pergunta que ninguém previu e percebe quando ela está incompleta.

O ganho: a resposta do agente sai em 1,4 segundo, em média. Montar a mesma consulta à mão leva, pela nossa estimativa, de 3 a 6 minutos. Só o lado do agente é medido; o lado manual é estimativa. Mas a diferença é de segundos contra minutos.

Para o modelo, testamos três provedores com as mesmas perguntas. Ficamos com o gpt-oss-120b na Groq: acertou tudo, gastou menos tokens e não travou no limite do plano gratuito, como aconteceu com o Gemini. O custo por pergunta é zero.

Agora o Caio mostra como o sistema é montado.


## Caio — Arquitetura e integrações

### Slide 4 — O grafo: quem decide cada passo

Obrigado, Kauê. Este é o desenho do sistema, feito em LangGraph. As cores mostram quem decide cada passo: laranja é o modelo, verde é o código, vermelho é uma pessoa.

A pergunta entra. Ao mesmo tempo, o sistema carrega a memória do gestor, e a triagem lê a pergunta para decidir: dá para responder, falta informação, ou está fora do assunto?

Se dá para responder, entra o agente. Ele escolhe o que consultar e repete até ter a resposta. Se o gestor pedir para salvar a análise, o sistema para e espera uma pessoa aprovar.

No fim, o código monta a resposta e confere se ela tem fonte. Só duas caixas são do modelo; o resto é código.

### Slide 5 — Os padrões usados, e o nível de autonomia

(~1 min)

Usamos os padrões da aula de arquitetura, sempre escolhendo o mais simples que resolve.

Para checar se a mensagem é válida, basta um if no código. Para saber se a pergunta está completa, precisamos do modelo: "quanto custa a Trayenta" está completa, "quanto tá o remédio na Drogasil" não está, e uma regra fixa não separa as duas. A memória e a triagem rodam ao mesmo tempo, porque uma não depende da outra.

O agente só aparece onde precisa: quando o número de consultas depende do que a consulta anterior trouxe. E ele fica dentro de uma caixa: só recebe o que a triagem aprovou, só lê dados, e a única escrita passa por uma pessoa. Também há limites em código: no máximo 8 passos, 20 mil tokens e 90 segundos por pergunta.

### Slide 6 — Integrações: ferramentas, APIs e MCP

(~1 min 15 s)

Estas são as integrações do agente com o mundo de fora.

São cinco ferramentas. A principal consulta preço no banco SQL Server do fractal-precos; se o banco não estiver acessível, ela cai sozinha num espelho em SQLite com a mesma estrutura. A segunda busca as regras da rede numa base de documentos, com embeddings rodando localmente. Vendas e estoque já existem como ferramentas, mas ainda não têm dado: respondem "não implementado", e o agente explica isso em vez de inventar. A quinta é a única que escreve: salva a análise num arquivo, e só depois que uma pessoa aprova.

O modelo é chamado por uma API compatível com a da OpenAI. Trocar de provedor é trocar três variáveis no .env, sem mexer no código.

E fizemos um servidor MCP próprio, que consulta CNPJ e CEP na BrasilAPI, com um cliente separado. Ele é uma frente opcional e ainda não está ligado ao grafo.

Agora o Felipe mostra de onde vem o conhecimento do agente.


## Felipe — Conhecimento e demonstração

### Slide 7 — RAG: duas formas de recuperar

Obrigado, Caio. Antes de escolher como buscar, classificamos as perguntas do case. A maior parte nem precisa de embedding.

Preço, histórico e falta de produto são registros: respondem com SQL. Já as regras da rede — teto de desconto, como funciona o programa do laboratório — vêm de 12 documentos que escrevemos, buscados por similaridade.

Cortamos os documentos por seção, e isso subiu o acerto do primeiro resultado de 69% para 87,5%. Um limiar de distância faz o sistema recusar perguntas que a base não responde.

E um caso que nos ensinou muito: a política de 2025, revogada, ficou a 0,0009 de distância da política de 2026 no índice. A busca não separa as duas. A solução foi marcar o documento como revogado e filtrar antes de buscar.

### Slide 8 — Memória: o que lembra e o que esquece

(~1 min)

O RAG consulta documentos que alguém escreveu; a memória guarda o que o próprio sistema viveu. São três: as perguntas que o gestor já fez, as preferências dele — como "minha farmácia padrão é a Raia" — e as regras que só o time de BI escreve.

O que não guardamos é tão importante quanto o que guardamos: nenhum preço, porque ele estaria velho no dia seguinte, nem o texto das próprias respostas. E pergunta recusada, como uma com CPF de paciente, não grava nada.

O sistema também esquece: quando a preferência muda, depois de 90 dias, ou quando o gestor pede exclusão. Agora vamos ver tudo isso funcionando.

### Slide 9 — Demonstração: o agente rodando

(~3 min — narre o vídeo ou a execução ao vivo)

[Toque o vídeo gravado de "python demo.py" — ou rode ao vivo no terminal.]

São cinco cenas, todas com o modelo de verdade.

Cena 1: uma pergunta de preço. Reparem que a resposta traz a fonte: a view, o filtro e a data da coleta.

Cena 2: uma pergunta sobre regra. O agente decide sozinho buscar na base de documentos e cita o trecho que usou.

Cena 3: a pergunta não diz qual remédio. O sistema pergunta uma vez só e, com a resposta, consulta.

Cena 4: a pergunta tem CPF de paciente e remédio controlado. A triagem recusa antes de qualquer consulta, e explica o que o sistema faz.

Cena 5: o gestor pede para salvar a análise. O sistema para e mostra o que vai fazer e o prazo. Depois da aprovação, ele grava. E se a mesma aprovação chegar duas vezes, não cria um segundo arquivo.

O Lucas vai explicar por que essas duas últimas cenas importam.


## Lucas — Governança e segurança

### Slide 10 — Governança: a única escrita para numa pessoa

Obrigado, Felipe. O desafio de governança deste agente é a cena 5. O sistema só lê dados; a única coisa que ele escreve é a análise exportada. Parecia um detalhe, mas o pedido real — "salva pra eu mandar pra diretoria" — mostrou que esse arquivo sai do sistema e vira base de decisão.

Por isso é o único ponto em que o grafo para e espera uma pessoa. Ela vê a ação, a consequência e o prazo, e pode aprovar, rejeitar ou corrigir o texto. Se ninguém responder em 24 horas, nada é exportado.

E aprovar duas vezes não exporta duas vezes: o nome do arquivo é calculado pelo conteúdo. Além disso, toda execução fica registrada com o modelo, a versão do prompt e o motivo de término, então dá para reconstruir por que o sistema respondeu o que respondeu.

### Slide 11 — Segurança: riscos e controles em código

(~1 min 15 s)

E a segurança. A regra que seguimos: nenhum controle importante depende só de o modelo obedecer ao prompt. Cada risco tem um controle em código.

Dado de paciente na pergunta: a triagem recusa antes de qualquer ferramenta, como vocês viram na cena 4.

O agente agir sozinho: as ferramentas só leem, e a única escrita passa por uma pessoa.

Resposta inventada: quem decide se a resposta tem base é o código. Sem fonte na consulta, a saída é "não sei".

Agente em laço ou gastando demais: há tetos de passos, tokens e tempo, e um detector que para quando a mesma consulta se repete.

Memória: ela não guarda números nem respostas, e um pedido de exclusão apaga o gestor de 13 lugares — inclusive um que só o teste encontrou.

E segredos: a chave da API e o acesso ao banco ficam no .env, fora do git, e os logs com dado real também.

### Slide 12 — Resultados e o que ainda falta

(~1 min)

Os números que sustentam o que mostramos: nos testes de preço, 12 de 12 valores certos e nenhuma confusão entre o preço da farmácia e o do programa de desconto. A triagem acertou as 14 mensagens de teste, sem atender nenhuma com dado de paciente. E o projeto tem 110 testes automatizados.

O que ainda falta, dito por nós: vendas e estoque não têm dado, então dois dos três pilares respondem só "não implementado". Num dos casos, o agente chamou de falta de produto o que a regra da rede chama de "sem coleta recente" — a correção é levar essa regra para a própria ferramenta. E o servidor MCP ainda não está ligado ao grafo.

### Slide 13 — Obrigado. Perguntas?

Resumindo: um agente que responde perguntas de negócio de farmácia com fonte conferível, que sabe dizer "não sei", e que para e pergunta a uma pessoa antes de fazer qualquer coisa que saia do sistema.

Tudo o que mostramos roda com um comando — python demo.py — e tem log real no repositório. Obrigado, e ficamos à disposição para perguntas.

(Nas perguntas, cada um responde sobre o próprio bloco — Kauê: problema e modelo; Caio: arquitetura e integrações; Felipe: RAG, memória e demo; Lucas: governança e segurança.)


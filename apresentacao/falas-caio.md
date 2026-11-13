# Falas do Caio — Arquitetura e integrações (slides 4 a 6)

Tempo: cerca de 3 minutos e meio. Você entra depois do Kauê e passa a palavra para o Felipe.

---

## Slide 4 — O grafo: quem decide cada passo

Obrigado, Kauê. Este é o desenho do sistema, feito em **LangGraph**. As cores mostram quem decide cada passo: **laranja é o modelo**, **verde é o código** e **vermelho é uma pessoa**.

A pergunta do gestor entra. Ao mesmo tempo, o sistema carrega a memória dele e a **triagem** lê a pergunta para decidir: dá para responder, falta informação ou está fora do assunto?

Se dá para responder, entra o **agente**. Ele escolhe o que consultar e repete até ter a resposta. Se o gestor pedir para salvar a análise, o sistema **para e espera uma pessoa aprovar**.

No fim, o código monta a resposta e confere se ela tem fonte. **Só duas caixas são do modelo; o resto é código.**

---

## Slide 5 — Os padrões usados

Usamos os padrões que vimos na aula de arquitetura, sempre escolhendo o mais simples que resolve.

- Para checar se a mensagem é válida, basta um **if** no código.
- Para saber se a pergunta está completa, precisamos do **modelo**: "quanto custa a Trayenta" está completa, "quanto tá o remédio na Drogasil" não está. Uma regra fixa não separa as duas.
- A memória e a triagem rodam **ao mesmo tempo**, porque uma não depende da outra.
- O **agente** só aparece onde precisa: quando o número de consultas depende do que a consulta anterior trouxe.

Mas ele fica **dentro de uma caixa**: só recebe o que a triagem aprovou, só lê dados, e a única escrita passa por uma pessoa. E há limites no código: no máximo **8 passos, 20 mil tokens e 90 segundos** por pergunta.

---

## Slide 6 — Integrações: ferramentas, APIs e MCP

Estas são as ligações do agente com o mundo de fora. São **cinco ferramentas**:

- **consultar_precos** busca o preço no banco **SQL Server** do fractal-precos. Se o banco não estiver acessível, ela usa sozinha uma cópia local com a mesma estrutura.
- **consultar_base_conhecimento** busca as regras da rede em 12 documentos que escrevemos.
- **consultar_vendas** e **consultar_estoque** já existem, mas ainda não têm dado. Elas respondem "não implementado", e o agente explica isso em vez de inventar.
- **exportar_analise** é a única que escreve: salva a análise num arquivo, e **só depois que uma pessoa aprova**.

O modelo é chamado por uma **API compatível com a da OpenAI**. Trocar de provedor é mudar o arquivo `.env`, sem mexer no código.

E fizemos um **servidor MCP** próprio, que consulta CNPJ e CEP na BrasilAPI. Ele é opcional e ainda não está ligado ao grafo.

Agora o Felipe vai mostrar de onde vem o conhecimento do agente.

---

## Se perguntarem

- **Por que LangGraph?** Porque o sistema é um fluxo com várias rotas e uma pausa para aprovação humana. O LangGraph já resolve a pausa e a retomada salvas em disco.
- **Por que não vários agentes?** Um agente só, com 5 ferramentas, resolve todos os casos. Vários agentes só valem a pena quando vendas e estoque tiverem dados.
- **Por que o MCP não está no grafo?** Ele foi feito como exercício da aula de MCP. Ligá-lo ao agente é o próximo passo, quando houver mais de um agente usando a mesma ferramenta.
- **O que acontece se o modelo errar a triagem?** Medimos em 14 mensagens e ele acertou todas. Se a resposta da triagem vier quebrada, o sistema segue para o agente, que ainda tem as próprias regras.

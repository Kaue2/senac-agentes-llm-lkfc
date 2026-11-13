# Falas do Caio — A arquitetura (slides 6 a 9)

Tempo: cerca de 3 a 4 minutos. Você entra depois do Kauê e passa a palavra para o Felipe.

---

## Slide 6 — O grafo: quem decide cada passo

Obrigado, Kauê. Este é o desenho do sistema. As cores mostram quem decide cada passo: **laranja é o modelo**, **verde é o código** e **vermelho é uma pessoa**.

A pergunta do gestor entra. Ao mesmo tempo, o sistema carrega a memória dele e a **triagem** lê a pergunta para decidir: dá para responder, falta informação ou está fora do assunto?

Se dá para responder, entra o **agente**. Ele escolhe o que consultar — o preço, as regras da rede — e repete até ter a resposta. Se o gestor pedir para salvar a análise, o sistema **para e espera uma pessoa aprovar**. O Lucas vai mostrar essa parte.

No fim, o código monta a resposta e confere se ela está certa. **Só duas caixas são do modelo; o resto é código.**

---

## Slide 7 — Os padrões usados

Usamos os padrões que vimos na aula de arquitetura, sempre escolhendo o mais simples que resolve.

- Para checar se a mensagem é válida, basta um **if** no código.
- Para saber se a pergunta está completa, precisamos do **modelo**: "quanto custa a Trayenta" está completa, "quanto tá o remédio na Drogasil" não está. Uma regra fixa não separa as duas.
- A memória e a triagem rodam **ao mesmo tempo**, porque uma não depende da outra.
- O **agente** só aparece onde precisa: quando o número de consultas depende do que a consulta anterior trouxe.

Mas ele fica **dentro de uma caixa**: só recebe o que a triagem aprovou, só lê dados, e a única escrita passa por uma pessoa.

---

## Slide 8 — Estado, limites e o que o LangGraph não deu

O sistema guarda tudo o que acontece num **estado com 22 campos**, cada um com tipo definido.

Para ele não rodar sem parar, colocamos **limites**: no máximo 8 passos, 20 mil tokens e 90 segundos por pergunta. E se ele chamar a mesma consulta três vezes seguidas, a gente para: é um laço.

O LangGraph não fazia tudo isso. Ele avisa que a execução acabou, mas não diz **por quê**. Então criamos 15 motivos de término, que aparecem em toda resposta. No total, foram cerca de **108 linhas** que tivemos que escrever.

---

## Slide 9 — O contrato: texto entra, objeto validado sai

A entrada é simples: o gestor escreve a pergunta em texto livre.

A saída é sempre no mesmo formato. Ela traz:

- a **resposta**;
- a **fonte** de onde o número veio;
- as **suposições** que o sistema fez;
- e se a resposta é **suficiente** ou não.

O ponto principal: **quem decide se a resposta é suficiente é o código, não o modelo**. Se não houver fonte, o sistema responde "não sei" e explica o motivo.

Este exemplo é real: o preço da Novalgina na Araujo, com a origem do dado e a data da coleta.

Agora o Felipe vai mostrar de onde vem o conhecimento do agente.

---

## Se perguntarem

- **Por que LangGraph?** Porque o sistema é um fluxo com várias rotas e uma pausa para aprovação humana. O LangGraph já resolve a pausa e a retomada salvas em disco.
- **Por que não vários agentes?** Um agente só, com 5 ferramentas, resolve todos os casos. Vários agentes só valem a pena quando vendas e estoque tiverem dados.
- **O que acontece se o modelo errar a triagem?** Medimos em 14 mensagens e ele acertou todas. Se a resposta da triagem vier quebrada, o sistema segue para o agente, que ainda tem as próprias regras.

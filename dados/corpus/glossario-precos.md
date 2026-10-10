---
id: glossario-precos
titulo: Glossário de preços do monitoramento de concorrência
tipo: glossario
versao: 3
vigente_desde: 2026-01-15
revogado_em:
dono: Inteligência Comercial
---

# Glossário de preços do monitoramento de concorrência

Este glossário define os campos de preço usados em todos os relatórios de concorrência e nas
respostas do agente de BI. Quando um relatório e este glossário divergirem, vale o glossário.

## PMC — Preço Máximo ao Consumidor

O PMC é o teto de preço ao consumidor definido pela CMED (Câmara de Regulação do Mercado de
Medicamentos) para cada apresentação de medicamento. Nenhuma farmácia pode vender acima do PMC.
O PMC é reajustado uma vez por ano por autorização da CMED. O PMC não é coletado pelo
monitoramento: ele vem da lista oficial da CMED e é usado apenas como referência.

## PrecoTabela

PrecoTabela é o preço cheio exibido pela farmácia no site, antes de qualquer desconto. Na
prática ele fica igual ou muito próximo do PMC, mas não é a mesma coisa: o PMC é regulado, o
PrecoTabela é o que a farmácia escolheu exibir como preço "de".

## PrecoFarmacia

PrecoFarmacia é o preço efetivamente praticado para qualquer cliente que entra no site, sem
cadastro em programa nenhum. É o preço "por" da vitrine. Para comparar farmácias entre si,
o campo correto é sempre o PrecoFarmacia.

## PrecoPbm

PrecoPbm é o preço com o desconto de um Programa de Benefício em Medicamentos (PBM) do
laboratório. Ele só vale para o paciente cadastrado no programa, e só existe quando a
farmácia aderiu ao programa daquele produto. O PrecoPbm nunca deve ser usado para comparar
farmácias como se fosse preço de prateleira: um gestor que compara PrecoPbm de uma farmácia
com PrecoFarmacia de outra está comparando públicos diferentes.

## Desconto praticado

O desconto praticado de uma farmácia sobre um produto é calculado como
1 − (PrecoFarmacia ÷ PrecoTabela). O desconto do PBM não entra nesse cálculo, porque é
concedido pelo laboratório e não pela farmácia.

## Produto de referência e genérico

Produto de referência é o medicamento inovador registrado na Anvisa (por exemplo, a Trayenta).
O genérico tem o mesmo princípio ativo, a mesma dose e a mesma forma farmacêutica (por exemplo,
a Linagliptina genérica). No cadastro, o genérico aponta para o seu produto de referência pelo
campo ProdutoReferenciaId.

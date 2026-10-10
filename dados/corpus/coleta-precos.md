---
id: coleta-precos
titulo: Como a coleta de preços de concorrência funciona
tipo: procedimento
versao: 2
vigente_desde: 2026-02-01
revogado_em:
dono: Engenharia de Dados
---

# Como a coleta de preços de concorrência funciona

## Cobertura

O monitoramento coleta cerca de 1.000 SKUs nos sites de 13 redes de farmácia, uma vez por dia.

## Janela de coleta

A rodada diária de coleta roda entre 02:00 e 06:00, no horário de Brasília. Um preço alterado
pela farmácia durante o dia só aparece no banco na rodada do dia seguinte.

## CEP de referência

Algumas redes exibem preço diferente por região. A coleta usa sempre o mesmo CEP de referência,
da capital paulista, para que a série seja comparável no tempo. O preço coletado não representa
o preço de outras regiões.

## O que não é coletado

O preço coletado não inclui frete, não inclui cupom de desconto e não inclui preço de assinatura
ou de compra recorrente. Esses valores dependem do cliente e não são públicos.

## Exceção: PBM que exige login

Quando o site da farmácia só mostra o preço do PBM depois que o cliente faz login, o campo
PrecoPbm fica nulo mesmo que o programa exista para aquele produto naquela farmácia.

## Falha de coleta

Quando a página de um produto não carrega, a coleta daquele produto naquele dia é descartada, e
não gravada como indisponível. Por isso pode haver dias sem coleta na série de um produto.

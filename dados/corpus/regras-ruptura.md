---
id: regras-ruptura
titulo: Regras de ruptura e disponibilidade no monitoramento
tipo: procedimento
versao: 2
vigente_desde: 2026-04-10
revogado_em:
dono: Inteligência Comercial
---

# Regras de ruptura e disponibilidade no monitoramento

Ruptura é a situação em que um produto monitorado numa farmácia aparece como indisponível para
compra no site. Este documento define quando o agente de BI pode chamar uma situação de
ruptura, e quando não pode.

## Definição de ruptura

Um produto está em ruptura numa farmácia quando a coleta mais recente registra Disponivel = 0
para um produto que está cadastrado para aquela farmácia em ProdutoFarmacia. O início da
ruptura é o campo DesdeQuando da view vw_Ruptura.

## Ruptura confirmada e ruptura a confirmar

Para alertar a gestão, a ruptura só é reportada como confirmada depois de pelo menos 2 coletas
consecutivas com o produto indisponível. Com uma única coleta indisponível, a situação deve ser
reportada como ruptura a confirmar, porque falhas pontuais de carregamento do site produzem
indisponibilidade falsa.

## Exceção: sem coleta recente

Se a última coleta de um produto numa farmácia tem mais de 3 dias, a situação não é ruptura:
é sem coleta recente. Nesse caso o agente informa a data da última coleta e não afirma nada
sobre a disponibilidade atual.

## Exceção: produto descontinuado

Produto descontinuado pelo fabricante não é ruptura. Quando a descontinuação é comunicada, o
produto é retirado do cadastro de monitoramento daquela farmácia, e deixa de aparecer nas views.

## Exceção: produto não cadastrado na farmácia

Um produto que não está cadastrado para uma farmácia não está em ruptura nela — ele simplesmente
não é monitorado ali. O agente deve dizer que não há monitoramento daquele produto naquela
farmácia, e não que o produto está em falta.

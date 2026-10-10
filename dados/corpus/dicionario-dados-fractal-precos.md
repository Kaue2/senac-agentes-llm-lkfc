---
id: dicionario-dados-fractal-precos
titulo: Dicionário de dados do banco de preços (fractal-precos)
tipo: dicionario
versao: 2
vigente_desde: 2026-02-01
revogado_em:
dono: Engenharia de Dados
---

# Dicionário de dados do banco de preços (fractal-precos)

O banco de preços guarda a coleta diária dos sites das farmácias monitoradas. As consultas do
agente de BI leem sempre as views, nunca as tabelas brutas, para que a regra de "preço atual"
e de "ruptura" seja a mesma em todos os relatórios.

## Tabela Produto

Cadastro do produto monitorado. Colunas principais: Id, Nome, PrincipioAtivo, MarcaId,
EhReferencia (1 para produto de referência, 0 para genérico ou similar) e
ProdutoReferenciaId (preenchido só nos genéricos, aponta para o produto de referência).

## Tabela Farmacia

Cadastro das redes de farmácia monitoradas. Cada linha é uma rede (por exemplo, Drogasil ou
Araujo), e não uma loja física: o monitoramento coleta o site da rede, não o preço de balcão
de cada loja.

## Tabela ProdutoFarmacia

Liga um produto a uma farmácia, com o SKU que a farmácia usa no próprio site (SkuFarmacia) e
o código de barras observado na página (EanObservado). Um produto que não aparece nesta tabela
para uma farmácia não é monitorado naquela farmácia — a ausência não significa ruptura.

## Tabela PrecoColetado

Uma linha por coleta de um produto numa farmácia. Colunas: DataHoraColeta, PrecoTabela,
PrecoFarmacia, PrecoPbm (nulo quando não há programa ou quando o preço do programa não foi
visível na coleta), ProgramaPbmId e Disponivel (1 disponível para compra, 0 indisponível).

## Tabela ProgramaPBM

Cadastro dos programas de benefício dos laboratórios, com o fabricante responsável.

## View vw_PrecoAtual

Devolve, para cada produto em cada farmácia, a coleta mais recente, já com os nomes de
produto, farmácia, marca, fabricante e programa PBM. É a view usada para responder
"qual o preço atual". Ler a tabela PrecoColetado diretamente para essa pergunta é proibido,
porque a coleta mais recente pode ter falhado em uma farmácia e não em outra.

## View vw_Ruptura

Devolve, para cada produto em cada farmácia, o estado de disponibilidade atual e desde quando
ele dura (DesdeQuando), calculado pela transição de estado entre coletas e não pelo primeiro
zero encontrado no histórico. Colunas: Disponivel, DesdeQuando, UltimaColeta,
DiasNoEstadoAtual e QtdColetasNesseEstado. É a view usada para responder "desde quando um
produto está em falta".

## Convenção de datas

As datas de coleta são registradas no horário de Brasília. Uma coleta registrada às
00:00:00 representa a rodada de coleta daquele dia, e não o minuto exato da leitura da página.

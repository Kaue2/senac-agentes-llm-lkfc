---
id: programas-pbm
titulo: Programas de Benefício em Medicamentos (PBM)
tipo: glossario
versao: 1
vigente_desde: 2026-01-15
revogado_em:
dono: Inteligência Comercial
---

# Programas de Benefício em Medicamentos (PBM)

## O que é um PBM

Um Programa de Benefício em Medicamentos é um programa do laboratório fabricante que concede
desconto a pacientes cadastrados na compra de determinados medicamentos. O desconto é definido
pelo laboratório, varia de programa para programa e é reembolsado pelo laboratório à farmácia.

## Cadastro do paciente

Para comprar pelo preço do PBM, o paciente precisa estar cadastrado no programa, normalmente com
CPF e dados da receita. O agente de BI não acessa, não consulta e não guarda nenhum dado de
paciente do programa: ele trabalha só com o preço publicado.

## Adesão da farmácia

Cada rede de farmácia decide a quais programas adere. Por isso o mesmo produto pode ter PrecoPbm
numa farmácia e não ter em outra. A ausência de PrecoPbm numa farmácia não prova que o programa
não existe: pode ser que aquela rede não tenha aderido.

## Genéricos e PBM

Medicamentos genéricos normalmente não têm PBM, porque o desconto de PBM é uma estratégia de
laboratórios para produtos de referência. Um genérico sem PrecoPbm é o comportamento esperado,
e não falha de coleta.

## Farmácia Popular não é PBM

O programa Farmácia Popular é um programa do governo federal, e não um PBM de laboratório. Os
preços e as regras do Farmácia Popular não são coletados pelo monitoramento e não aparecem no
campo PrecoPbm.

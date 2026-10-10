"""`consultar_base_conhecimento` — o RAG do Exercício 7 como FERRAMENTA do agente.

Na Parte 1 o agente só sabia o que estava no prompt; as regras de negócio (tetos de desconto,
regra de ruptura confirmada, margem de concorrente) não estavam em lugar nenhum. Aqui a
recuperação vira ferramenta: o modelo decide QUANDO buscar (desafio A do Exercício 7), e a
ferramenta devolve trechos com identificador para o agente citar.

O portão da Aula 06 continua valendo dentro da ferramenta: se o trecho mais próximo está além do
limiar, a ferramenta devolve "não encontrado" com o assunto mais próximo — o agente recebe a
recusa como DADO e não tem trecho fraco em que se apoiar. Documento revogado nunca é devolvido
(filtro `somente_vigentes`, a curadoria decidida no Exercício 7, §6).
"""

from __future__ import annotations

from src.core.tools import Ferramenta, RegistroFerramentas
from src.rag.embeddings import ModeloEmbedding
from src.rag.indice import IndiceVetorial, somente_vigentes
from src.rag.resposta import K_PADRAO, LIMIAR_PADRAO


def _consultar_base(indice: IndiceVetorial, embeddings: ModeloEmbedding, pergunta: str) -> dict:
    vetor = embeddings.embed_consultas([pergunta])[0]
    resultados = indice.buscar(vetor, K_PADRAO, somente_vigentes)
    if not resultados or resultados[0].distancia > LIMIAR_PADRAO:
        mais_proximo = resultados[0].trecho if resultados else None
        return {
            "encontrado": False,
            "mensagem": (
                "A base de conhecimento não trata deste assunto. Não responda com regra inventada; diga ao "
                "gestor que a regra não está documentada e que ele deve procurar o time de Dados e BI."
            ),
            "assunto_mais_proximo": f"{mais_proximo.metadados.get('titulo')} — {mais_proximo.secao}" if mais_proximo else None,
        }
    return {
        "encontrado": True,
        "trechos": [
            {"id": r.trecho.id, "documento": r.trecho.metadados.get("titulo"), "texto": r.trecho.texto.split("\n\n", 1)[-1]}
            for r in resultados
        ],
        "instrucao": "Responda só com o que os trechos dizem e cite o id do trecho usado entre colchetes.",
    }


def registrar_ferramenta_conhecimento(
    registro: RegistroFerramentas, indice: IndiceVetorial, embeddings: ModeloEmbedding
) -> None:
    registro.registrar(
        Ferramenta(
            nome="consultar_base_conhecimento",
            descricao=(
                "Busca na base de conhecimento interna da rede: políticas de preço (tetos de desconto, margem "
                "mínima, exceções de controlados e PBM), regras de ruptura, definições de métricas (margem, "
                "PrecoPbm, desconto), sazonalidade, FEFO, como a coleta funciona e o que o agente pode ou não "
                "responder. Use para perguntas sobre REGRAS e DEFINIÇÕES. NÃO devolve preço, venda nem estoque "
                "de produto — para preço use consultar_precos. Argumento: a pergunta em português, completa."
            ),
            parametros_json_schema={
                "type": "object",
                "properties": {"pergunta": {"type": "string", "description": "A dúvida de regra ou definição, em português."}},
                "required": ["pergunta"],
            },
            handler=lambda pergunta: _consultar_base(indice, embeddings, pergunta),
            leitura_ou_escrita="leitura",
            reversivel=True,
            conversa_com="Índice vetorial do corpus dados/corpus/ (SQLite + numpy, e5-large)",
        )
    )

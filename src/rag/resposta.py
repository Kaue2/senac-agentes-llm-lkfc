"""O pipeline RAG do case: recuperar → portão → montar contexto → gerar → conferir citação.

Exercícios 6 (§4, RAG mínimo e portão) e 7 (citação verificável e recusa).

Decisões, com o número que as sustenta em exercicios/aula-06-buscador-do-regulamento.md:

- `K_PADRAO = 3`: com corte por estrutura e e5-large, recall@3 = recall@5 = 15/16; k=5 não
  recupera nada a mais e põe 67% mais texto na janela.
- `LIMIAR_PADRAO`: distância (1 - cosseno) acima da qual o trecho mais próximo é considerado
  longe demais para responder. Calibrado sobre as 20 perguntas (a regra de escolha está em
  `src/rag/avaliacao.py::escolher_limiar`); o valor e a folga medida estão no relatório.
- O portão decide ANTES da chamada ao modelo: uma pergunta barrada não gasta token, e a recusa
  é determinística e testável. A recusa informa o trecho mais próximo — "não sei" seco é pior
  que "a base não trata disto; o mais próximo foi X" (Aula 07, §3).
- A citação é conferida em código: o identificador citado precisa estar entre os recuperados.
  Citação fora do contexto é alucinação com aparência de rigor (Aula 07, §2).
"""

from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

from openai import BadRequestError, OpenAI

from src.core.prompts import PromptVersionado, carregar_prompt

from .embeddings import ModeloEmbedding
from .indice import IndiceVetorial, Resultado

K_PADRAO = 3
LIMIAR_PADRAO = 0.1685
TEMPERATURA = 0.0
MAX_TOKENS_RESPOSTA = 1500

_PADRAO_ID_TRECHO = re.compile(r"[a-z0-9-]+#[a-z]\d{2}(?:\.\d+)?")


@dataclass
class RespostaRAG:
    pergunta: str
    recuperados: list[Resultado]
    barrado_pelo_portao: bool
    resposta: str
    citacoes: list[str]
    citacoes_validas: list[str]
    citacoes_invalidas: list[str]
    recusou: bool
    trace: dict[str, Any] = field(default_factory=dict)

    @property
    def ids_recuperados(self) -> list[str]:
        return [r.trecho.id for r in self.recuperados]


def normalizar_citacao(citacao: str) -> str:
    """Tira os delimitadores: o contexto mostra o id como `[politica-precificacao-2026#s04]`, e o
    modelo copia com os colchetes (observado na 1ª execução do Exercício 7: 18 de 20 citações
    vieram assim e foram contadas como inválidas). O delimitador não é parte do id; o id em si
    continua comparado exatamente."""
    return citacao.strip().strip("[]").strip()


def verificar_citacoes(citacoes: list[str], ids_recuperados: list[str]) -> tuple[list[str], list[str]]:
    """Separa citações conferíveis (o id está entre os trechos entregues ao modelo) das que
    não estão. Comparação exata: um id "parecido" não é o mesmo trecho."""
    citacoes = [normalizar_citacao(c) for c in citacoes]
    recuperados = set(ids_recuperados)
    validas = [c for c in citacoes if c in recuperados]
    invalidas = [c for c in citacoes if c not in recuperados]
    return validas, invalidas


def ids_citados_no_texto(texto: str) -> list[str]:
    """Identificadores de trecho escritos no corpo da resposta (além da lista `citacoes`)."""
    return sorted(set(_PADRAO_ID_TRECHO.findall(texto)))


def montar_contexto(recuperados: list[Resultado], ordem: str = "relevancia") -> str:
    if ordem not in ("relevancia", "invertida"):
        raise ValueError(f"ordem inválida: {ordem!r}")
    sequencia = recuperados if ordem == "relevancia" else list(reversed(recuperados))
    return "\n\n".join(f"[{r.trecho.id}]\n{r.trecho.texto}" for r in sequencia)


def mensagem_de_recusa_do_portao(mais_proximo: Resultado, limiar: float) -> str:
    t = mais_proximo.trecho
    titulo = t.metadados.get("titulo", t.doc_id)
    secao = f" — {t.secao}" if t.secao else ""
    return (
        "A base de conhecimento não trata deste assunto. O trecho mais próximo que encontrei foi "
        f"«{titulo}{secao}» [{t.id}], a uma distância de {mais_proximo.distancia:.4f} "
        f"(o limite para responder é {limiar:.4f}). Se a pergunta é sobre esse tema, reformule; "
        "se não é, ela precisa ir para o time de Dados e BI."
    )


def interpretar_saida(conteudo: str) -> dict[str, Any]:
    """Lê o JSON do contrato de saída. Saída fora do contrato vira erro registrado — nunca
    resposta: um texto solto não tem citação conferível."""
    try:
        dados = json.loads(conteudo)
    except json.JSONDecodeError as exc:
        return {"erro_contrato": f"JSON inválido: {exc}"}
    if not isinstance(dados, dict):
        return {"erro_contrato": "a saída não é um objeto JSON"}
    faltando = [c for c in ("resposta", "citacoes", "recusou") if c not in dados]
    if faltando:
        return {"erro_contrato": f"chaves ausentes: {', '.join(faltando)}", **dados}
    if not isinstance(dados["citacoes"], list):
        return {"erro_contrato": "citacoes não é lista", **dados}
    return dados


class PipelineRAG:
    def __init__(
        self,
        indice: IndiceVetorial,
        embeddings: ModeloEmbedding,
        cliente: OpenAI | None,
        modelo_llm: str,
        k: int = K_PADRAO,
        limiar: float = LIMIAR_PADRAO,
        filtro: Callable[[dict], bool] | None = None,
        nome_filtro: str = "nenhum",
        prompt: PromptVersionado | None = None,
    ) -> None:
        self.indice = indice
        self.embeddings = embeddings
        self.cliente = cliente
        self.modelo_llm = modelo_llm
        self.k = k
        self.limiar = limiar
        self.filtro = filtro
        self.nome_filtro = nome_filtro
        self.prompt = prompt or carregar_prompt("resposta_rag_v1")

    def carimbo(self) -> dict[str, str]:
        return {
            "modelo_llm": self.modelo_llm,
            "temperatura": str(TEMPERATURA),
            "max_tokens": str(MAX_TOKENS_RESPOSTA),
            "prompt_resposta": self.prompt.rotulo,
            "modelo_embedding": self.indice.carimbo.get("modelo_embedding", "?"),
            "chunking": self.indice.carimbo.get("chunking", "?"),
            "metrica": self.indice.carimbo.get("metrica", "?"),
            "k": str(self.k),
            "limiar_portao": f"{self.limiar:.4f}",
            "filtro_corpus": self.nome_filtro,
        }

    def recuperar(self, pergunta: str, k: int | None = None) -> list[Resultado]:
        vetor = self.embeddings.embed_consultas([pergunta])[0]
        return self.indice.buscar(vetor, k or self.k, self.filtro)

    def responder(self, pergunta: str, portao: bool = True, ordem: str = "relevancia") -> RespostaRAG:
        recuperados = self.recuperar(pergunta)
        trace: dict[str, Any] = {
            "carimbo": {**self.carimbo(), "portao": "ligado" if portao else "desligado", "ordem_contexto": ordem},
            "recuperados": [
                {"posicao": r.posicao, "id": r.trecho.id, "distancia": round(r.distancia, 4)} for r in recuperados
            ],
        }

        if not recuperados or (portao and recuperados[0].distancia > self.limiar):
            texto = (
                mensagem_de_recusa_do_portao(recuperados[0], self.limiar)
                if recuperados
                else "A base de conhecimento não tem nenhum trecho para esta consulta."
            )
            trace["decisao"] = "barrado_pelo_portao"
            return RespostaRAG(pergunta, recuperados, True, texto, [], [], [], True, trace)

        return self.gerar(pergunta, recuperados, ordem, trace)

    def gerar(
        self, pergunta: str, recuperados: list[Resultado], ordem: str = "relevancia", trace: dict | None = None
    ) -> RespostaRAG:
        """Geração sobre uma lista de trechos dada, sem busca nem portão. Separada de
        `responder` para os experimentos do Exercício 7 que fixam o contexto (posição do trecho
        certo no meio de um contexto longo — modo de falha "recuperou e ignorou")."""
        trace = trace if trace is not None else {
            "carimbo": {**self.carimbo(), "portao": "não aplicado", "ordem_contexto": ordem},
            "recuperados": [
                {"posicao": i, "id": r.trecho.id, "distancia": round(r.distancia, 4)}
                for i, r in enumerate(recuperados, start=1)
            ],
        }
        if self.cliente is None:
            raise RuntimeError("Sem cliente de LLM configurado (preencha o .env).")

        mensagem = self.prompt.preencher(contexto=montar_contexto(recuperados, ordem), pergunta=pergunta)
        inicio = time.perf_counter()
        try:
            resposta = self.cliente.chat.completions.create(
                model=self.modelo_llm,
                messages=[{"role": "user", "content": mensagem}],
                temperature=TEMPERATURA,
                max_tokens=MAX_TOKENS_RESPOSTA,
                response_format={"type": "json_object"},
            )
        except BadRequestError as exc:
            # A Groq valida o JSON do lado dela e responde 400 (`json_validate_failed`) quando o
            # modelo gera JSON inválido. É falha do CONTRATO de saída, não de infraestrutura:
            # registra e segue, como qualquer saída fora do contrato.
            if "json_validate_failed" not in f"{exc} {getattr(exc, 'body', '')}":
                raise
            trace["latencia_s"] = round(time.perf_counter() - inicio, 3)
            trace["decisao"] = "erro_contrato"
            trace["erro_contrato"] = "o provedor rejeitou o JSON gerado (json_validate_failed)"
            return RespostaRAG(pergunta, recuperados, False, "", [], [], [], False, trace)
        escolha = resposta.choices[0]
        trace["latencia_s"] = round(time.perf_counter() - inicio, 3)
        trace["finish_reason"] = escolha.finish_reason
        trace["tokens"] = resposta.usage.total_tokens if resposta.usage else None
        trace["saida_bruta"] = escolha.message.content

        dados = interpretar_saida(escolha.message.content or "")
        if escolha.finish_reason == "length":
            dados = {"erro_contrato": "resposta cortada por max_tokens (finish_reason=length)"}
        if "erro_contrato" in dados:
            trace["decisao"] = "erro_contrato"
            trace["erro_contrato"] = dados["erro_contrato"]
            return RespostaRAG(pergunta, recuperados, False, "", [], [], [], False, trace)

        citacoes = [normalizar_citacao(str(c)) for c in dados["citacoes"]]
        citacoes += [c for c in ids_citados_no_texto(str(dados["resposta"])) if c not in citacoes]
        validas, invalidas = verificar_citacoes(citacoes, [r.trecho.id for r in recuperados])
        trace["decisao"] = "recusou" if dados["recusou"] else "respondeu"
        return RespostaRAG(
            pergunta=pergunta,
            recuperados=recuperados,
            barrado_pelo_portao=False,
            resposta=str(dados["resposta"]),
            citacoes=citacoes,
            citacoes_validas=validas,
            citacoes_invalidas=invalidas,
            recusou=bool(dados["recusou"]),
            trace=trace,
        )

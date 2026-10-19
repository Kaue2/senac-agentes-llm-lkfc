"""Os nós do grafo. Cada um diz, na primeira linha da docstring, se chama o MODELO ou só CÓDIGO.

Regras que valem para todos:

- um nó devolve só os campos que escreve (o LangGraph aplica a atualização com o reducer do campo);
- nenhum nó levanta exceção por erro de ferramenta: erro vira dado (`{"erro": ...}`) e o modelo
  decide o que fazer — erro RECUPERÁVEL. Erro do provedor do modelo depois das retentativas da
  biblioteca é FATAL e encerra o turno com `motivo_terminacao = "erro_fatal_modelo: ..."`;
- todo nó registra um evento (início/fim em epoch) em `eventos`: é com isso que a execução mede
  se os ramos paralelos se sobrepuseram de fato (§6.4, aviso sobre paralelismo).
"""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timedelta
from typing import Any

import openai
from langgraph.runtime import Runtime
from langgraph.types import interrupt
from pydantic import ValidationError

from src.memoria.contexto import contar_tokens, montar_contexto_memoria
from src.memoria.politica import extrair_preferencia_farmacia, extrair_recorte
from src.projects.farmacia_precos.tools_farmacia import chave_exportacao

from .contrato import MAX_CARACTERES_ENTRADA, AcaoExecutada, DecisaoHumana, Entrada, Fonte, SaidaAgente, Triagem
from .dependencias import Dependencias
from .estado import ZERAR, EstadoGrafo

TETO_TOKENS_CONVERSA = 800          # janela da conversa anterior enviada ao modelo (docs/memoria.md §5.5)
MAX_CARACTERES_RESULTADO = 2000     # retorno de ferramenta, por chamada, como o modelo o vê
_PADRAO_ID_TRECHO = re.compile(r"[a-z0-9-]+#[a-z]\d{2}(?:\.\d+)?")

CAPACIDADES = (
    "Eu respondo sobre preço atual, histórico de preço e falta (ruptura) de produtos nas 13 farmácias "
    "monitoradas, e sobre as regras e definições da rede (descontos, margem, PBM, ruptura, FEFO). "
    "Vendas e estoque ainda não têm dado. Não altero preço, não faço compra e não trato dado de paciente."
)
VIEW_POR_MODO = {"atual": "vw_PrecoAtual", "historico": "PrecoColetado", "ruptura": "vw_Ruptura"}


def _evento(no: str, inicio: float, **extra: Any) -> dict[str, Any]:
    fim = time.time()
    return {"no": no, "inicio": round(inicio, 4), "fim": round(fim, 4), "ms": round(1000 * (fim - inicio), 1), **extra}


def _texto(estado: EstadoGrafo) -> str:
    return estado["entrada"]["texto"]


def janela_da_conversa(mensagens: list[dict], teto_tokens: int = TETO_TOKENS_CONVERSA) -> list[dict]:
    """Política da janela (§5.5): truncar o INÍCIO. Anda do fim para o começo e para quando o próximo
    turno estouraria o teto — o mais recente nunca sai. O que se perde: o começo de uma conversa
    longa (a pergunta original de 10 turnos atrás). Retornos de ferramenta nunca entram aqui: a
    conversa guarda só o texto trocado, e os dados são reconsultados."""
    escolhidas: list[dict] = []
    total = 0
    for m in reversed(mensagens):
        custo = contar_tokens(m["texto"])
        if total + custo > teto_tokens:
            break
        escolhidas.append(m)
        total += custo
    return list(reversed(escolhidas))


# =============================================================================== entrada
def receber_entrada(estado: EstadoGrafo, runtime: Runtime[Dependencias]) -> dict:
    """CÓDIGO. Valida a entrada, zera os campos do turno e acrescenta a mensagem à conversa."""
    inicio = time.time()
    deps = runtime.context
    entrada = Entrada.model_validate(estado["entrada"])
    texto = entrada.texto.strip()
    motivo = None
    if not texto:
        motivo = "entrada_vazia"
    elif len(texto) > MAX_CARACTERES_ENTRADA:
        motivo = "entrada_longa"
    turno = estado.get("turno", 0) + 1
    return {
        "entrada": {**entrada.model_dump(), "texto": texto[:MAX_CARACTERES_ENTRADA]},
        "turno": turno,
        "inicio_turno": deps.agora().isoformat(),
        "mensagens": [{"papel": "usuario", "texto": texto[:MAX_CARACTERES_ENTRADA], "turno": turno}],
        "eventos": [ZERAR, _evento("receber_entrada", inicio)],
        "trajetoria": [ZERAR],
        "mensagens_modelo": [ZERAR],
        "efeitos_aplicados": [ZERAR],
        "contexto_memoria": "",
        "memoria_usada": {},
        "triagem": None,
        "chamadas_pendentes": [],
        "passos": 0,
        "tokens": 0,
        "acao_pendente": None,
        "aprovacao": None,
        "decisao_humana": None,
        "resposta_texto": None,
        "motivo_terminacao": motivo,
        "saida": None,
        "gravacoes_memoria": [],
    }


# ====================================================================== ramos paralelos
def carregar_memoria(estado: EstadoGrafo, runtime: Runtime[Dependencias]) -> dict:
    """CÓDIGO (+ embedding local). Lê a memória de longo prazo: procedural inteira, semântica por
    chave, episódica por similaridade filtrada pelo gestor (src/memoria/contexto.py)."""
    inicio = time.time()
    deps = runtime.context
    if deps.memoria is None:
        usada = {"ativa": False}
        texto = ""
    else:
        ctx = montar_contexto_memoria(deps.memoria, estado["entrada"]["usuario_id"], _texto(estado))
        texto = ctx.texto
        usada = {
            "ativa": True, "tokens": ctx.tokens, "fatos": ctx.fatos, "episodios": ctx.episodios,
            "descartados_por_teto": ctx.descartados_por_teto, "descartes_por_contradicao": ctx.descartes_por_contradicao,
        }
    return {
        "contexto_memoria": texto,
        "memoria_usada": usada,
        "eventos": [_evento("carregar_memoria", inicio)],
        "trajetoria": [{"no": "carregar_memoria", "tipo": "memoria", **usada}],
    }


def _chamar_triagem(deps: Dependencias, mensagens: list[dict]) -> tuple[Triagem, int]:
    resposta = deps.cliente.chat.completions.create(
        model=deps.modelo, messages=mensagens, response_format={"type": "json_object"}, temperature=0,
    )
    tokens = resposta.usage.total_tokens if resposta.usage else 0
    return Triagem.model_validate_json(resposta.choices[0].message.content or ""), tokens


def triagem(estado: EstadoGrafo, runtime: Runtime[Dependencias]) -> dict:
    """MODELO (saída estruturada). Decide a rota: atender, esclarecer ou fora do escopo."""
    inicio = time.time()
    deps = runtime.context
    anteriores = janela_da_conversa(estado.get("mensagens", [])[:-1])
    conversa = "\n".join(f"{'gestor' if m['papel'] == 'usuario' else 'agente'}: {m['texto']}" for m in anteriores)
    mensagens = [
        {"role": "system", "content": deps.prompt_triagem.texto},
        {"role": "user", "content": f"Conversa anterior:\n{conversa or '(nenhuma)'}\n\nMensagem atual do gestor:\n{_texto(estado)}"},
    ]
    tokens = 0
    erros: list[str] = []
    resultado: Triagem | None = None
    for _ in range(2):  # uma retentativa: JSON inválido é erro recuperável
        try:
            resultado, t = _chamar_triagem(deps, mensagens)
            tokens += t
            break
        except (ValidationError, json.JSONDecodeError, openai.BadRequestError) as exc:
            erros.append(f"{type(exc).__name__}: {str(exc)[:200]}")
        except openai.APIError as exc:
            erros.append(f"{type(exc).__name__}: {str(exc)[:200]}")
            break
    if resultado is None:
        # Falha ABERTA, declarada: sem triagem, o laço do agente ainda tem as regras do prompt e o
        # portão do RAG; recusar tudo porque a triagem caiu seria pior para o gestor.
        resultado = Triagem(
            rota="atender", pilar="misto", pergunta_reescrita=_texto(estado),
            justificativa="triagem indisponível; seguiu para o agente sem interpretação", suposicoes=[],
        )
    triagem_dict = resultado.model_dump()
    triagem_dict["erros"] = erros
    return {
        "triagem": triagem_dict,
        "tokens": tokens,
        "eventos": [_evento("triagem", inicio)],
        "trajetoria": [{"no": "triagem", "tipo": "triagem", "rota": resultado.rota, "pilar": resultado.pilar,
                        "suposicoes": resultado.suposicoes, "faltando": resultado.faltando, "erros": erros, "tokens": tokens}],
    }


def portao(estado: EstadoGrafo, runtime: Runtime[Dependencias]) -> dict:
    """CÓDIGO. Junção dos dois ramos paralelos; a decisão de rota está em `rotas.rota_triagem`."""
    return {"eventos": [_evento("portao", time.time())]}


# =========================================================== saídas sem o laço do agente
def esclarecer(estado: EstadoGrafo, runtime: Runtime[Dependencias]) -> dict:
    """CÓDIGO. Devolve a pergunta de esclarecimento que a triagem formulou."""
    t = estado["triagem"]
    pergunta = t.get("pergunta_esclarecimento") or f"Para responder, preciso saber: {', '.join(t.get('faltando') or ['o recorte'])}."
    return {"resposta_texto": pergunta, "motivo_terminacao": "esclarecimento_pedido",
            "eventos": [_evento("esclarecer", time.time())]}


def recusar(estado: EstadoGrafo, runtime: Runtime[Dependencias]) -> dict:
    """CÓDIGO. Recusa dizendo o que o sistema faz (fora do escopo) ou o que falta (recorte)."""
    t = estado["triagem"]
    if t["rota"] == "fora_escopo":
        motivo_recusa = (t.get("justificativa") or "está fora do escopo").strip().rstrip(".")
        texto = f"Não posso atender a esse pedido: {motivo_recusa[:1].lower() + motivo_recusa[1:]}. {CAPACIDADES}"
        motivo = "fora_do_escopo"
    else:
        faltando = ", ".join(t.get("faltando") or ["o recorte da pergunta"])
        texto = (
            f"Ainda falta {faltando} para eu responder com confiança, mesmo depois da pergunta de esclarecimento. "
            "Reformule a pergunta com esse dado, ou procure o time de Dados e BI."
        )
        motivo = "recorte_insuficiente"
    return {"resposta_texto": texto, "motivo_terminacao": motivo, "eventos": [_evento("recusar", time.time())]}


# ====================================================================== laço do agente
def tetos_excedidos(estado: EstadoGrafo, deps: Dependencias) -> str | None:
    t = deps.tetos
    if estado.get("passos", 0) >= t.max_passos:
        return f"orcamento_excedido_passos ({estado.get('passos', 0)}/{t.max_passos})"
    if estado.get("tokens", 0) >= t.max_tokens:
        return f"orcamento_excedido_tokens ({estado.get('tokens', 0)}/{t.max_tokens})"
    decorrido = (deps.agora() - datetime.fromisoformat(estado["inicio_turno"])).total_seconds()
    if decorrido >= t.max_segundos:
        return f"orcamento_excedido_tempo ({decorrido:.0f}s/{t.max_segundos:g}s)"
    return None


def _assinatura(nome: str, argumentos: dict) -> str:
    return f"{nome}:{json.dumps(argumentos, sort_keys=True, ensure_ascii=False)}"


def detectar_laco(estado: EstadoGrafo, chamadas: list[dict], limite: int) -> str | None:
    """`recursion_limit` limita o dano e não detecta: um agente que repete a mesma consulta gasta o
    teto inteiro e termina como "limite de recursão", o diagnóstico errado. Aqui: a mesma ferramenta
    com os mesmos argumentos já chamada `limite` vezes neste turno → laço."""
    anteriores = [_assinatura(p["ferramenta"], p.get("argumentos", {}))
                  for p in estado.get("trajetoria", []) if p.get("tipo") == "chamada_ferramenta"]
    for c in chamadas:
        assinatura = _assinatura(c["nome"], c["argumentos"])
        if anteriores.count(assinatura) >= limite:
            return f"laco_detectado ({c['nome']} repetida {anteriores.count(assinatura) + 1}x com os mesmos argumentos)"
    return None


def montar_mensagens_agente(estado: EstadoGrafo, deps: Dependencias) -> list[dict]:
    mensagens: list[dict] = [{"role": "system", "content": deps.prompt_agente.texto}]
    if estado.get("contexto_memoria"):
        mensagens.append({"role": "system", "content": estado["contexto_memoria"]})
    t = estado.get("triagem") or {}
    if t:
        linhas = [f"Interpretação da triagem: {t.get('pergunta_reescrita')}"]
        if t.get("suposicoes"):
            linhas.append("Suposições a declarar na resposta: " + "; ".join(t["suposicoes"]))
        mensagens.append({"role": "system", "content": "\n".join(linhas)})
    for m in janela_da_conversa(estado.get("mensagens", [])[:-1]):
        mensagens.append({"role": "user" if m["papel"] == "usuario" else "assistant", "content": m["texto"]})
    mensagens.append({"role": "user", "content": _texto(estado)})
    mensagens.extend(estado.get("mensagens_modelo", []))
    return mensagens


def _chamar_modelo(deps: Dependencias, mensagens: list[dict]):
    """Erro recuperável × fatal: 429, 5xx e timeout já são retentados pela biblioteca openai
    (`max_retries=6`, src/core/llm_client.py). `BadRequestError` (o provedor rejeita uma chamada de
    ferramenta malformada gerada pelo modelo — `tool_use_failed` na Groq) é recuperável UMA vez.
    O resto que chega aqui é fatal."""
    try:
        return deps.cliente.chat.completions.create(model=deps.modelo, messages=mensagens, tools=deps.ferramentas.schemas_para_modelo())
    except openai.BadRequestError:
        return deps.cliente.chat.completions.create(model=deps.modelo, messages=mensagens, tools=deps.ferramentas.schemas_para_modelo())


def agente(estado: EstadoGrafo, runtime: Runtime[Dependencias]) -> dict:
    """MODELO (com ferramentas). Escolhe a próxima ferramenta ou escreve a resposta final."""
    inicio = time.time()
    deps = runtime.context
    motivo = tetos_excedidos(estado, deps)
    if motivo:
        return {"motivo_terminacao": motivo, "eventos": [_evento("agente", inicio, sem_chamada=True)]}
    try:
        resposta = _chamar_modelo(deps, montar_mensagens_agente(estado, deps))
    except openai.APIError as exc:
        return {"motivo_terminacao": f"erro_fatal_modelo: {type(exc).__name__}: {str(exc)[:200]}",
                "eventos": [_evento("agente", inicio)]}
    passos = estado.get("passos", 0) + 1
    tokens = estado.get("tokens", 0) + (resposta.usage.total_tokens if resposta.usage else 0)
    mensagem = resposta.choices[0].message
    chamadas_brutas = mensagem.tool_calls or []

    if not chamadas_brutas:
        texto = (mensagem.content or "").strip()
        return {
            "passos": passos, "tokens": tokens,
            "resposta_texto": texto or None,
            "motivo_terminacao": "resposta_final" if texto else "resposta_vazia",
            "eventos": [_evento("agente", inicio, passo=passos)],
            "trajetoria": [{"no": "agente", "passo": passos, "tipo": "resposta_final", "conteudo": texto}],
        }

    chamadas = []
    for c in chamadas_brutas:
        try:
            argumentos = json.loads(c.function.arguments or "{}")
            erro = None
        except json.JSONDecodeError as exc:
            argumentos, erro = {}, f"argumentos inválidos do modelo: {exc}"
        chamadas.append({"id": c.id, "nome": c.function.name, "argumentos": argumentos, "erro_argumentos": erro})

    laco = detectar_laco(estado, chamadas, deps.tetos.limite_repeticao)
    if laco:
        return {"passos": passos, "tokens": tokens, "motivo_terminacao": laco,
                "eventos": [_evento("agente", inicio, passo=passos)]}

    msg_assistente = {
        "role": "assistant", "content": mensagem.content or "",
        "tool_calls": [{"id": c.id, "type": "function", "function": {"name": c.function.name, "arguments": c.function.arguments or "{}"}}
                       for c in chamadas_brutas],
    }
    return {
        "passos": passos, "tokens": tokens,
        "mensagens_modelo": [msg_assistente],
        "chamadas_pendentes": chamadas,
        "eventos": [_evento("agente", inicio, passo=passos)],
    }


def _mensagem_ferramenta(tool_call_id: str, resultado: dict) -> dict:
    conteudo = json.dumps(resultado, ensure_ascii=False, default=str)
    if len(conteudo) > MAX_CARACTERES_RESULTADO:
        conteudo = conteudo[:MAX_CARACTERES_RESULTADO] + "…(truncado)"
    return {"role": "tool", "tool_call_id": tool_call_id, "content": conteudo}


def ferramentas(estado: EstadoGrafo, runtime: Runtime[Dependencias]) -> dict:
    """CÓDIGO. Executa as ferramentas de LEITURA pedidas pelo modelo. A de escrita
    (`exportar_analise`) não roda aqui: vira `acao_pendente` e vai para o ponto de parada humano."""
    inicio = time.time()
    deps = runtime.context
    mensagens: list[dict] = []
    trajetoria: list[dict] = []
    acao: dict | None = None
    for c in estado.get("chamadas_pendentes", []):
        if c["nome"] == "exportar_analise" and not c["erro_argumentos"]:
            if acao is None:
                acao = {"tool_call_id": c["id"], "ferramenta": c["nome"], "argumentos": c["argumentos"]}
            else:
                mensagens.append(_mensagem_ferramenta(c["id"], {"erro": "uma exportação por vez; aguarde a aprovação da primeira"}))
            continue
        if c["erro_argumentos"]:
            resultado = {"erro": c["erro_argumentos"]}
        else:
            resultado = deps.ferramentas.chamar(c["nome"], c["argumentos"])
        mensagens.append(_mensagem_ferramenta(c["id"], resultado))
        trajetoria.append({"no": "ferramentas", "passo": estado.get("passos", 0), "tipo": "chamada_ferramenta",
                           "ferramenta": c["nome"], "argumentos": c["argumentos"], "resultado": resultado,
                           "erro_recuperavel": "erro" in resultado})
    return {
        "mensagens_modelo": mensagens,
        "trajetoria": trajetoria,
        "chamadas_pendentes": [],
        "acao_pendente": acao,
        "eventos": [_evento("ferramentas", inicio)],
    }


# ================================================================ ponto de parada humano
def preparar_aprovacao(estado: EstadoGrafo, runtime: Runtime[Dependencias]) -> dict:
    """CÓDIGO. Grava no estado o pedido de aprovação, COM o prazo, antes da pausa. O prazo não pode
    ser calculado no nó que pausa: na retomada aquele nó roda de novo desde o começo, e o prazo seria
    recalculado a partir da hora da resposta — nunca venceria."""
    deps = runtime.context
    acao = estado["acao_pendente"]
    args = acao["argumentos"]
    chave = chave_exportacao(args.get("pergunta", ""), args.get("dados_resumo", ""), args.get("explicacao", ""))
    agora = deps.agora()
    aprovacao = {
        "acao": acao["ferramenta"],
        "argumentos": args,
        "chave_idempotencia": chave,
        "consequencia": (
            f"Cria o arquivo dados/exports/analise_{chave}.md com a pergunta, os dados e a explicação acima. "
            "Não altera preço, venda nem estoque. Para desfazer, apague o arquivo. Se o mesmo conteúdo já "
            "tiver sido exportado, nada novo é criado."
        ),
        "perfil_revisor": "Administração (o usuário principal do case) ou o próprio gestor que pediu",
        "respostas_aceitas": {
            "aprovar": {"decisao": "aprovar"},
            "rejeitar": {"decisao": "rejeitar", "comentario": "motivo"},
            "editar": {"decisao": "editar", "argumentos": {"dados_resumo": "...", "explicacao": "..."}},
        },
        "criado_em": agora.isoformat(),
        "prazo_expira_em": (agora + timedelta(hours=deps.tetos.prazo_aprovacao_horas)).isoformat(),
        "se_ninguem_responder": "a execução expira: nada é exportado e o turno termina com motivo 'aprovacao_expirada'",
        "tool_call_id": acao["tool_call_id"],
        "thread_id": f"{estado['entrada']['usuario_id']}:{estado['entrada']['sessao_id']}",
    }
    return {"aprovacao": aprovacao, "eventos": [_evento("preparar_aprovacao", time.time())]}


CAMPOS_EDITAVEIS = ("pergunta", "dados_resumo", "explicacao")


def aguardar_humano(estado: EstadoGrafo, runtime: Runtime[Dependencias]) -> dict:
    """CÓDIGO + PAUSA (`interrupt`). Nada com efeito colateral antes do `interrupt`: na retomada
    este nó roda de novo desde a primeira linha."""
    deps = runtime.context
    aprovacao = estado["aprovacao"]
    bruto = interrupt(aprovacao)
    try:
        decisao = DecisaoHumana.model_validate(bruto if isinstance(bruto, dict) else {"decisao": bruto})
    except ValidationError as exc:
        return {"decisao_humana": {"decisao": "invalida", "erro": str(exc)[:300], "recebido": str(bruto)[:200]},
                "eventos": [_evento("aguardar_humano", time.time(), invalida=True)]}

    registro = decisao.model_dump()
    registro["recebida_em"] = deps.agora().isoformat()
    if deps.agora() > datetime.fromisoformat(aprovacao["prazo_expira_em"]) and decisao.decisao != "expirou":
        registro["decisao_original"] = decisao.decisao
        registro["decisao"] = "expirou"

    atualizacao: dict[str, Any] = {"decisao_humana": registro, "eventos": [_evento("aguardar_humano", time.time())]}
    if registro["decisao"] == "rejeitar":
        resultado = {"status": "rejeitado_pelo_revisor", "comentario": decisao.comentario, "nada_foi_gravado": True}
        atualizacao["mensagens_modelo"] = [_mensagem_ferramenta(aprovacao["tool_call_id"], resultado)]
        atualizacao["trajetoria"] = [{"no": "aguardar_humano", "tipo": "chamada_ferramenta", "ferramenta": "exportar_analise",
                                      "argumentos": aprovacao["argumentos"], "resultado": resultado, "decisao": registro}]
        atualizacao["acao_pendente"] = None
    elif registro["decisao"] == "expirou":
        atualizacao["motivo_terminacao"] = "aprovacao_expirada"
        atualizacao["resposta_texto"] = (
            "A exportação pedida não foi aprovada dentro do prazo e não foi feita. "
            f"Prazo: {aprovacao['prazo_expira_em']}. Peça de novo se ainda precisar."
        )
        atualizacao["acao_pendente"] = None
    return atualizacao


def exportar(estado: EstadoGrafo, runtime: Runtime[Dependencias]) -> dict:
    """CÓDIGO (ESCRITA). Executa a exportação aprovada, com os argumentos editados se houver. A
    ferramenta é idempotente pelo conteúdo: a mesma aprovação entregue duas vezes não cria nada novo."""
    inicio = time.time()
    deps = runtime.context
    aprovacao = estado["aprovacao"]
    decisao = estado["decisao_humana"]
    args = dict(aprovacao["argumentos"])
    if decisao["decisao"] == "editar" and decisao.get("argumentos"):
        args.update({k: v for k, v in decisao["argumentos"].items() if k in CAMPOS_EDITAVEIS})
    resultado = deps.ferramentas.chamar("exportar_analise", args)
    efeito = {
        "acao": "exportar_analise", "argumentos": args,
        "chave_idempotencia": resultado.get("chave_idempotencia", ""), "ja_existia": bool(resultado.get("ja_existia")),
        "resultado": resultado, "decisao": decisao["decisao"], "revisor": decisao.get("revisor"),
    }
    return {
        "mensagens_modelo": [_mensagem_ferramenta(aprovacao["tool_call_id"], resultado)],
        "trajetoria": [{"no": "exportar", "tipo": "chamada_ferramenta", "ferramenta": "exportar_analise",
                        "argumentos": args, "resultado": resultado, "decisao": decisao}],
        "efeitos_aplicados": [efeito],
        "acao_pendente": None,
        "eventos": [_evento("exportar", inicio)],
    }


# ============================================================================== término
def extrair_fontes(trajetoria: list[dict], resposta: str) -> tuple[list[Fonte], list[str], list[str]]:
    """Fontes conferíveis a partir da trajetória, em CÓDIGO. Devolve (fontes, alertas, motivos de
    falta de base) — os motivos alimentam `motivo_insuficiencia`."""
    fontes: list[Fonte] = []
    alertas: list[str] = []
    sem_base: list[str] = []
    citados = {c.strip("[]") for c in _PADRAO_ID_TRECHO.findall(resposta or "")}
    recuperados: dict[str, str] = {}
    for p in trajetoria:
        if p.get("tipo") != "chamada_ferramenta":
            continue
        nome, args, res = p["ferramenta"], p.get("argumentos", {}), p.get("resultado", {})
        if "erro" in res:
            alertas.append(f"{nome}: {res['erro']}")
            continue
        if nome == "consultar_precos":
            modo = args.get("modo", "atual")
            ref = f"{VIEW_POR_MODO.get(modo, modo)}(produto='{args.get('produto')}'" + (f", farmacia='{args['farmacia']}')" if args.get("farmacia") else ")")
            if res.get("encontrado"):
                linhas = res.get("resultados", [])
                datas = sorted({str(l.get("DataUltimaColeta") or l.get("DataHoraColeta") or l.get("UltimaColeta") or "") for l in linhas} - {""})
                fontes.append(Fonte(tipo="banco_precos", referencia=ref,
                                    detalhe=f"{len(linhas)} linha(s), fonte={res.get('fonte')}, coleta mais recente {datas[-1] if datas else '?'}"))
            else:
                sem_base.append(f"nenhum registro em {ref}")
        elif nome == "consultar_base_conhecimento":
            if res.get("encontrado"):
                for t in res.get("trechos", []):
                    recuperados[t["id"]] = t.get("documento", "")
            else:
                sem_base.append(f"a base de conhecimento não trata do assunto (mais próximo: {res.get('assunto_mais_proximo')})")
        elif nome in ("consultar_vendas", "consultar_estoque"):
            fontes.append(Fonte(tipo="ferramenta", referencia=nome, detalhe=res.get("status", "")))
            sem_base.append(f"{nome}: pilar sem dado (não implementado)")
    for cid in sorted(citados):
        if cid in recuperados:
            fontes.append(Fonte(tipo="corpus", referencia=cid, detalhe=recuperados[cid]))
        else:
            alertas.append(f"citação [{cid}] não está entre os trechos recuperados")
    if recuperados and not (citados & set(recuperados)):
        alertas.append("a resposta usou a base de conhecimento sem citar trecho")
    return fontes, alertas, sem_base


def montar_saida(estado: EstadoGrafo, runtime: Runtime[Dependencias]) -> dict:
    """CÓDIGO. Monta e VALIDA o objeto de saída (contrato §1.2). A suficiência é regra em código."""
    inicio = time.time()
    motivo = estado.get("motivo_terminacao") or "desconhecido"
    resposta = estado.get("resposta_texto")
    t = estado.get("triagem") or {}
    fontes, alertas, sem_base = extrair_fontes(estado.get("trajetoria", []), resposta or "")
    alertas += [f"triagem: {e}" for e in t.get("erros", [])]
    tem_base = any(f.tipo in ("banco_precos", "corpus") for f in fontes)

    pergunta_esclarecimento = None
    motivo_insuf = None
    if motivo == "esclarecimento_pedido":
        suficiencia = "aguardando_esclarecimento"
        pergunta_esclarecimento = resposta
        motivo_insuf = "falta: " + ", ".join(t.get("faltando") or ["recorte"])
    elif motivo == "resposta_final" and tem_base:
        suficiencia = "suficiente"
    elif motivo == "resposta_final" and not fontes and (resposta or "").rstrip().endswith("?"):
        # O agente perguntou de volta por conta própria (o prompt v3 proíbe; acontece). Regra em código.
        suficiencia = "aguardando_esclarecimento"
        pergunta_esclarecimento = resposta
        motivo_insuf = "o agente pediu esclarecimento"
    else:
        suficiencia = "insuficiente"
        if motivo == "resposta_final":
            motivo_insuf = "; ".join(sem_base) or "o agente respondeu sem consultar nenhuma fonte"
        else:
            motivo_insuf = motivo

    if resposta is None:
        resposta = {
            "entrada_vazia": "Não recebi nenhuma pergunta. " + CAPACIDADES,
            "entrada_longa": f"A pergunta passou de {MAX_CARACTERES_ENTRADA} caracteres; divida em perguntas menores.",
        }.get(motivo, f"Não consegui concluir a resposta (motivo: {motivo}). Tente reformular ou procure o time de Dados e BI.")

    saida = SaidaAgente(
        resultado=resposta,
        fontes=fontes,
        suficiencia=suficiencia,
        motivo_insuficiencia=motivo_insuf if suficiencia != "suficiente" else None,
        suposicoes=t.get("suposicoes", []) if t.get("rota") == "atender" else [],
        pergunta_esclarecimento=pergunta_esclarecimento,
        acoes_executadas=[AcaoExecutada(**{k: e[k] for k in ("acao", "argumentos", "chave_idempotencia", "ja_existia", "resultado")})
                          for e in estado.get("efeitos_aplicados", [])],
        alertas=alertas,
        motivo_terminacao=motivo,
        thread_id=f"{estado['entrada']['usuario_id']}:{estado['entrada']['sessao_id']}",
        turno=estado.get("turno", 1),
    )
    esclarecimentos = estado.get("esclarecimentos_feitos", 0) + 1 if suficiencia == "aguardando_esclarecimento" else 0
    return {
        "saida": saida.model_dump(),
        "resposta_texto": resposta,
        "esclarecimentos_feitos": esclarecimentos,
        "mensagens": [{"papel": "agente", "texto": resposta, "turno": estado.get("turno", 1)}],
        "eventos": [_evento("montar_saida", inicio)],
    }


def gravar_memoria(estado: EstadoGrafo, runtime: Runtime[Dependencias]) -> dict:
    """CÓDIGO. Escreve na memória de longo prazo pela política de src/memoria/politica.py: o código
    extrai por regra; o agente nunca decide o que guardar. Toda gravação tem chave derivada do
    conteúdo e devolve `ja_existia`."""
    inicio = time.time()
    deps = runtime.context
    gravacoes: list[dict] = []
    motivo = estado.get("motivo_terminacao")
    rota = (estado.get("triagem") or {}).get("rota")
    if deps.memoria is None:
        gravacoes.append({"pulado": "memória desligada"})
    elif rota == "fora_escopo" or motivo != "resposta_final":
        # Pendência do Exercício 8 fechada aqui: execução recusada (ex.: dado de paciente) não vira
        # episódio — o nome do paciente não tem padrão para o mascaramento pegar.
        gravacoes.append({"pulado": f"turno terminou por '{motivo}' (rota {rota}): nada a lembrar"})
    else:
        usuario = estado["entrada"]["usuario_id"]
        hoje = deps.agora().date().isoformat()
        recorte = extrair_recorte(estado.get("trajetoria", []), motivo)
        if recorte.ferramentas:
            g = deps.memoria.gravar_episodio(usuario, hoje, _texto(estado), recorte)
            gravacoes.append({"tipo": "episodica", "id": g.id, "ja_existia": g.ja_existia})
        preferencia = extrair_preferencia_farmacia(_texto(estado))
        if preferencia:
            g = deps.memoria.gravar_fato(f"usuario:{usuario}:farmacia_padrao", preferencia, hoje,
                                         f"thread:{usuario}:{estado['entrada']['sessao_id']}:turno{estado.get('turno')}")
            gravacoes.append({"tipo": "semantica", "id": g.id, "ja_existia": g.ja_existia})
    return {"gravacoes_memoria": gravacoes, "eventos": [_evento("gravar_memoria", inicio)]}

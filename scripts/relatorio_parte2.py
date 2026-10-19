"""Gera docs/io.md e as tabelas de medição de docs/grafo.md e docs/rag.md a partir dos logs de
logs/parte2/ — os exemplos da documentação são COPIADOS de execuções, não escritos à mão (§1.3).

Cada "o que ler ali" vem com uma checagem: se a saída do log não tiver o que a frase afirma, o
exemplo sai marcado com AVISO em vez de afirmar algo falso.

Uso: python scripts/relatorio_parte2.py   (depois de scripts/run_casos_parte2.py)
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

RAIZ = Path(__file__).resolve().parents[1]
LOGS = RAIZ / "logs" / "parte2"
DOCS = RAIZ / "docs"


def carregar(nome: str) -> dict:
    return json.loads((LOGS / nome).read_text(encoding="utf-8"))


def ferramentas(log: dict) -> list[str]:
    return [p["ferramenta"] for p in log["trajetoria"] if p.get("tipo") == "chamada_ferramenta"]


def preco_farmacia(log: dict) -> str:
    """O PrecoFarmacia que a ferramenta devolveu, no formato brasileiro (para conferir com o texto)."""
    for p in log["trajetoria"]:
        if p.get("ferramenta") == "consultar_precos" and p["resultado"].get("encontrado"):
            return f"{p['resultado']['resultados'][0]['PrecoFarmacia']:.2f}".replace(".", ",")
    return "?"


def bloco_exemplo(titulo: str, nome_log: str, leitura: str, checagens: list[tuple[str, bool]]) -> str:
    log = carregar(nome_log)
    c = log["carimbo"]
    falhas = [desc for desc, ok in checagens if not ok]
    pedido = log["pedido"]
    entrada = pedido["texto"] if isinstance(pedido, dict) and "texto" in pedido else json.dumps(pedido, ensure_ascii=False)
    aviso = f"\n> **AVISO — a execução não mostrou:** {'; '.join(falhas)}.\n" if falhas else ""
    return f"""
### {titulo}

Execução: commit `{c['commit']}`, {c['data_utc']} · modelo `{c['modelo']}` · prompts `{c['prompt_triagem']}`, `{c['prompt_agente']}` · log [`logs/parte2/{nome_log}`](../logs/parte2/{nome_log})

**Entrada exata** (usuário `{log['thread_id'].split(':')[0]}`, sessão `{log['thread_id'].split(':')[1]}`):

```
{entrada}
```

**Saída completa:**

```json
{json.dumps(log['saida'], ensure_ascii=False, indent=2)}
```

**O que ler ali:** {leitura}
{aviso}"""


def gerar_io() -> str:
    c01, c05 = carregar("caso-01-simples-t1.json"), carregar("caso-05-fora-do-corpus-t1.json")
    i1a, i1b = carregar("io-01-incompleta-t1.json"), carregar("io-01-incompleta-t2.json")
    i2, i3 = carregar("io-02-ambigua-t1.json"), carregar("io-03-fora-do-escopo-t1.json")
    s = lambda log: log["saida"]  # noqa: E731

    exemplos = [
        bloco_exemplo(
            "3.1 O caminho feliz", "caso-01-simples-t1.json",
            "`suficiencia: suficiente` porque há uma fonte do tipo `banco_precos` — a referência diz a view e o filtro "
            "(`vw_PrecoAtual`, produto e farmácia) e o detalhe diz a data da coleta. O `PrecoFarmacia` que está no "
            f"`resultado` (R$ {preco_farmacia(c01)}) é o da linha que a ferramenta devolveu, conferível no log; cada "
            "campo de preço vem nomeado, e o PBM ausente é dito, e não preenchido.",
            [("suficiência suficiente", s(c01)["suficiencia"] == "suficiente"),
             ("fonte banco_precos", any(f["tipo"] == "banco_precos" for f in s(c01)["fontes"])),
             ("o PrecoFarmacia da ferramenta no texto", preco_farmacia(c01) in s(c01)["resultado"])]),
        bloco_exemplo(
            "3.2 A recusa (pergunta fora do corpus)", "caso-05-fora-do-corpus-t1.json",
            "`suficiencia: insuficiente` com `fontes: []` — o modelo decidiu buscar (`consultar_base_conhecimento`), o "
            "portão do RAG barrou (trecho mais próximo além do limiar) e o `motivo_insuficiencia` diz qual foi o "
            "assunto mais próximo. No lugar da resposta, o sistema diz que a regra não está documentada e para "
            "onde ir. Nenhuma política de troca foi inventada.",
            [("suficiência insuficiente", s(c05)["suficiencia"] == "insuficiente"),
             ("consultou a base", "consultar_base_conhecimento" in ferramentas(c05)),
             ("sem fontes", s(c05)["fontes"] == [])]),
        bloco_exemplo(
            "3.3 Entrada incompleta — turno 1: pergunta o que falta", "io-01-incompleta-t1.json",
            "`suficiencia: aguardando_esclarecimento` e `pergunta_esclarecimento` preenchida; `motivo_terminacao: "
            "esclarecimento_pedido`. A triagem viu que falta o produto (o único recorte sem o qual não há consulta) e "
            "o laço do agente **não rodou** — nenhuma ferramenta, nenhum número.",
            [("aguardando esclarecimento", s(i1a)["suficiencia"] == "aguardando_esclarecimento"),
             ("sem ferramentas", ferramentas(i1a) == [])]),
        bloco_exemplo(
            "3.3 Entrada incompleta — turno 2: com a resposta, atende", "io-01-incompleta-t2.json",
            "mesma `thread_id` do turno 1, `turno: 2`. \"a trayenta 5mg\" sozinho não diz a farmácia: ela veio da "
            "conversa guardada no checkpoint, e a fonte mostra a consulta com o produto **e** a farmácia do turno 1.",
            [("turno 2", s(i1b)["turno"] == 2),
             ("suficiente", s(i1b)["suficiencia"] == "suficiente"),
             ("farmácia do turno 1 na fonte", any("drogasil" in f["referencia"].lower() for f in s(i1b)["fontes"]))]),
        bloco_exemplo(
            "3.4 Entrada ambígua — escolhe e declara a escolha", "io-02-ambigua-t1.json",
            "\"quanto custa\" tem três respostas no domínio (PrecoTabela, PrecoFarmacia, PrecoPbm). O sistema não "
            "pergunta: escolhe a convenção do glossário (`glossario-precos`: para comparar, PrecoFarmacia) e a "
            "**declara** em `suposicoes`, campo que o consumidor da saída lê sem interpretar o texto.",
            [("suposição declarada", bool(s(i2)["suposicoes"])),
             ("suficiente", s(i2)["suficiencia"] == "suficiente")]),
        bloco_exemplo(
            "3.5 Entrada fora do escopo — recusa e diz o que faz", "io-03-fora-do-escopo-t1.json",
            "`motivo_terminacao: fora_do_escopo`, decidido pela triagem; o laço do agente não rodou e nenhuma "
            "ferramenta foi chamada. O `resultado` diz por que recusou (dado de paciente identificado) e o que o "
            "sistema faz. A execução também **não** foi gravada na memória (pendência do Exercício 8 fechada): o "
            "log mostra `gravacoes_memoria` com o motivo.",
            [("fora do escopo", s(i3)["motivo_terminacao"] == "fora_do_escopo"),
             ("sem ferramentas", ferramentas(i3) == []),
             ("não gravou memória", all("pulado" in g for g in i3.get("gravacoes_memoria") or [{"pulado": 1}]))]),
    ]

    resumo = json.loads((LOGS / "resumo.json").read_text(encoding="utf-8"))
    c6 = resumo["casos"].get("caso-06-para-e-espera", {})
    pausa = carregar("caso-06-t1-pausa.json")
    ap1, ap2 = carregar("caso-06-t1-aprovacao-1.json"), carregar("caso-06-t1-aprovacao-2-repetida.json")
    linhas_casos = []
    for id_, prova, arquivo in [
        ("1 — simples", "o caminho feliz existe", "caso-01-simples-t1.json"),
        ("2 — divergência", "o sistema diz uma coisa, o usuário diz outra", "caso-02-divergencia-t1.json"),
        ("3 — registro inexistente", "erro de ferramenta que o modelo contorna", "caso-03-registro-inexistente-t1.json"),
        ("4 — não deve agir", "o sistema sabe não agir", "caso-04-nao-deve-agir-t1.json"),
        ("5 — fora do corpus", "recusa dizendo algo útil", "caso-05-fora-do-corpus-t1.json"),
        ("6 — para e espera", "pausa, aprova editando, a 2ª aprovação não duplica", "caso-06-t1-pausa.json"),
    ]:
        log = carregar(arquivo)
        linhas_casos.append(
            f"| {id_} | {prova} | {log['saida']['suficiencia']} | `{log['saida']['motivo_terminacao']}` | "
            f"{', '.join(ferramentas(log)) or '—'} | [`{arquivo}`](../logs/parte2/{arquivo}) |")

    acao1 = ap1["saida"]["acoes_executadas"][0] if ap1["saida"]["acoes_executadas"] else {}
    acao2 = ap2["saida"]["acoes_executadas"][0] if ap2["saida"]["acoes_executadas"] else {}
    c4 = carregar("caso-04-nao-deve-agir-t1.json")

    return f"""# Entrada e saída — o contrato do sistema

Parte 2, §1. **Gerado** por `python scripts/relatorio_parte2.py` a partir dos logs de `logs/parte2/`
(produzidos por `python scripts/run_casos_parte2.py`): os exemplos abaixo são copiados das
execuções, com o commit e a data que estão no carimbo de cada log. Não edite à mão — rode de novo.

## 1. A entrada é texto

O sistema recebe **texto livre** em português — `src/grafo/contrato.py::Entrada`:

| Campo | Quem preenche | Validação |
|---|---|---|
| `texto` | o gestor, digitando no chat | não vazio, até 800 caracteres (~200 tokens, o teto do "objetivo" no orçamento da janela); fora disso, `entrada_vazia`/`entrada_longa` sem chamar o modelo |
| `usuario_id` | **a sessão do sistema interno** (matrícula pseudônima, ex. `G-0042`) — não é digitado | `^[A-Za-z0-9_-]{{1,40}}$` |
| `sessao_id` | **a aba de chat** — não é digitado | idem |

`thread_id = usuario_id:sessao_id` é o endereço do checkpoint (ver `memoria.md` §5.5).

Onde as outras formas entram: o sistema **não** recebe formulário nem arquivo. O banco de preços e o
corpus são consultados **por ferramenta**; o "pedido para exportar" é texto ("salva essa análise"),
não um botão. Não há gatilho de outro sistema antes deste: toda execução começa com uma mensagem.

## 2. O contrato de saída

`src/grafo/contrato.py::SaidaAgente` (Pydantic; toda saída é validada em `montar_saida` antes de sair):

| Campo | Obrigatório pelo enunciado | O que é |
|---|---|---|
| `resultado` | **o resultado** | a resposta, a pergunta de volta ou a recusa — o texto que o gestor lê |
| `fontes` | **a fonte** | lista de `Fonte(tipo, referencia, detalhe)`: `banco_precos` (view + filtro + data da coleta), `corpus` (id do trecho **citado e conferido** entre os recuperados) ou `ferramenta` (a que respondeu "não implementado"). Extraída da trajetória **em código**, nunca escrita pelo modelo |
| `suficiencia` | **a suficiência** | `suficiente` · `insuficiente` · `aguardando_esclarecimento` · `aguardando_aprovacao` |
| `motivo_insuficiencia` | | por que não houve base (registro inexistente, base sem o assunto, pilar sem dado, teto...) |
| `suposicoes` | | escolhas feitas no lugar do gestor, declaradas |
| `pergunta_esclarecimento` | | a pergunta de volta, quando houver |
| `acoes_executadas` | | escritas feitas, com `chave_idempotencia` e `ja_existia` |
| `alertas` | | citação fora dos trechos recuperados, erro de ferramenta, falha da triagem |
| `motivo_terminacao`, `thread_id`, `turno` | | como e onde terminou |

**A suficiência é regra em código** (`montar_saida`): `suficiente` só quando o turno terminou em
`resposta_final` **e** existe ao menos uma fonte `banco_precos` ou `corpus`. Uma resposta fluente sem
fonte é `insuficiente`. A recusa é parte do contrato: uma saída `insuficiente` é válida, não exceção.

## 3. Os exemplos
{''.join(exemplos)}

## 4. Os seis casos demonstrados (§9)

| Caso | O que prova | Suficiência | Término | Ferramentas | Log |
|---|---|---|---|---|---|
{chr(10).join(linhas_casos)}

**Como ler cada um:**

- **2 — divergência:** o gestor afirma R$ 150; o sistema consulta, mostra o valor do banco com a
  data da coleta e destaca a diferença, sem concordar e sem meio-termo.
- **3 — registro inexistente:** a ferramenta devolve `encontrado: false` como **dado**; o modelo não
  tenta inventar nem insiste, e a suficiência sai `insuficiente` com o filtro que voltou vazio.
- **4 — não deve agir:** `exportar_analise` não foi chamada e o grafo não pausou
  (ferramentas: {', '.join(ferramentas(c4)) or '—'}). **Mas a resposta tem um erro de domínio**: a última
  coleta do espelho é de 19/09/2026, e pela regra `regras-ruptura#s04` (mais de 3 dias sem coleta) a
  situação é "sem coleta recente", não ruptura. O modelo não consultou a regra — ver `rag.md` §5.
- **6 — para e espera:** detalhado abaixo.

## 5. O caso 6 — pausa, aprovação editando, aprovação repetida

**Entrada:** `{pausa['pedido']['texto']}`

**1. O grafo para.** O modelo consultou o preço e pediu `exportar_analise`; o nó `aguardar_humano`
chamou `interrupt` e a saída voltou com `suficiencia: aguardando_aprovacao`. O que o revisor recebe
(campo `interrupcao` do log [`caso-06-t1-pausa.json`](../logs/parte2/caso-06-t1-pausa.json)):

```json
{json.dumps({k: (pausa['interrupcao'] or {}).get(k) for k in ('acao', 'argumentos', 'chave_idempotencia', 'consequencia', 'prazo_expira_em', 'se_ninguem_responder')}, ensure_ascii=False, indent=2)}
```

**2. A pessoa aprova editando** — corrige a `explicacao` antes de deixar seguir:

```json
{json.dumps(ap1['pedido'], ensure_ascii=False, indent=2)}
```

Resultado (log [`caso-06-t1-aprovacao-1.json`](../logs/parte2/caso-06-t1-aprovacao-1.json)):
arquivo `{acao1.get('resultado', {}).get('arquivo')}`, chave `{acao1.get('chave_idempotencia')}`,
`ja_existia: {acao1.get('ja_existia')}`. A chave difere da mostrada na pausa porque o conteúdo foi
editado — ela é recalculada sobre o que de fato foi gravado.

**3. A mesma aprovação chega de novo**, a partir do mesmo checkpoint da pausa
(`{c6.get('checkpoint_da_pausa')}`): log
[`caso-06-t1-aprovacao-2-repetida.json`](../logs/parte2/caso-06-t1-aprovacao-2-repetida.json) —
chave `{acao2.get('chave_idempotencia')}`, `ja_existia: {acao2.get('ja_existia')}`.

| | arquivos em `dados/exports/` |
|---|---|
| antes | {len(c6.get('exports_antes', []))} |
| depois da 1ª aprovação | {len(c6.get('exports_depois_aprovacao_1', []))} (novos: {', '.join(c6.get('arquivos_novos_aprovacao_1', [])) or '—'}) |
| depois da 2ª aprovação | {len(c6.get('exports_depois_aprovacao_2', []))} (novos: {', '.join(c6.get('arquivos_novos_aprovacao_2', [])) or '—'}) |

A segunda chamada à ferramenta aconteceu (está na trajetória do log), e não criou nada.

**Resposta final ao gestor** (depois da 1ª aprovação):

> {ap1['saida']['resultado'].replace(chr(10), chr(10) + '> ')}
"""


def tabela_medicoes() -> tuple[str, str]:
    linhas_par, linhas_rag = [], []
    soma = decorrido = maior = 0.0
    for arq in sorted(LOGS.glob("*-t*.json")):
        log = json.loads(arq.read_text(encoding="utf-8"))
        m = log["medicoes"]
        rag = m["chamadas_recuperacao_rag"]
        linhas_rag.append(f"| `{arq.stem}` | {log['tipo']} | {rag} | {m['chamadas_modelo_laco']} | {(log.get('triagem') or {}).get('pilar', '—')} |")
        p = m.get("paralelo")
        if p and log["tipo"] == "turno":
            linhas_par.append(f"| `{arq.stem}` | {p['memoria_ms']:.0f} | {p['triagem_ms']:.0f} | {p['soma_ms']:.0f} | {p['maior_ms']:.0f} | **{p['decorrido_ms']:.0f}** |")
            soma += p["soma_ms"]
            decorrido += p["decorrido_ms"]
            maior += p["maior_ms"]
    n = len(linhas_par)
    mem = sorted(float(l.split("|")[2]) for l in linhas_par)
    tri = sorted(float(l.split("|")[3]) for l in linhas_par)
    med_mem, med_tri = mem[len(mem) // 2], tri[len(tri) // 2]
    par = (
        "| turno | memória (ms) | triagem (ms) | soma (ms) | maior (ms) | decorrido (ms) |\n|---|---:|---:|---:|---:|---:|\n"
        + "\n".join(linhas_par)
        + f"\n| **total ({n} turnos)** | | | **{soma:.0f}** | **{maior:.0f}** | **{decorrido:.0f}** |\n\n"
        f"O decorrido tende ao **maior** dos ramos ({decorrido:.0f} ms contra {maior:.0f} ms), e não à soma ({soma:.0f} ms): "
        "há paralelismo de verdade, porque os ramos usam recursos diferentes (a memória é CPU local — SQLite e o e5-large "
        "via ONNX —, a triagem é espera de rede pela Groq). **O ganho é pequeno:** "
        f"{(soma - decorrido) / max(n, 1):.0f} ms por turno, {100 * (soma - decorrido) / max(soma, 1):.1f}% do tempo dos dois ramos, porque a memória é "
        f"muito mais rápida que a triagem (medianas: {med_mem:.0f} ms contra {med_tri:.0f} ms). O paralelo fica porque é de graça (não acrescenta chamada nem "
        "custo) e porque o ganho cresce com a memória: a busca episódica é linear no número de episódios do gestor. "
        "Com modelo local que atende uma requisição por vez — o caso medido na Aula 09 — o ganho seria o mesmo, já que só "
        "um dos ramos chama o modelo."
    )
    total_rag = sum(int(l.split("|")[3]) for l in linhas_rag)
    rag = (
        "| execução | tipo | chamadas de recuperação | chamadas ao modelo no laço | pilar (triagem) |\n|---|---|---:|---:|---|\n"
        + "\n".join(linhas_rag)
        + f"\n\n**{total_rag} chamadas de recuperação em {len(linhas_rag)} execuções.** Com etapa fixa seriam "
        f"{sum(1 for l in linhas_rag if '| turno |' in l)} buscas (uma por turno); as que o modelo pulou eram perguntas de "
        "preço, de esclarecimento ou fora do escopo — com uma exceção que custou a resposta certa: o caso 4 (§5)."
    )
    return par, rag


def substituir_entre_marcadores(caminho: Path, nome: str, conteudo: str) -> None:
    texto = caminho.read_text(encoding="utf-8")
    inicio, fim = f"<!-- {nome}:inicio -->", f"<!-- {nome}:fim -->"
    if inicio not in texto:
        raise SystemExit(f"{caminho.name}: marcador {inicio} ausente")
    novo = re.sub(re.escape(inicio) + r".*?" + re.escape(fim), lambda _: f"{inicio}\n{conteudo}\n{fim}", texto, flags=re.DOTALL)
    caminho.write_text(novo, encoding="utf-8")


def exemplos_readme() -> tuple[str, str]:
    c01, pausa = carregar("caso-01-simples-t1.json"), carregar("caso-06-t1-pausa.json")
    c = c01["carimbo"]
    principal = (
        f"Commit `{c['commit']}`, {c['data_utc']}, modelo `{c['modelo']}` — log "
        f"[`logs/parte2/caso-01-simples-t1.json`](logs/parte2/caso-01-simples-t1.json). Entrada: "
        f"`{c01['pedido']['texto']}`\n\n```json\n{json.dumps(c01['saida'], ensure_ascii=False, indent=2)}\n```\n\n"
        "A fonte diz de qual view e com qual filtro o número veio, e a data da coleta; `suficiencia` é decidida "
        "em código (há fonte do banco), não pelo modelo."
    )
    itr = pausa["interrupcao"] or {}
    pausa_txt = (
        f"Exemplo real ([`logs/parte2/caso-06-t1-pausa.json`](logs/parte2/caso-06-t1-pausa.json)) — entrada: "
        f"`{pausa['pedido']['texto']}` A saída volta com `suficiencia: aguardando_aprovacao`, e o revisor recebe:\n\n"
        f"```json\n{json.dumps({k: itr.get(k) for k in ('acao', 'argumentos', 'consequencia', 'prazo_expira_em', 'se_ninguem_responder')}, ensure_ascii=False, indent=2)}\n```"
    )
    return principal, pausa_txt


def main() -> None:
    (DOCS / "io.md").write_text(gerar_io(), encoding="utf-8")
    par, rag = tabela_medicoes()
    substituir_entre_marcadores(DOCS / "grafo.md", "medicoes-paralelo", par)
    substituir_entre_marcadores(DOCS / "rag.md", "medicoes-rag", rag)
    principal, pausa = exemplos_readme()
    substituir_entre_marcadores(RAIZ / "README.md", "exemplo-principal", principal)
    substituir_entre_marcadores(RAIZ / "README.md", "exemplo-pausa", pausa)
    print("docs/io.md gerado; tabelas de grafo.md §5 e rag.md §6 e exemplos do README atualizados.")


if __name__ == "__main__":
    main()

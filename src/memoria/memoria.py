"""As três memórias de longo prazo do agente de BI (Exercício 8), cada uma na estrutura que o
seu padrão de acesso pede:

| Tipo | O que guarda no case | Estrutura | Recuperação |
|---|---|---|---|
| episódica | o recorte de consultas passadas de cada gestor (pergunta mascarada, produto, farmácia, modo, ferramentas) | SQLite + vetor por linha, busca por similaridade em numpy | por relevância à pergunta atual, filtrada pelo gestor |
| semântica | fatos sobre entidades com chave natural: a farmácia padrão do gestor, aliases de produto | SQLite chave-valor, append-only, com `valido_desde` obrigatório | por chave; desempate por `max(valido_desde)` |
| procedural | regras de como conduzir a análise, escritas e revisadas pelo time de BI | arquivo de texto anexado ao system prompt | inteira, a cada execução |

Buscar a farmácia padrão de um gestor por similaridade seria mais caro e menos exato que ler
`usuario:<id>:farmacia_padrao` — por isso a semântica é chave-valor.

Toda escrita é escrita (Aula 05): tem chave de idempotência derivada do CONTEÚDO e devolve
`ja_existia`. `uuid4()` a cada chamada não deduplica nada.

O esquecimento tem três causas, e nenhuma exige reconstruir índice: o índice episódico é uma
tabela com o vetor na própria linha, então remover é `DELETE` — o que mantém a remoção útil para
recuperação de incidente (memória envenenada sai na hora, não na próxima reindexação).
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from src.rag.embeddings import CAMINHO_CACHE, EmbeddingComCache, ModeloEmbedding

from .politica import RecorteExtraido, texto_para_memoria

PASTA_MEMORIA_PADRAO = Path(__file__).resolve().parents[2] / "dados" / "memoria"

# Decaimento da episódica: 90 dias. A coleta de preço é diária e o recorte que um gestor usa
# (produto × farmácia) muda com o portfólio monitorado e as campanhas, que mudam por trimestre;
# um episódio de mais de um trimestre descreve um portfólio que pode nem existir mais. É
# REMOÇÃO (não rebaixamento): rebaixar manteria o dado, e a remoção por titular teria de
# alcançar mais registros por mais tempo. A semântica não decai por idade — preferência não
# envelhece, é substituída (contradição).
DIAS_DECAIMENTO_EPISODICA = 90


def chave_idempotencia(*partes: str) -> str:
    return hashlib.sha256("\x1f".join(partes).encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class Gravacao:
    id: str
    ja_existia: bool


@dataclass(frozen=True)
class Episodio:
    id: str
    usuario_id: str
    data: str
    texto: str
    recorte: dict
    distancia: float | None = None


@dataclass(frozen=True)
class Fato:
    chave: str
    valor: str
    valido_desde: str
    origem: str


@dataclass(frozen=True)
class LeituraFato:
    vencedor: Fato | None
    descartados: list[Fato]


class Memoria:
    def __init__(self, embeddings: ModeloEmbedding, pasta: Path = PASTA_MEMORIA_PADRAO) -> None:
        self.embeddings = embeddings
        self.pasta = pasta
        pasta.mkdir(parents=True, exist_ok=True)
        self.caminho_db = pasta / "memoria.db"
        self.caminho_procedural = pasta / "procedural.md"
        self.caminho_descartes = pasta / "descartes.jsonl"
        # check_same_thread=False: `carregar_memoria` roda numa thread do LangGraph (em paralelo com a
        # triagem) e `gravar_memoria` em outra; os dois nunca rodam no mesmo superstep.
        self.conn = sqlite3.connect(self.caminho_db, check_same_thread=False)
        # Sem secure_delete, o texto de um episódio apagado continua nos bytes do arquivo até a
        # página ser reutilizada — a varredura por bytes de `varrer` encontraria o titular.
        self.conn.execute("PRAGMA secure_delete = ON")
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS episodica (
                id TEXT PRIMARY KEY, usuario_id TEXT NOT NULL, data TEXT NOT NULL,
                texto TEXT NOT NULL, recorte TEXT NOT NULL, vetor BLOB NOT NULL
            );
            CREATE TABLE IF NOT EXISTS semantica (
                id TEXT PRIMARY KEY, chave TEXT NOT NULL, valor TEXT NOT NULL,
                valido_desde TEXT NOT NULL, origem TEXT NOT NULL, gravado_em TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS ix_semantica_chave ON semantica (chave);
            """
        )
        if not self.caminho_procedural.exists():
            self.caminho_procedural.write_text("", encoding="utf-8")

    def fechar(self) -> None:
        self.conn.close()

    # ---------------------------------------------------------------- episódica
    @staticmethod
    def texto_do_episodio(pergunta: str, recorte: RecorteExtraido) -> str:
        partes = [f"Pergunta: {texto_para_memoria(pergunta)}"]
        if recorte.produtos:
            partes.append(f"produto: {', '.join(recorte.produtos)}")
        if recorte.farmacias:
            partes.append(f"farmácia: {', '.join(recorte.farmacias)}")
        if recorte.modos:
            partes.append(f"modo: {', '.join(recorte.modos)}")
        return " | ".join(partes)

    def gravar_episodio(self, usuario_id: str, data: str, pergunta: str, recorte: RecorteExtraido) -> Gravacao:
        texto = self.texto_do_episodio(pergunta, recorte)
        # Chave pelo CONTEÚDO: mesmo gestor, mesmo dia, mesmo texto = mesmo episódio. Uma
        # retentativa da execução (ou a retomada de um checkpoint) não duplica a memória.
        id_ = chave_idempotencia("episodica", usuario_id, data, texto)
        if self.conn.execute("SELECT 1 FROM episodica WHERE id = ?", (id_,)).fetchone():
            return Gravacao(id_, True)
        vetor = self.embeddings.embed_documentos([texto])[0]
        recorte_json = json.dumps(recorte.__dict__, ensure_ascii=False)
        self.conn.execute(
            "INSERT INTO episodica VALUES (?, ?, ?, ?, ?, ?)", (id_, usuario_id, data, texto, recorte_json, vetor.tobytes())
        )
        self.conn.commit()
        return Gravacao(id_, False)

    def buscar_episodios(self, usuario_id: str, pergunta: str, k: int = 3) -> list[Episodio]:
        linhas = self.conn.execute(
            "SELECT id, usuario_id, data, texto, recorte, vetor FROM episodica WHERE usuario_id = ?", (usuario_id,)
        ).fetchall()
        if not linhas:
            return []
        matriz = np.stack([np.frombuffer(v, dtype=np.float32) for *_, v in linhas])
        consulta = self.embeddings.embed_consultas([pergunta])[0]
        distancias = 1.0 - matriz @ consulta
        ordem = np.argsort(distancias, kind="stable")[:k]
        return [
            Episodio(linhas[i][0], linhas[i][1], linhas[i][2], linhas[i][3], json.loads(linhas[i][4]), float(distancias[i]))
            for i in ordem
        ]

    def contar_episodios(self) -> int:
        return self.conn.execute("SELECT COUNT(*) FROM episodica").fetchone()[0]

    # ---------------------------------------------------------------- semântica
    def gravar_fato(self, chave: str, valor: str, valido_desde: str, origem: str) -> Gravacao:
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", valido_desde or ""):
            raise ValueError("todo fato precisa de valido_desde AAAA-MM-DD: sem carimbo não há desempate")
        id_ = chave_idempotencia("semantica", chave, valor, valido_desde)
        if self.conn.execute("SELECT 1 FROM semantica WHERE id = ?", (id_,)).fetchone():
            return Gravacao(id_, True)
        self.conn.execute(
            "INSERT INTO semantica VALUES (?, ?, ?, ?, ?, ?)",
            (id_, chave, valor, valido_desde, origem, datetime.now(timezone.utc).isoformat(timespec="seconds")),
        )
        self.conn.commit()
        return Gravacao(id_, False)

    def ler_fato(self, chave: str) -> LeituraFato:
        """Desempate determinístico: vence o maior `valido_desde`; em empate de data, o gravado
        por último. Os perdedores NÃO são apagados (contradição não apaga — o fato antigo era
        verdade na época dele) e o descarte é registrado: um descarte silencioso é
        indistinguível, no log, de um fato que nunca foi recuperado."""
        linhas = self.conn.execute(
            "SELECT chave, valor, valido_desde, origem, gravado_em FROM semantica WHERE chave = ?", (chave,)
        ).fetchall()
        if not linhas:
            return LeituraFato(None, [])
        ordenadas = sorted(linhas, key=lambda r: (r[2], r[4]), reverse=True)
        vencedor, *perdedores = [Fato(c, v, d, o) for c, v, d, o, _ in ordenadas]
        if perdedores:
            with self.caminho_descartes.open("a", encoding="utf-8") as f:
                for p in perdedores:
                    f.write(json.dumps({
                        "lido_em": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                        "chave": chave, "descartado": p.__dict__, "vencedor": vencedor.__dict__,
                        "regra": "max(valido_desde)",
                    }, ensure_ascii=False) + "\n")
        return LeituraFato(vencedor, perdedores)

    def chaves_do_usuario(self, usuario_id: str) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT DISTINCT chave FROM semantica WHERE chave LIKE ?", (f"usuario:{usuario_id}:%",)
        ).fetchall()]

    def contar_chaves(self) -> int:
        return self.conn.execute("SELECT COUNT(DISTINCT chave) FROM semantica").fetchone()[0]

    # --------------------------------------------------------------- procedural
    def gravar_regra(self, regra: str, autor: str) -> Gravacao:
        """Só humanos (time de BI) escrevem regra procedural — a regra entra no system prompt de
        TODAS as execuções, e uma regra escrita pelo próprio agente a partir de um erro é
        exatamente o vetor de envenenamento persistente da Aula 14."""
        id_ = chave_idempotencia("procedural", regra.strip())
        atual = self.caminho_procedural.read_text(encoding="utf-8")
        if f"[{id_}]" in atual:
            return Gravacao(id_, True)
        with self.caminho_procedural.open("a", encoding="utf-8") as f:
            f.write(f"- [{id_}] {regra.strip()} (autor: {autor})\n")
        return Gravacao(id_, False)

    def texto_procedural(self) -> str:
        return self.caminho_procedural.read_text(encoding="utf-8").strip()

    # ---------------------------------------------------------- esquecimento
    def decair(self, hoje: date, dias: int = DIAS_DECAIMENTO_EPISODICA) -> int:
        corte = (hoje - timedelta(days=dias)).isoformat()
        cursor = self.conn.execute("DELETE FROM episodica WHERE data < ?", (corte,))
        self.conn.commit()
        return cursor.rowcount

    def remover_registro(self, id_: str) -> bool:
        """Esquecimento seletivo de UM registro (episódico ou semântico), por id."""
        removidos = 0
        textos = [r[0] for r in self.conn.execute("SELECT texto FROM episodica WHERE id = ?", (id_,))]
        removidos += self.conn.execute("DELETE FROM episodica WHERE id = ?", (id_,)).rowcount
        removidos += self.conn.execute("DELETE FROM semantica WHERE id = ?", (id_,)).rowcount
        self.conn.commit()
        self._remover_do_cache_de_embeddings(textos)
        return removidos > 0

    def _remover_do_cache_de_embeddings(self, textos: list[str]) -> None:
        """O cache de embeddings guarda o vetor do texto do episódio — derivado do texto, e
        portanto do identificador que ele contiver. Fica de fora de quase toda lista de remoção."""
        caminho = getattr(self.embeddings, "_caminho_cache", CAMINHO_CACHE)
        if not textos or not Path(caminho).exists():
            return
        prefixo = self.embeddings.prefixo_documento
        with sqlite3.connect(caminho) as conn:
            conn.execute("PRAGMA secure_delete = ON")
            for t in textos:
                conn.execute(
                    "DELETE FROM cache WHERE modelo = ? AND hash = ?",
                    (self.embeddings.nome, EmbeddingComCache._hash(prefixo + t)),
                )

    def remover_titular(self, usuario_id: str, pastas_extras: list[Path]) -> dict[str, int]:
        """Remoção a pedido do titular (o gestor saiu da empresa, ou pediu pela LGPD). Alcança:
        episódica (+ vetores no cache), semântica (chaves do usuário), procedural (linhas que o
        mencionem), e arquivos de checkpoint e de log em `pastas_extras` — os dois que escapam
        com frequência, porque não são "memória" e guardam os argumentos de cada passo."""
        relatorio: dict[str, int] = {}
        textos = [r[0] for r in self.conn.execute("SELECT texto FROM episodica WHERE usuario_id = ?", (usuario_id,))]
        relatorio["episodica"] = self.conn.execute("DELETE FROM episodica WHERE usuario_id = ?", (usuario_id,)).rowcount
        relatorio["semantica"] = self.conn.execute(
            "DELETE FROM semantica WHERE chave LIKE ? OR origem LIKE ?", (f"usuario:{usuario_id}:%", f"%{usuario_id}%")
        ).rowcount
        self.conn.commit()
        self._remover_do_cache_de_embeddings(textos)
        relatorio["cache_embeddings"] = len(textos)

        linhas = self.caminho_procedural.read_text(encoding="utf-8").splitlines(keepends=True)
        mantidas = [l for l in linhas if usuario_id not in l]
        relatorio["procedural"] = len(linhas) - len(mantidas)
        self.caminho_procedural.write_text("".join(mantidas), encoding="utf-8")

        if self.caminho_descartes.exists():
            linhas = self.caminho_descartes.read_text(encoding="utf-8").splitlines(keepends=True)
            mantidas = [l for l in linhas if usuario_id not in l]
            relatorio["registro_de_descartes"] = len(linhas) - len(mantidas)
            self.caminho_descartes.write_text("".join(mantidas), encoding="utf-8")

        arquivos = 0
        for pasta in pastas_extras:
            for arquivo in pasta.rglob("*.json"):
                texto = arquivo.read_text(encoding="utf-8")
                if usuario_id in texto:
                    # Checkpoint e log são REDIGIDOS, não apagados: o resto da trajetória é
                    # evidência de execução que não pertence ao titular.
                    arquivo.write_text(texto.replace(usuario_id, "[titular-removido]"), encoding="utf-8")
                    arquivos += 1
        relatorio["checkpoints_e_logs"] = arquivos
        return relatorio

    def varrer(self, identificador: str, pastas_extras: list[Path]) -> list[str]:
        """Verificação INDEPENDENTE da remoção: não confia no relatório de `remover_titular` —
        relê cada estrutura e procura o identificador. Lista vazia = remoção comprovada."""
        achados = []
        for tabela, colunas in (("episodica", ("usuario_id", "texto", "recorte")), ("semantica", ("chave", "valor", "origem"))):
            for coluna in colunas:
                n = self.conn.execute(f"SELECT COUNT(*) FROM {tabela} WHERE {coluna} LIKE ?", (f"%{identificador}%",)).fetchone()[0]
                if n:
                    achados.append(f"{tabela}.{coluna}: {n}")
        for caminho in (self.caminho_procedural, self.caminho_descartes):
            if caminho.exists() and identificador in caminho.read_text(encoding="utf-8"):
                achados.append(str(caminho.name))
        # Conjunto de arquivos: pastas aninhadas (checkpoints dentro da pasta da memória) não podem
        # contar o mesmo arquivo duas vezes.
        arquivos = sorted({a.resolve() for pasta in pastas_extras for a in pasta.rglob("*") if a.is_file()})
        achados += [str(a) for a in arquivos if identificador.encode() in a.read_bytes()]
        return achados


def medir_ms(funcao, *args, repeticoes: int = 20) -> float:
    inicio = time.perf_counter()
    for _ in range(repeticoes):
        funcao(*args)
    return 1000 * (time.perf_counter() - inicio) / repeticoes

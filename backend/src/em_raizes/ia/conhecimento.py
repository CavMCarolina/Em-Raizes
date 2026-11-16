"""Base de conhecimento do Guardião (RAG simples, sem banco vetorial).

O manual em Markdown é dividido em trechos por título (## e ###) e a busca
usa BM25 com normalização de acentos. É leve, explicável e roda offline.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

CAMINHO_MANUAL = Path(__file__).parent / "conhecimento" / "manual.md"

STOPWORDS = set(
    """
    a o as os um uma uns umas de da do das dos dum duma em no na nos nas num numa por pelo pela pelos pelas
    para pra pro com sem sob sobre e ou mas que se ao aos à às é ser sao são foi era tem ter ha há como
    qual quais quando onde porque por que eu voce você ele ela eles elas meu minha seu sua isso isto esse
    essa este esta aquele aquela me te lhe nos vos ja já nao não mais muito muita pode posso faco faço fazer
    o que oque está esta estou tá ta vai vou dar deu
    """.split()
)


def normalizar(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto.lower())
    return "".join(c for c in texto if not unicodedata.combining(c))


SUFIXOS = ("acao", "ando", "endo", "indo", "ado", "ada", "ar", "er", "ir")


def _radical(token: str) -> str:
    """Stemming mínimo em português.

    Tira o plural ("trincas" -> "trinca", "missoes" -> "missao") e algumas
    terminações verbais ("irrigando", "irrigar", "irrigacao" -> "irrig").
    """
    if len(token) > 4 and token.endswith("oes"):
        token = token[:-3] + "ao"
    elif len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        token = token[:-1]
    if len(token) > 5:
        for suf in SUFIXOS:
            if token.endswith(suf) and len(token) - len(suf) >= 4:
                return token[: -len(suf)]
    return token


def tokenizar(texto: str) -> list[str]:
    tokens = re.findall(r"[a-z0-9]+", normalizar(texto))
    return [_radical(t) for t in tokens if t not in STOPWORDS and len(t) > 1]


@dataclass
class Trecho:
    titulo: str
    texto: str


def dividir_markdown(md: str) -> list[Trecho]:
    trechos: list[Trecho] = []
    titulo_secao, titulo, linhas = "", "", []

    def fechar():
        corpo = "\n".join(linhas).strip()
        if titulo and corpo:
            trechos.append(Trecho(titulo=titulo, texto=corpo))

    for linha in md.splitlines():
        if linha.startswith("## "):
            fechar()
            titulo_secao = linha[3:].strip()
            titulo, linhas = titulo_secao, []
        elif linha.startswith("### "):
            fechar()
            titulo, linhas = f"{titulo_secao} > {linha[4:].strip()}", []
        elif linha.startswith("# "):
            continue
        else:
            linhas.append(linha)
    fechar()
    return trechos


class BaseConhecimento:
    def __init__(self, caminho: Path | str = CAMINHO_MANUAL, k1: float = 1.5, b: float = 0.75):
        self.trechos = dividir_markdown(Path(caminho).read_text(encoding="utf-8"))
        # o título conta em dobro: ajuda perguntas curtas como "erro 401"
        self._docs = [tokenizar(t.titulo) * 2 + tokenizar(t.texto) for t in self.trechos]
        self._tf = [Counter(d) for d in self._docs]
        self._media = sum(len(d) for d in self._docs) / max(len(self._docs), 1)
        n = len(self._docs)
        df = Counter(t for d in self._docs for t in set(d))
        self._idf = {t: math.log(1 + (n - f + 0.5) / (f + 0.5)) for t, f in df.items()}
        self.k1, self.b = k1, b

    def buscar(self, pergunta: str, k: int = 3, minimo: float = 0.5) -> list[tuple[Trecho, float]]:
        consulta = tokenizar(pergunta)
        if not consulta:
            return []
        pontuados = []
        for trecho, tf, doc in zip(self.trechos, self._tf, self._docs, strict=True):
            score = 0.0
            for termo in consulta:
                if termo not in tf:
                    continue
                f = tf[termo]
                denom = f + self.k1 * (1 - self.b + self.b * len(doc) / self._media)
                score += self._idf.get(termo, 0) * f * (self.k1 + 1) / denom
            if score >= minimo:
                pontuados.append((trecho, round(score, 2)))
        pontuados.sort(key=lambda x: x[1], reverse=True)
        return pontuados[:k]

    def contexto(self, pergunta: str, k: int = 3) -> tuple[str, list[str]]:
        achados = self.buscar(pergunta, k=k)
        if not achados:
            return "(nenhum trecho do manual parece relevante)", []
        texto = "\n\n".join(f"[{t.titulo}]\n{t.texto}" for t, _ in achados)
        return texto, [t.titulo for t, _ in achados]

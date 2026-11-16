"""Análise de risco de deslizamento, irrigação e prioridades de plantio.

O índice de risco é uma combinação ponderada e explicável dos fatores que a
literatura de geotecnia aponta como mais relevantes para deslizamentos rasos:
declividade, saturação do solo, chuva acumulada, falta de vegetação, tipo de
solo e sinais visíveis (fissuras, erosão, vazamentos).

ATENÇÃO: os pesos e limiares são ILUSTRATIVOS (MVP acadêmico). Um sistema
real precisa ser calibrado com dados históricos e validado pela Defesa Civil.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .modelos import POROSIDADE, TAMANHO_CELULA_M, Mapeamento

PESOS = {
    "declividade": 0.28,
    "saturacao": 0.22,
    "chuva": 0.18,
    "vegetacao": 0.12,
    "solo": 0.10,
    "sinais": 0.10,
}

FATOR_SOLO = {"rochoso": 0.10, "argiloso": 0.45, "siltoso": 0.60, "arenoso": 0.75, "aterro": 1.00}

# (limite inferior, limite superior, nome, cor)
CLASSES_RISCO = [
    (0, 30, "baixo", "#2e7d32"),
    (30, 55, "moderado", "#fdd835"),
    (55, 75, "alto", "#ef6c00"),
    (75, 101, "critico", "#c62828"),
]
ORDEM_CLASSES = [c[2] for c in CLASSES_RISCO]

NIVEIS_ALERTA = {
    "normal": {"titulo": "Normal", "cor": "#2e7d32", "ordem": 0},
    "atencao": {"titulo": "Atenção", "cor": "#f57f17", "ordem": 1},
    "alerta": {"titulo": "Alerta", "cor": "#ef6c00", "ordem": 2},
    "alerta_maximo": {"titulo": "Alerta máximo — evacuar", "cor": "#c62828", "ordem": 3},
}

DECLIVIDADE_MAX_ROBO = 35.0  # acima disso o robô não sobe: plantio manual com equipe técnica
UMIDADE_IRRIGAR = 18.0  # abaixo disso as mudas jovens precisam de água
UMIDADE_ALVO = 25.0
MUDAS_POR_CELULA = 400  # capim-vetiver em linhas de nível a cada ~1,5 m, mudas a cada ~15 cm


def _norm(v, lo: float, hi: float):
    return np.clip((np.asarray(v, dtype=float) - lo) / (hi - lo), 0.0, 1.0)


def classificar(indice) -> np.ndarray:
    indice = np.asarray(indice, dtype=float)
    out = np.empty(indice.shape, dtype=object)
    for lo, hi, nome, _ in CLASSES_RISCO:
        out[(indice >= lo) & (indice < hi)] = nome
    return out


def fatores_risco(df: pd.DataFrame, chuva_mm: float, umidade=None) -> pd.DataFrame:
    """Cada fator normalizado entre 0 (bom) e 1 (ruim)."""
    umid = df["umidade_pct"] if umidade is None else umidade
    sinais = np.clip(0.6 * df["prob_fissura"] + 0.4 * df["erosao"] + 0.2 * df["vazamento"].astype(float), 0, 1)
    return pd.DataFrame(
        {
            "declividade": _norm(df["declividade_graus"], 10, 45),
            "saturacao": _norm(np.asarray(umid) / POROSIDADE, 0.35, 1.0),
            "chuva": np.full(len(df), float(_norm(chuva_mm, 20, 180))),
            "vegetacao": 1 - df["cobertura_vegetal"].to_numpy(),
            "solo": df["tipo_solo"].map(FATOR_SOLO).to_numpy(),
            "sinais": np.asarray(sinais),
        },
        index=df.index,
    )


def indice_risco(df: pd.DataFrame, chuva_mm: float, umidade=None) -> np.ndarray:
    f = fatores_risco(df, chuva_mm, umidade)
    soma = sum(PESOS[k] * f[k] for k in PESOS)
    # terreno plano quase não desliza: a declividade "libera" o risco
    gate = 0.35 + 0.65 * f["declividade"]
    return np.clip(100 * soma * gate * 1.15, 0, 100).round(1).to_numpy()


def umidade_prevista(df: pd.DataFrame, previsao_24h: float) -> np.ndarray:
    """Quanto a umidade sobe se a chuva prevista para 24 h se confirmar."""
    ganho = 0.12 * previsao_24h * (1 - 0.3 * df["cobertura_vegetal"])
    return np.clip(df["umidade_pct"] + ganho, 0, POROSIDADE).to_numpy()


def zona_atingimento(df: pd.DataFrame, criticas: pd.Series, alcance: int = 2) -> pd.Series:
    """Células logo abaixo (morro abaixo) de uma célula crítica também correm perigo."""
    alvo = pd.Series(False, index=df.index)
    pos = {(r, c): i for i, r, c in zip(df.index, df["linha"], df["coluna"], strict=True)}
    for i in df.index[criticas]:
        r, c = df.at[i, "linha"], df.at[i, "coluna"]
        for dr in range(1, alcance + 1):
            for dc in (-1, 0, 1):
                j = pos.get((r + dr, c + dc))
                if j is not None:
                    alvo.at[j] = True
    return alvo


@dataclass
class Alerta:
    nivel: str
    titulo: str
    cor: str
    mensagem: str
    acao: str
    pessoas_em_risco: float
    casas_em_risco: int
    celulas_evacuar: list[str] = field(default_factory=list)


@dataclass
class Analise:
    mapa: Mapeamento
    df: pd.DataFrame
    alerta: Alerta
    estatisticas: dict

    @property
    def criticas(self) -> pd.DataFrame:
        return self.df[self.df["classe_risco"] == "critico"]


def _definir_alerta(df: pd.DataFrame, mapa: Mapeamento) -> Alerta:
    ocupada = df["casas"] > 0
    crit_agora = df["classe_risco"] == "critico"
    crit_24h = df["classe_risco_24h"] == "critico"
    alto_agora = df["classe_risco"].isin(["alto", "critico"])

    atingida = zona_atingimento(df, crit_agora)
    evacuar = ocupada & (crit_agora | atingida)

    if evacuar.any():
        nivel = "alerta_maximo"
        acao = (
            "Evacuar imediatamente as casas listadas e seguir para o ponto de apoio. "
            "Acionar Defesa Civil (199) e Bombeiros (193)."
        )
    elif (ocupada & (crit_24h | zona_atingimento(df, crit_24h))).any() or (
        (ocupada & alto_agora).sum() >= 5 and mapa.chuva_72h >= 60
    ):
        nivel = "alerta"
        evacuar = ocupada & (crit_24h | zona_atingimento(df, crit_24h) | alto_agora)
        acao = (
            "Preparar evacuação preventiva: avisar moradores, separar documentos e "
            "remédios, observar trincas e água barrenta. Robô recolhido."
        )
    elif alto_agora.any() or crit_24h.any() or mapa.previsao_24h >= 30:
        nivel = "atencao"
        evacuar = pd.Series(False, index=df.index)
        acao = "Monitorar a chuva e fazer vistoria nas áreas destacadas em laranja/vermelho."
    else:
        nivel = "normal"
        evacuar = pd.Series(False, index=df.index)
        acao = "Seguir com plantio e irrigação programados."

    info = NIVEIS_ALERTA[nivel]
    casas = int(df.loc[evacuar, "casas"].sum())
    pessoas = float(df.loc[evacuar, "moradores_estimados"].sum())
    msg = {
        "alerta_maximo": f"Risco crítico de deslizamento em área com {casas} casas (~{pessoas:.0f} pessoas).",
        "alerta": f"Risco pode virar crítico nas próximas 24 h em área com {casas} casas (~{pessoas:.0f} pessoas).",
        "atencao": "Há trechos com risco alto, mas sem casas diretamente expostas agora.",
        "normal": "Nenhum trecho com risco alto no momento.",
    }[nivel]
    return Alerta(
        nivel=nivel,
        titulo=info["titulo"],
        cor=info["cor"],
        mensagem=msg,
        acao=acao,
        pessoas_em_risco=round(pessoas, 1),
        casas_em_risco=casas,
        celulas_evacuar=df.loc[evacuar].sort_values("risco_24h", ascending=False)["celula"].tolist(),
    )


def analisar(mapa: Mapeamento) -> Analise:
    """Calcula risco atual, risco previsto (24 h), irrigação e plantio."""
    df = mapa.celulas.copy()

    df["risco"] = indice_risco(df, mapa.chuva_72h)
    df["classe_risco"] = classificar(df["risco"])

    # Previsão: janela de 72 h "anda" um dia (sai o dia mais antigo, entra a previsão)
    chuva_futura = mapa.chuva_72h * 0.67 + mapa.previsao_24h
    df["umidade_24h"] = umidade_prevista(df, mapa.previsao_24h).round(1)
    df["risco_24h"] = indice_risco(df, chuva_futura, df["umidade_24h"])
    df["classe_risco_24h"] = classificar(df["risco_24h"])
    df["tendencia"] = np.select(
        [df["risco_24h"] - df["risco"] > 5, df["risco"] - df["risco_24h"] > 5],
        ["subindo", "caindo"],
        "estavel",
    )

    # Irrigação: só em áreas sem casas com vegetação em formação (cobertura 15–60%),
    # solo seco, risco baixo/moderado e sem chuva prevista. Encosta encharcada NUNCA é irrigada.
    vai_chover = mapa.previsao_24h >= 10
    df["precisa_irrigar"] = (
        (df["umidade_pct"] < UMIDADE_IRRIGAR)
        & df["classe_risco"].isin(["baixo", "moderado"])
        & (df["casas"] == 0)
        & (df["tipo_solo"] != "rochoso")
        & df["cobertura_vegetal"].between(0.15, 0.6)
        & (not vai_chover)
    )
    area = TAMANHO_CELULA_M**2
    deficit = np.clip(UMIDADE_ALVO - df["umidade_pct"], 0, None) / 100
    # rega só as faixas plantadas (~30% da célula) até ~5 cm de profundidade
    df["litros_irrigacao"] = np.where(df["precisa_irrigar"], (area * 0.3 * 0.05 * deficit * 1000).round(0), 0)

    # Plantio de capim-vetiver
    apto = (
        (df["casas"] == 0)
        & (df["tipo_solo"] != "rochoso")
        & (df["cobertura_vegetal"] < 0.5)
        & (df["declividade_graus"].between(8, 45))
    )
    f_decl = _norm(df["declividade_graus"], 10, 45)
    prioridade = (1 - df["cobertura_vegetal"]) * (0.5 + 0.5 * f_decl) * (df["risco"] / 100 + 0.3)
    df["prioridade_plantio"] = np.where(apto, (prioridade * 100).round(1), 0.0)
    df["plantio_recomendado"] = apto & (df["prioridade_plantio"] >= 30)
    df["plantio_manual"] = df["plantio_recomendado"] & (df["declividade_graus"] > DECLIVIDADE_MAX_ROBO)
    df["mudas"] = np.where(
        df["plantio_recomendado"], (MUDAS_POR_CELULA * (1 - df["cobertura_vegetal"])).round(0), 0
    ).astype(int)

    alerta = _definir_alerta(df, mapa)

    contagem = df["classe_risco"].value_counts().reindex(ORDEM_CLASSES, fill_value=0)
    contagem_24h = df["classe_risco_24h"].value_counts().reindex(ORDEM_CLASSES, fill_value=0)
    estat = {
        "celulas": len(df),
        "area_ha": mapa.area_m2 / 10_000,
        "casas": int(df["casas"].sum()),
        "moradores": float(df["moradores_estimados"].sum()),
        "por_classe": contagem.to_dict(),
        "por_classe_24h": contagem_24h.to_dict(),
        "risco_medio": float(df["risco"].mean().round(1)),
        "risco_medio_24h": float(df["risco_24h"].mean().round(1)),
        "fissuras": int(df["fissura_detectada"].sum()),
        "vazamentos": int(df["vazamento"].sum()),
        "celulas_plantio": int(df["plantio_recomendado"].sum()),
        "celulas_plantio_manual": int(df["plantio_manual"].sum()),
        "mudas": int(df["mudas"].sum()),
        "celulas_irrigar": int(df["precisa_irrigar"].sum()),
        "litros": float(df["litros_irrigacao"].sum()),
        "cobertura_media": float(df["cobertura_vegetal"].mean().round(2)),
        "umidade_media": float(df["umidade_pct"].mean().round(1)),
    }
    return Analise(mapa=mapa, df=df, alerta=alerta, estatisticas=estat)


def explicar_celula(analise: Analise, celula: str) -> dict:
    """Contribuição de cada fator para o risco de uma célula (explicabilidade)."""
    df = analise.df
    linha = df[df["celula"] == celula]
    if linha.empty:
        raise KeyError(f"Célula {celula} não existe neste mapeamento.")
    f = fatores_risco(linha, analise.mapa.chuva_72h).iloc[0]
    contrib = {k: round(PESOS[k] * float(f[k]) * 100, 1) for k in PESOS}
    return {"celula": celula, "fatores_0a1": f.round(2).to_dict(), "contribuicao_pts": contrib}

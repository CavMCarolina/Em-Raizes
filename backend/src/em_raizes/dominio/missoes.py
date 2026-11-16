"""Missões do robô jardineiro (simuladas).

Transforma a análise do drone em uma fila de tarefas para o robô:
plantio de capim-vetiver, irrigação de mudas e inspeção de fissuras.
A rota é ordenada pelo vizinho mais próximo a partir da base do robô.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

from .modelos import TAMANHO_CELULA_M
from .risco import NIVEIS_ALERTA, Analise

CAPACIDADE_MUDAS = 600  # mudas por viagem
CAPACIDADE_AGUA_L = 300  # litros por viagem
VELOCIDADE_M_MIN = 12  # robô de esteira em encosta
MIN_POR_MUDA = 0.05
MIN_POR_100L = 6


def _base_robo(analise: Analise) -> tuple[int, int]:
    """Base do robô: canto inferior esquerdo (pé do morro, acesso pela rua)."""
    return analise.mapa.linhas - 1, 0


def gerar_missoes(analise: Analise) -> pd.DataFrame:
    df = analise.df
    tarefas = []

    for _, r in df[df["plantio_recomendado"]].iterrows():
        tarefas.append(
            {
                "tipo": "plantio",
                "celula": r["celula"],
                "linha": int(r["linha"]),
                "coluna": int(r["coluna"]),
                "prioridade_valor": float(r["prioridade_plantio"]),
                "mudas": int(r["mudas"]),
                "litros": 0.0,
                "executor": "equipe técnica" if r["plantio_manual"] else "robô",
                "observacao": (
                    f"Declividade {r['declividade_graus']:.0f}° acima do limite do robô"
                    if r["plantio_manual"]
                    else "Plantar em linhas de nível (curvas de nível)"
                ),
            }
        )
    for _, r in df[df["precisa_irrigar"]].iterrows():
        tarefas.append(
            {
                "tipo": "irrigacao",
                "celula": r["celula"],
                "linha": int(r["linha"]),
                "coluna": int(r["coluna"]),
                "prioridade_valor": float(60 - r["umidade_pct"]),
                "mudas": 0,
                "litros": float(r["litros_irrigacao"]),
                "executor": "robô",
                "observacao": f"Umidade {r['umidade_pct']:.0f}% (meta 25%)",
            }
        )
    for _, r in df[df["fissura_detectada"]].iterrows():
        tarefas.append(
            {
                "tipo": "inspecao",
                "celula": r["celula"],
                "linha": int(r["linha"]),
                "coluna": int(r["coluna"]),
                "prioridade_valor": float(r["risco"] + 20),
                "mudas": 0,
                "litros": 0.0,
                "executor": "Defesa Civil" if r["casas"] > 0 else "robô (câmera)",
                "observacao": f"Fissura detectada pela visão (prob. {r['prob_fissura']:.0%})",
            }
        )

    colunas = [
        "ordem",
        "id",
        "tipo",
        "celula",
        "linha",
        "coluna",
        "prioridade",
        "mudas",
        "litros",
        "executor",
        "duracao_min",
        "status",
        "observacao",
    ]
    if not tarefas:
        return pd.DataFrame(columns=colunas)

    m = pd.DataFrame(tarefas)
    m["prioridade"] = pd.cut(m["prioridade_valor"], [-np.inf, 35, 60, np.inf], labels=["baixa", "média", "alta"])
    m["prioridade"] = m["prioridade"].astype(str)

    # Rota: vizinho mais próximo a partir da base, priorizando "alta"
    pos = _base_robo(analise)
    restantes = m.copy()
    ordem = []
    for nivel in ["alta", "média", "baixa"]:
        grupo = restantes[restantes["prioridade"] == nivel]
        idx = list(grupo.index)
        while idx:
            dist = [abs(m.at[i, "linha"] - pos[0]) + abs(m.at[i, "coluna"] - pos[1]) for i in idx]
            j = idx.pop(int(np.argmin(dist)))
            ordem.append(j)
            pos = (m.at[j, "linha"], m.at[j, "coluna"])
    m = m.loc[ordem].reset_index(drop=True)

    # Tempo estimado (deslocamento + trabalho)
    desloc = [0.0]
    for i in range(1, len(m)):
        d = abs(m.at[i, "linha"] - m.at[i - 1, "linha"]) + abs(m.at[i, "coluna"] - m.at[i - 1, "coluna"])
        desloc.append(d * TAMANHO_CELULA_M / VELOCIDADE_M_MIN)
    trabalho = m["mudas"] * MIN_POR_MUDA + m["litros"] / 100 * MIN_POR_100L + np.where(m["tipo"] == "inspecao", 5, 0)
    m["duracao_min"] = (np.array(desloc) + trabalho).round(1)

    m["ordem"] = range(1, len(m) + 1)
    m["id"] = [f"M{i:03d}" for i in m["ordem"]]

    # Segurança: com alerta ativo o robô fica recolhido
    nivel = analise.alerta.nivel
    if NIVEIS_ALERTA[nivel]["ordem"] >= NIVEIS_ALERTA["alerta"]["ordem"]:
        m["status"] = np.where(m["executor"] == "Defesa Civil", "urgente", "suspensa (alerta ativo)")
    else:
        m["status"] = np.where(m["executor"] == "robô", "pendente", "encaminhar")

    return m[colunas]


def resumo_missoes(missoes: pd.DataFrame) -> dict:
    if missoes.empty:
        return {
            "total": 0,
            "plantio": 0,
            "irrigacao": 0,
            "inspecao": 0,
            "mudas": 0,
            "litros": 0.0,
            "viagens": 0,
            "horas": 0.0,
            "suspensas": 0,
        }
    robo = missoes[missoes["executor"] == "robô"]
    viagens = int(np.ceil(robo["mudas"].sum() / CAPACIDADE_MUDAS) + np.ceil(robo["litros"].sum() / CAPACIDADE_AGUA_L))
    return {
        "total": len(missoes),
        "plantio": int((missoes["tipo"] == "plantio").sum()),
        "irrigacao": int((missoes["tipo"] == "irrigacao").sum()),
        "inspecao": int((missoes["tipo"] == "inspecao").sum()),
        "mudas": int(missoes["mudas"].sum()),
        "litros": float(missoes["litros"].sum()),
        "viagens": viagens,
        "horas": round(float(robo["duracao_min"].sum()) / 60, 1),
        "suspensas": int(missoes["status"].str.startswith("suspensa").sum()),
    }

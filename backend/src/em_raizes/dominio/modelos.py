"""Modelos e constantes do domínio (independentes da origem dos dados).

Um ``Mapeamento`` é o que um voo do drone entrega — hoje vem do simulador
(``em_raizes.fontes.simulador``); no futuro virá do drone real, com o mesmo formato.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import numpy as np
import pandas as pd

TAMANHO_CELULA_M = 10
POROSIDADE = 45.0  # umidade volumétrica (%) em que o solo fica saturado
MORADORES_POR_CASA = 2.8  # média de moradores por domicílio (Censo IBGE 2022 ~2,79)

CENARIOS: dict[str, dict] = {
    "seco": {
        "nome": "Tempo seco",
        "chuva_72h": 4.0,
        "previsao_24h": 0.0,
        "descricao": "Sem chuva relevante nos últimos 3 dias.",
    },
    "moderada": {
        "nome": "Chuva moderada",
        "chuva_72h": 45.0,
        "previsao_24h": 25.0,
        "descricao": "Chuva contínua, sem acumulado crítico.",
    },
    "forte": {
        "nome": "Chuva forte",
        "chuva_72h": 110.0,
        "previsao_24h": 60.0,
        "descricao": "Acumulado alto em 72 h e mais chuva prevista.",
    },
    "extrema": {
        "nome": "Tempestade extrema",
        "chuva_72h": 190.0,
        "previsao_24h": 120.0,
        "descricao": "Evento extremo: solo encharcado e chuva intensa prevista.",
    },
}

CENARIO_REAL = "real"  # chuva medida de verdade (Cemaden + previsão), ver fontes/chuva.py

TIPOS_SOLO = ["argiloso", "siltoso", "arenoso", "aterro", "rochoso"]
PONTO_DE_APOIO = "Escola Municipal na base do morro (ponto de apoio simulado)"


def setor_da_celula(linha: int, coluna: int, linhas: int, colunas: int) -> str:
    """Nome amigável do setor (3 x 3) para alertas: ex. 'Meio-Leste'."""
    faixa = ["Alto", "Meio", "Baixo"][min(linha * 3 // linhas, 2)]
    lado = ["Oeste", "Centro", "Leste"][min(coluna * 3 // colunas, 2)]
    return f"{faixa}-{lado}"


@dataclass
class Mapeamento:
    """Resultado de um voo do drone (simulado ou real)."""

    celulas: pd.DataFrame
    cenario: str
    chuva_72h: float
    previsao_24h: float
    semente: int
    linhas: int
    colunas: int
    voo_id: str
    data_voo: datetime
    nome_clima: str = ""  # usado quando a chuva é real (ex.: "Chuva real · Petrópolis/RJ")

    @property
    def nome_cenario(self) -> str:
        return self.nome_clima or CENARIOS.get(self.cenario, {}).get("nome", self.cenario)

    @property
    def area_m2(self) -> int:
        return self.linhas * self.colunas * TAMANHO_CELULA_M**2

    def grade(self, coluna: str) -> np.ndarray:
        """Devolve uma coluna do DataFrame como matriz (linhas x colunas)."""
        df = self.celulas.sort_values(["linha", "coluna"])
        return df[coluna].to_numpy().reshape(self.linhas, self.colunas)

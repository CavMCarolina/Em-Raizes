"""Simulador do voo do drone de mapeamento.

No MVP não existe drone físico. Este módulo gera, de forma reprodutível
(mesma semente = mesmo morro), os dados que o drone entregaria depois de
um voo sobre a encosta:

- relevo (modelo digital de elevação) e declividade;
- umidade do solo (sensor multiespectral/térmico simulado);
- cobertura vegetal (índice tipo NDVI, 0 a 1);
- ocupação (casas detectadas nas imagens);
- saídas simuladas de visão computacional: tipo de solo previsto com
  confiança, fissuras, erosão, entulho/aterro e vazamentos de água.

A área é uma grade de células de 10 m x 10 m. A linha 0 é o topo do morro
e a última linha é a base.
"""

from __future__ import annotations

from datetime import datetime, timedelta

import numpy as np
import pandas as pd

from ..dominio.modelos import (
    CENARIO_REAL,
    CENARIOS,
    MORADORES_POR_CASA,
    POROSIDADE,
    TAMANHO_CELULA_M,
    TIPOS_SOLO,
    Mapeamento,
    setor_da_celula,
)


def _suavizar(matriz: np.ndarray, passes: int = 2) -> np.ndarray:
    """Média móvel 3x3 simples (evita depender de scipy)."""
    m = matriz.astype(float)
    for _ in range(passes):
        p = np.pad(m, 1, mode="edge")
        m = (
            sum(p[1 + dy : 1 + dy + m.shape[0], 1 + dx : 1 + dx + m.shape[1]] for dy in (-1, 0, 1) for dx in (-1, 0, 1))
            / 9.0
        )
    return m


def _relevo(rng: np.random.Generator, linhas: int, colunas: int):
    y, x = np.mgrid[0:linhas, 0:colunas]
    yn = y / max(linhas - 1, 1)  # 0 = topo, 1 = base
    xn = x / max(colunas - 1, 1)

    elev = 130 * (1 - yn) ** 1.25
    elev += 10 * np.sin(xn * np.pi * 2 + rng.uniform(0, np.pi)) * (1 - yn)
    # talvegue: caminho natural da água descendo o morro
    centro = rng.uniform(0.3, 0.7)
    talvegue = np.exp(-((xn - centro) ** 2) / 0.006)
    elev -= 9 * talvegue * (0.4 + 0.6 * yn)
    elev += 5 * _suavizar(rng.normal(0, 1, (linhas, colunas)), passes=3)

    gy, gx = np.gradient(elev, TAMANHO_CELULA_M)
    declividade = np.degrees(np.arctan(np.hypot(gx, gy)))
    return elev, declividade, talvegue, yn


def simular_voo(
    cenario: str = "moderada",
    semente: int = 42,
    linhas: int = 24,
    colunas: int = 24,
    data_voo: datetime | None = None,
    voo_id: str | None = None,
    chuva_72h: float | None = None,
    previsao_24h: float | None = None,
    nome_clima: str = "",
) -> Mapeamento:
    """Gera os dados de um voo de mapeamento sobre uma encosta fictícia.

    Com ``cenario="real"`` a chuva vem dos parâmetros ``chuva_72h``/``previsao_24h``
    (medida de verdade); o morro, as casas e os sensores continuam simulados.
    """
    if cenario == CENARIO_REAL:
        if chuva_72h is None or previsao_24h is None:
            raise ValueError("Cenário 'real' exige chuva_72h e previsao_24h.")
    elif cenario not in CENARIOS:
        raise ValueError(f"Cenário desconhecido: {cenario!r}. Use um de {list(CENARIOS)} ou 'real'")
    if linhas < 6 or colunas < 6:
        raise ValueError("A grade precisa ter pelo menos 6 x 6 células.")

    rng = np.random.default_rng(semente)
    if cenario == CENARIO_REAL:
        cfg = {"chuva_72h": float(chuva_72h), "previsao_24h": float(previsao_24h)}
    else:
        cfg = CENARIOS[cenario]
    chuva_72h = cfg["chuva_72h"]

    elev, decl, talvegue, yn = _relevo(rng, linhas, colunas)

    # Ocupação: casas concentradas no meio e na base da encosta
    prob_casa = np.clip(0.75 * yn**0.8 - 0.08, 0, 0.75)
    prob_casa *= np.where(decl > 42, 0.4, 1.0)
    prob_casa *= 1 - 0.6 * talvegue  # menos casas exatamente na linha de drenagem
    tem_ocupacao = rng.random((linhas, colunas)) < prob_casa
    casas = np.where(tem_ocupacao, rng.integers(1, 4, (linhas, colunas)), 0)

    # Cobertura vegetal: mata no topo, pouca vegetação perto das casas
    cobertura = 0.85 - 0.55 * yn + 0.12 * _suavizar(rng.normal(0, 1, (linhas, colunas)))
    cobertura = np.where(casas > 0, cobertura * 0.35, cobertura)
    # cicatrizes de solo exposto (desmatamento, deslizamentos antigos)
    for _ in range(rng.integers(2, 5)):
        cy, cx = rng.integers(2, linhas - 2), rng.integers(2, colunas - 2)
        r = rng.integers(1, 3)
        cobertura[max(cy - r, 0) : cy + r + 1, max(cx - r, 0) : cx + r + 1] *= 0.15
    cobertura = np.clip(cobertura, 0.0, 0.98)

    # Tipo de solo
    solo = rng.choice(["argiloso", "siltoso", "arenoso"], size=(linhas, colunas), p=[0.5, 0.3, 0.2])
    solo = np.where((yn < 0.18) & (decl > 30) & (rng.random((linhas, colunas)) < 0.6), "rochoso", solo)
    solo = np.where((casas > 0) & (rng.random((linhas, colunas)) < 0.25), "aterro", solo)

    # Vazamentos de água/esgoto (câmera térmica) em parte das casas
    vazamento = (casas > 0) & (rng.random((linhas, colunas)) < 0.12)

    # Umidade do solo (%) — depende da chuva, da drenagem e de vazamentos
    umidade = 11 + 0.15 * chuva_72h
    umidade = umidade + 10 * talvegue + 6 * yn + np.where(vazamento, 8, 0)
    umidade = umidade - 3 * cobertura + rng.normal(0, 2.0, (linhas, colunas))
    umidade = np.where(solo == "rochoso", umidade * 0.6, umidade)
    umidade = np.clip(umidade, 4, POROSIDADE)

    # ---- Visão computacional (simulada) ----
    decl_n = np.clip((decl - 10) / 35, 0, 1)
    sat = umidade / POROSIDADE
    erosao = np.clip((1 - cobertura) * decl_n * (0.5 + 0.5 * min(chuva_72h / 150, 1)), 0, 1)
    erosao = np.clip(erosao + rng.normal(0, 0.05, (linhas, colunas)), 0, 1)
    prob_fissura = np.clip(0.9 * decl_n * sat * (1 - 0.6 * cobertura) + rng.normal(0, 0.06, (linhas, colunas)), 0, 1)
    fissuras = prob_fissura > 0.55

    # Classificador de solo por imagem: acerta ~88% das vezes
    confianca = np.clip(rng.normal(0.86, 0.07, (linhas, colunas)), 0.55, 0.99)
    erra = rng.random((linhas, colunas)) < 0.12
    solo_errado = rng.choice(TIPOS_SOLO, size=(linhas, colunas))
    solo_visao = np.where(erra, solo_errado, solo)
    confianca = np.where(erra, confianca * 0.75, confianca)

    ll, cc = np.mgrid[0:linhas, 0:colunas]
    df = pd.DataFrame(
        {
            "linha": ll.ravel(),
            "coluna": cc.ravel(),
            "celula": [f"L{r:02d}C{c:02d}" for r, c in zip(ll.ravel(), cc.ravel(), strict=True)],
            "elevacao_m": elev.ravel().round(1),
            "declividade_graus": decl.ravel().round(1),
            "umidade_pct": umidade.ravel().round(1),
            "cobertura_vegetal": cobertura.ravel().round(2),
            "tipo_solo": solo.ravel(),
            "casas": casas.ravel().astype(int),
            "vazamento": vazamento.ravel(),
            "erosao": erosao.ravel().round(2),
            "prob_fissura": prob_fissura.ravel().round(2),
            "fissura_detectada": fissuras.ravel(),
            "solo_visao": solo_visao.ravel(),
            "confianca_visao": confianca.ravel().round(2),
            "talvegue": (talvegue.ravel() > 0.5),
        }
    )
    df["moradores_estimados"] = (df["casas"] * MORADORES_POR_CASA).round(1)
    df["setor"] = [setor_da_celula(r, c, linhas, colunas) for r, c in zip(df["linha"], df["coluna"], strict=True)]

    data = data_voo or datetime.now().replace(second=0, microsecond=0)
    return Mapeamento(
        celulas=df,
        cenario=cenario,
        chuva_72h=chuva_72h,
        previsao_24h=cfg["previsao_24h"],
        semente=semente,
        linhas=linhas,
        colunas=colunas,
        voo_id=voo_id or f"VOO-{data:%Y%m%d-%H%M}-{semente:04d}",
        data_voo=data,
        nome_clima=nome_clima,
    )


def historico_chuva(mapa: Mapeamento, dias: int = 7) -> pd.DataFrame:
    """Chuva diária observada (pluviômetro simulado) + previsão de amanhã.

    Os 3 últimos dias somam exatamente ``mapa.chuva_72h``.
    """
    rng = np.random.default_rng(mapa.semente + 7)
    ultimos3 = rng.dirichlet([2, 2, 3]) * mapa.chuva_72h
    anteriores = rng.gamma(1.2, mapa.chuva_72h / 12 + 1.5, max(dias - 3, 0))
    valores = np.concatenate([anteriores, ultimos3])
    hoje = mapa.data_voo.date()
    datas = [hoje - timedelta(days=dias - 1 - i) for i in range(dias)]
    df = pd.DataFrame({"data": datas, "chuva_mm": valores.round(1), "tipo": "observada"})
    previsao = pd.DataFrame({"data": [hoje + timedelta(days=1)], "chuva_mm": [mapa.previsao_24h], "tipo": ["prevista"]})
    return pd.concat([df, previsao], ignore_index=True)


def imagem_aerea(mapa: Mapeamento, px: int = 10) -> np.ndarray:
    """Gera uma "foto aérea" sintética (RGB uint8) a partir dos dados do voo.

    Serve para a aba de visão computacional: mostra o que o drone "viu".
    """
    rng = np.random.default_rng(mapa.semente + 99)
    L, C = mapa.linhas, mapa.colunas
    cob = np.kron(mapa.grade("cobertura_vegetal"), np.ones((px, px)))
    elev = np.kron(mapa.grade("elevacao_m"), np.ones((px, px)))
    elev = _suavizar(elev, passes=4)
    ero = np.kron(mapa.grade("erosao"), np.ones((px, px)))

    cor_solo = {
        "argiloso": (150, 85, 50),
        "siltoso": (165, 120, 80),
        "arenoso": (205, 175, 120),
        "aterro": (120, 110, 100),
        "rochoso": (130, 130, 125),
    }
    solo = mapa.grade("tipo_solo")
    base_solo = np.zeros((L * px, C * px, 3))
    for r in range(L):
        for c in range(C):
            base_solo[r * px : (r + 1) * px, c * px : (c + 1) * px] = cor_solo[solo[r, c]]

    textura = rng.normal(0, 1, (L * px, C * px))
    cob_t = np.clip(cob + 0.15 * textura, 0, 1)[..., None]
    verde = np.stack([45 + 20 * textura, 110 + 30 * textura, 40 + 10 * textura], axis=-1)
    img = cob_t * verde + (1 - cob_t) * base_solo
    img *= 1 - 0.35 * ero[..., None]  # sulcos de erosão mais escuros

    # sombreamento do relevo (luz vindo do noroeste)
    gy, gx = np.gradient(elev)
    sombra = np.clip(1 + 0.08 * (gx + gy), 0.7, 1.15)
    img *= sombra[..., None]

    # telhados das casas
    casas = mapa.grade("casas")
    cores_telhado = [(190, 90, 60), (170, 170, 170), (210, 120, 70), (140, 140, 150)]
    for r in range(L):
        for c in range(C):
            for _ in range(int(casas[r, c])):
                h, w = rng.integers(px // 3, px // 2 + 2), rng.integers(px // 3, px // 2 + 2)
                y0 = r * px + rng.integers(0, px - h + 1)
                x0 = c * px + rng.integers(0, px - w + 1)
                img[y0 : y0 + h, x0 : x0 + w] = cores_telhado[rng.integers(len(cores_telhado))]

    return np.clip(img, 0, 255).astype(np.uint8)


class MundoSimulado:
    """O "mundo" que o drone simulado observa.

    Guarda o morro (semente), o clima (cenário) e o efeito acumulado do trabalho
    do robô: mudas plantadas aumentam a cobertura vegetal, a irrigação aumenta a
    umidade e as inspeções confirmam ou descartam fissuras. Os efeitos só
    aparecem no PRÓXIMO voo — como na vida real, é preciso medir de novo.
    """

    GANHO_COBERTURA_PLANTIO = 0.25

    def __init__(self, semente: int = 42, cenario: str = "forte", tamanho: int = 24, chuva_real: dict | None = None):
        if cenario not in CENARIOS and cenario != CENARIO_REAL:
            raise ValueError(f"Cenário desconhecido: {cenario!r}")
        if cenario == CENARIO_REAL and not chuva_real:
            raise ValueError("Cenário 'real' exige a leitura de chuva (chuva_real).")
        self.semente = semente
        self.cenario = cenario
        self.chuva_real: dict | None = dict(chuva_real) if chuva_real else None
        self.tamanho = tamanho
        self.voos = 0
        self.delta_cobertura: dict[str, float] = {}
        self.delta_umidade: dict[str, float] = {}
        self.fissuras_verificadas: dict[str, bool] = {}

    def mudar_clima(self, cenario: str, chuva_real: dict | None = None) -> None:
        if cenario not in CENARIOS and cenario != CENARIO_REAL:
            raise ValueError(f"Cenário desconhecido: {cenario!r}")
        if cenario == CENARIO_REAL:
            if not chuva_real:
                raise ValueError("Cenário 'real' exige a leitura de chuva (chuva_real).")
            self.chuva_real = dict(chuva_real)
        self.cenario = cenario
        self.delta_umidade.clear()  # chuva nova "apaga" a irrigação anterior

    def atualizar_chuva_real(self, chuva_real: dict) -> None:
        """Nova leitura dos pluviômetros (sem trocar de cenário). Chuva a mais apaga a irrigação."""
        antes = (self.chuva_real or {}).get("chuva_72h", 0.0)
        self.chuva_real = dict(chuva_real)
        if chuva_real["chuva_72h"] > antes + 1:
            self.delta_umidade.clear()

    @property
    def chuva_atual(self) -> tuple[float, float]:
        """(chuva 72 h, previsão 24 h) do clima atual, simulado ou real."""
        if self.cenario == CENARIO_REAL and self.chuva_real:
            return float(self.chuva_real["chuva_72h"]), float(self.chuva_real["previsao_24h"])
        c = CENARIOS[self.cenario]
        return float(c["chuva_72h"]), float(c["previsao_24h"])

    def registrar_plantio(self, celulas: list[str]) -> None:
        for c in celulas:
            self.delta_cobertura[c] = min(self.delta_cobertura.get(c, 0.0) + self.GANHO_COBERTURA_PLANTIO, 0.9)

    def registrar_irrigacao(self, litros_por_celula: dict[str, float]) -> None:
        area = TAMANHO_CELULA_M**2
        for c, litros in litros_por_celula.items():
            # mesma conta da recomendação: faixas plantadas (30%) até 5 cm de profundidade
            ganho_pct = litros / (area * 0.3 * 0.05 * 1000) * 100
            self.delta_umidade[c] = self.delta_umidade.get(c, 0.0) + ganho_pct

    def registrar_inspecao(self, resultado: dict[str, bool]) -> None:
        self.fissuras_verificadas.update(resultado)

    def voar(self, data: datetime | None = None) -> Mapeamento:
        self.voos += 1
        data = data or datetime.now().replace(microsecond=0)
        mapa = simular_voo(
            self.cenario,
            self.semente,
            self.tamanho,
            self.tamanho,
            data_voo=data,
            voo_id=f"VOO-{self.voos:04d}-{data:%Y%m%d-%H%M%S}",
            **(
                {
                    "chuva_72h": self.chuva_real["chuva_72h"],
                    "previsao_24h": self.chuva_real["previsao_24h"],
                    "nome_clima": self.chuva_real.get("nome", "Chuva real"),
                }
                if self.cenario == CENARIO_REAL and self.chuva_real
                else {}
            ),
        )
        df = mapa.celulas
        if self.delta_cobertura:
            ganho = df["celula"].map(self.delta_cobertura).fillna(0.0)
            df["cobertura_vegetal"] = (df["cobertura_vegetal"] + ganho).clip(0, 0.98).round(2)
            df["erosao"] = (df["erosao"] * (1 - ganho)).clip(0, 1).round(2)
        if self.delta_umidade:
            ganho = df["celula"].map(self.delta_umidade).fillna(0.0)
            df["umidade_pct"] = (df["umidade_pct"] + ganho).clip(0, POROSIDADE).round(1)
        for celula, confirmada in self.fissuras_verificadas.items():
            m = df["celula"] == celula
            df.loc[m, "prob_fissura"] = 0.95 if confirmada else 0.1
            df.loc[m, "fissura_detectada"] = confirmada
        return mapa

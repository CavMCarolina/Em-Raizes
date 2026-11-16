import numpy as np
import pandas as pd
import pytest

from em_raizes.dominio.missoes import gerar_missoes, resumo_missoes
from em_raizes.dominio.risco import NIVEIS_ALERTA, analisar, explicar_celula, indice_risco
from em_raizes.fontes.simulador import CENARIOS, POROSIDADE, historico_chuva, imagem_aerea, simular_voo


def test_simulacao_reprodutivel_pela_semente():
    a = simular_voo("moderada", 7).celulas
    b = simular_voo("moderada", 7).celulas
    c = simular_voo("moderada", 8).celulas
    pd.testing.assert_frame_equal(a, b)
    assert not a["elevacao_m"].equals(c["elevacao_m"])


def test_valores_fisicamente_plausiveis():
    df = simular_voo("extrema", 1).celulas
    assert df["declividade_graus"].between(0, 90).all()
    assert df["umidade_pct"].between(0, POROSIDADE).all()
    assert df["cobertura_vegetal"].between(0, 1).all()
    assert (df["casas"] >= 0).all()
    assert len(df) == 24 * 24


def test_cenario_invalido_da_erro_claro():
    with pytest.raises(ValueError, match="Cenário desconhecido"):
        simular_voo("granizo")


def test_mais_chuva_aumenta_risco_medio():
    medias = [analisar(simular_voo(c, 42)).estatisticas["risco_medio"] for c in CENARIOS]
    assert medias == sorted(medias)


def test_niveis_de_alerta_por_cenario():
    nivel = {c: analisar(simular_voo(c, 42)).alerta.nivel for c in CENARIOS}
    assert nivel["seco"] == "normal"
    assert nivel["extrema"] == "alerta_maximo"
    ordem = [NIVEIS_ALERTA[nivel[c]]["ordem"] for c in CENARIOS]
    assert ordem == sorted(ordem)


def test_declividade_e_umidade_elevam_o_indice():
    base = pd.DataFrame(
        {
            "declividade_graus": [15.0, 40.0, 40.0],
            "umidade_pct": [15.0, 15.0, 44.0],
            "cobertura_vegetal": [0.5, 0.5, 0.5],
            "tipo_solo": ["argiloso"] * 3,
            "prob_fissura": [0.1] * 3,
            "erosao": [0.1] * 3,
            "vazamento": [False] * 3,
        }
    )
    r = indice_risco(base, chuva_mm=50)
    assert r[0] < r[1] < r[2]


def test_previsao_24h_nao_reduz_risco_com_chuva_prevista(analise_forte):
    df = analise_forte.df
    assert (df["umidade_24h"] >= df["umidade_pct"]).all()
    assert df["risco_24h"].mean() > df["risco"].mean()


def test_nunca_irriga_encosta_molhada_ou_com_chuva_prevista():
    for c in CENARIOS:
        a = analisar(simular_voo(c, 3))
        irr = a.df[a.df["precisa_irrigar"]]
        assert irr["classe_risco"].isin(["baixo", "moderado"]).all()
        assert (irr["casas"] == 0).all()
        if a.mapa.previsao_24h >= 10:
            assert irr.empty


def test_plantio_so_em_areas_sem_casas_e_sem_rocha(analise_forte):
    p = analise_forte.df[analise_forte.df["plantio_recomendado"]]
    assert not p.empty
    assert (p["casas"] == 0).all()
    assert (p["tipo_solo"] != "rochoso").all()


def test_evacuacao_lista_somente_celulas_com_casas():
    a = analisar(simular_voo("extrema", 42))
    ev = a.df[a.df["celula"].isin(a.alerta.celulas_evacuar)]
    assert len(ev) > 0
    assert (ev["casas"] > 0).all()
    assert a.alerta.pessoas_em_risco == pytest.approx(ev["moradores_estimados"].sum(), rel=1e-6)


def test_explicacao_soma_fatores(analise_forte):
    cel = analise_forte.df.iloc[100]["celula"]
    info = explicar_celula(analise_forte, cel)
    assert set(info["contribuicao_pts"]) == {"declividade", "saturacao", "chuva", "vegetacao", "solo", "sinais"}
    with pytest.raises(KeyError):
        explicar_celula(analise_forte, "L99C99")


def test_missoes_suspensas_com_alerta_e_liberadas_no_seco():
    m_ext = gerar_missoes(analisar(simular_voo("extrema", 42)))
    robo = m_ext[m_ext["executor"] != "Defesa Civil"]
    assert robo["status"].str.startswith("suspensa").all()

    m_seco = gerar_missoes(analisar(simular_voo("seco", 42)))
    assert (m_seco.loc[m_seco["executor"] == "robô", "status"] == "pendente").all()
    assert (m_seco["tipo"] == "irrigacao").any()
    r = resumo_missoes(m_seco)
    assert r["viagens"] >= 1 and r["horas"] > 0


def test_rota_comeca_pelas_missoes_de_alta_prioridade():
    m = gerar_missoes(analisar(simular_voo("seco", 42)))
    ordem_prioridade = m["prioridade"].map({"alta": 0, "média": 1, "baixa": 2}).to_numpy()
    assert (np.diff(ordem_prioridade) >= 0).all()


def test_historico_de_chuva_bate_com_cenario(analise_forte):
    h = historico_chuva(analise_forte.mapa)
    obs = h[h["tipo"] == "observada"]
    assert obs["chuva_mm"].tail(3).sum() == pytest.approx(analise_forte.mapa.chuva_72h, abs=0.2)
    assert h.iloc[-1]["chuva_mm"] == analise_forte.mapa.previsao_24h


def test_imagem_aerea_tem_formato_rgb(analise_forte):
    img = imagem_aerea(analise_forte.mapa, px=6)
    assert img.shape == (24 * 6, 24 * 6, 3)
    assert img.dtype == np.uint8

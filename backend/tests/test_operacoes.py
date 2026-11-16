from datetime import datetime, timedelta

import pytest

from em_raizes.fontes.simulador import MundoSimulado
from em_raizes.operacoes.central import DRONE, ROBO, CentralOperacoes, ComandoRecusado


class Relogio:
    def __init__(self):
        self.t = datetime(2026, 11, 10, 9, 0, 0).astimezone()

    def __call__(self):
        return self.t

    def avancar(self, segundos: float):
        self.t += timedelta(seconds=segundos)


def nova_central(cenario="seco", semente=42):
    rel = Relogio()
    return CentralOperacoes(MundoSimulado(semente=semente, cenario=cenario), relogio=rel), rel


def test_central_inicia_com_voo_e_frota_na_base():
    c, _ = nova_central()
    e = c.estado()
    assert e["ultimo_voo"]["voo_id"].startswith("VOO-0001")
    assert {d.status for d in e["dispositivos"]} == {"na_base"}
    assert e["alerta"]["nivel"] == "normal"


def test_voo_do_drone_progride_e_gera_novo_mapeamento():
    c, rel = nova_central()
    cmd = c.enviar_drone()
    assert cmd.status == "em_execucao" and c.dispositivos[DRONE].status == "em_missao"
    rel.avancar(6)
    assert 40 <= c.comando(cmd.id).progresso < 100 or c.estado() and c.comando(cmd.id).progresso >= 40
    rel.avancar(10)
    e = c.estado()
    feito = c.comando(cmd.id)
    assert feito.status == "concluido" and feito.resultado["voo_id"].startswith("VOO-0002")
    assert e["dispositivos"][0].status == "na_base"


def test_drone_ocupado_recusa_segundo_voo_com_codigo():
    c, _ = nova_central()
    c.enviar_drone()
    with pytest.raises(ComandoRecusado) as e:
        c.enviar_drone()
    assert e.value.comando.codigo_recusa == "dispositivo_ocupado"
    assert e.value.comando.status == "recusado"


def test_idempotencia_devolve_o_mesmo_comando():
    c, _ = nova_central()
    a = c.enviar_drone(chave="clique-123")
    b = c.enviar_drone(chave="clique-123")
    assert a.id == b.id
    assert len([x for x in c.comandos if x.tipo == "voo_drone"]) == 1


def test_bateria_baixa_bloqueia_drone_e_recarrega_na_base():
    c, rel = nova_central()
    c.dispositivos[DRONE].bateria = 20
    with pytest.raises(ComandoRecusado) as e:
        c.enviar_drone()
    assert e.value.comando.codigo_recusa == "bateria_baixa"
    rel.avancar(30)
    c.atualizar()
    assert c.dispositivos[DRONE].bateria >= 30
    assert c.enviar_drone().status == "em_execucao"


def test_plantio_padrao_usa_celulas_recomendadas_e_aparece_no_proximo_voo():
    c, rel = nova_central()
    cmd = c.enviar_robo("plantio")
    assert cmd.celulas and cmd.parametros["mudas"] > 0
    antes = c.analise.df.set_index("celula").loc[cmd.celulas, "cobertura_vegetal"]
    rel.avancar(cmd.duracao_s + 1)
    c.atualizar()
    assert c.comando(cmd.id).status == "concluido"
    # antes do novo voo o mapa não muda...
    assert (c.analise.df.set_index("celula").loc[cmd.celulas, "cobertura_vegetal"] == antes).all()
    # ...e as mesmas células não são replantadas
    seguinte = c.enviar_robo("plantio")
    assert not set(seguinte.celulas) & set(cmd.celulas)
    rel.avancar(seguinte.duracao_s + 1)
    voo = c.enviar_drone()
    rel.avancar(voo.duracao_s + 1)
    c.atualizar()
    depois = c.analise.df.set_index("celula").loc[cmd.celulas, "cobertura_vegetal"]
    assert (depois > antes).all()


def test_validacao_de_celulas_explica_o_que_ficou_de_fora():
    c, _ = nova_central()
    df = c.analise.df
    com_casa = df[df["casas"] > 0].iloc[0]["celula"]
    boa = c._alvos_padrao("plantio")[0][0]
    cmd = c.enviar_robo("plantio", [boa, com_casa, "L99C99"])
    assert cmd.celulas == [boa]
    assert "casas" in cmd.ignoradas[com_casa]
    assert "não existe" in cmd.ignoradas["L99C99"]


def test_sem_alvos_validos_recusa():
    c, _ = nova_central()
    com_casa = c.analise.df[c.analise.df["casas"] > 0].iloc[0]["celula"]
    with pytest.raises(ComandoRecusado) as e:
        c.enviar_robo("irrigacao", [com_casa])
    assert e.value.comando.codigo_recusa == "sem_alvos_validos"


def test_robo_recusado_com_alerta_ativo_mas_drone_voa():
    c, _ = nova_central(cenario="extrema")
    with pytest.raises(ComandoRecusado) as e:
        c.enviar_robo("plantio")
    assert e.value.comando.codigo_recusa == "alerta_ativo"
    assert c.enviar_drone().status == "em_execucao"
    assert c.estado()["robo_liberado"] is False


def test_clima_piora_voo_dispara_alerta_e_cancela_robo():
    c, rel = nova_central(cenario="seco")
    robo = c.enviar_robo("plantio")
    c.mudar_clima("extrema")
    rec = {r["acao"] for r in c.estado()["recomendacoes"]}
    assert "voo_drone" in rec
    voo = c.enviar_drone()
    rel.avancar(voo.duracao_s + 0.5)
    c.atualizar()
    assert c.nivel_alerta == "alerta_maximo"
    assert c.comando(robo.id).status == "cancelado"
    eventos = [e.tipo for e in c.listar_eventos()]
    assert "alerta_mudou" in eventos and "clima_mudou" in eventos


def test_parada_de_emergencia_cancela_tudo_e_bloqueia_ate_liberar():
    c, _ = nova_central()
    voo = c.enviar_drone()
    robo = c.enviar_robo("plantio")
    parada = c.parada_emergencia()
    assert set(parada.resultado["comandos_cancelados"]) == {voo.id, robo.id}
    assert {d.status for d in c.dispositivos.values()} == {"parado"}
    with pytest.raises(ComandoRecusado) as e:
        c.enviar_drone()
    assert e.value.comando.codigo_recusa == "frota_parada"
    c.liberar_frota()
    assert c.enviar_drone().status == "em_execucao"


def test_recolher_robo_cancela_missao():
    c, _ = nova_central()
    m = c.enviar_robo("plantio")
    r = c.recolher_robo()
    assert r.resultado["comando_cancelado"] == m.id
    assert c.comando(m.id).status == "cancelado"
    assert c.dispositivos[ROBO].status == "na_base"


def test_inspecao_confirma_ou_descarta_fissuras():
    c, rel = nova_central(cenario="seco")
    df = c.analise.df
    sem_casa = df.index[df["casas"] == 0][:3]
    df.loc[sem_casa, ["fissura_detectada", "prob_fissura"]] = [True, 0.6]  # simula detecções da visão
    cmd = c.enviar_robo("inspecao")
    assert len(cmd.celulas) == 3
    rel.avancar(cmd.duracao_s + 1)
    c.atualizar()
    res = c.comando(cmd.id).resultado
    assert set(res["confirmadas"]) | set(res["descartadas"]) == set(cmd.celulas)
    assert not set(c._alvos_padrao("inspecao")[0]) & set(cmd.celulas)


def test_eventos_incrementais_para_polling():
    c, _ = nova_central()
    ultimo = c.estado()["ultimo_evento_id"]
    c.enviar_drone()
    novos = c.listar_eventos(desde=ultimo)
    assert novos and all(e.id > ultimo for e in novos)
    assert novos[-1].origem == "admin"

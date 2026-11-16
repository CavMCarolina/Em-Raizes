from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from em_raizes.api.main import criar_app
from em_raizes.config import Config
from em_raizes.fontes.simulador import MundoSimulado
from em_raizes.ia.conhecimento import BaseConhecimento
from em_raizes.ia.guardiao import Guardiao
from em_raizes.ia.llm import ClienteLLM
from em_raizes.operacoes.central import CentralOperacoes

SENHA = "senha-de-teste-123"


class Relogio:
    def __init__(self):
        self.t = datetime(2026, 11, 10, 9, 0).astimezone()

    def __call__(self):
        return self.t


@pytest.fixture
def ctx():
    rel = Relogio()
    cfg = Config(segredo_jwt="segredo-teste-" + "x" * 32, admin_senha=SENHA, origens_cors=[])
    central = CentralOperacoes(MundoSimulado(semente=42, cenario="seco"), relogio=rel)
    guardiao = Guardiao(ClienteLLM(api_key=""), BaseConhecimento())
    cliente = TestClient(criar_app(cfg, central, guardiao))
    return cliente, rel, central


def token(cliente) -> dict:
    r = cliente.post("/api/auth/login", json={"usuario": "admin", "senha": SENHA})
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_rotas_publicas(ctx):
    cliente, _, _ = ctx
    assert cliente.get("/api/saude").json()["status"] == "ok"
    info = cliente.get("/api/info").json()
    assert info["login_habilitado"] and info["dados_simulados"]


def test_saude_informa_o_commit_em_execucao(ctx, monkeypatch):
    cliente, _, _ = ctx
    monkeypatch.delenv("EM_RAIZES_COMMIT", raising=False)
    monkeypatch.delenv("RENDER_GIT_COMMIT", raising=False)
    assert cliente.get("/api/saude").json()["commit"] is None
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abc123")  # deploy no Render
    assert cliente.get("/api/saude").json()["commit"] == "abc123"
    monkeypatch.setenv("EM_RAIZES_COMMIT", "def456")  # imagem construída pelo CI tem prioridade
    assert cliente.get("/api/saude").json()["commit"] == "def456"


def test_sem_autenticacao_401_e_senha_errada(ctx):
    cliente, _, _ = ctx
    r = cliente.get("/api/estado")
    assert r.status_code == 401 and r.json()["detail"]["codigo"] == "nao_autenticado"
    r = cliente.post("/api/auth/login", json={"usuario": "admin", "senha": "errada"})
    assert r.status_code == 401


def test_token_invalido(ctx):
    cliente, _, _ = ctx
    r = cliente.get("/api/estado", headers={"Authorization": "Bearer abc.def.ghi"})
    assert r.status_code == 401 and r.json()["detail"]["codigo"] == "token_invalido"


def test_estado_e_mapa(ctx):
    cliente, _, _ = ctx
    h = token(cliente)
    est = cliente.get("/api/estado", headers=h).json()
    assert {d["id"] for d in est["dispositivos"]} == {"DRN-01", "ROB-01"}
    mapa = cliente.get("/api/mapa", headers=h).json()
    assert len(mapa["celulas"]) == mapa["linhas"] * mapa["colunas"]
    cel = mapa["celulas"][0]["celula"]
    det = cliente.get(f"/api/mapa/celulas/{cel}", headers=h).json()
    assert set(det["explicacao"]["contribuicao_pts"]) >= {"declividade", "saturacao"}
    png = cliente.get("/api/mapa/imagem.png", headers=h)
    assert png.headers["content-type"] == "image/png" and png.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_fluxo_drone_com_origem_admin(ctx):
    cliente, rel, _ = ctx
    h = token(cliente)
    r = cliente.post("/api/comandos/drone/voo", headers=h)
    assert r.status_code == 201 and r.json()["origem"] == "admin" and r.json()["status"] == "em_execucao"
    cmd_id = r.json()["id"]
    ocupado = cliente.post("/api/comandos/drone/voo", headers=h)
    assert ocupado.status_code == 409 and ocupado.json()["codigo_recusa"] == "dispositivo_ocupado"
    rel.t += timedelta(seconds=20)
    feito = next(c for c in cliente.get("/api/comandos", headers=h).json() if c["id"] == cmd_id)
    assert feito["status"] == "concluido" and feito["resultado"]["voo_id"].startswith("VOO-0002")


def test_idempotencia_evita_comando_duplicado(ctx):
    cliente, _, central = ctx
    h = token(cliente) | {"Idempotency-Key": "clique-plantio-1"}
    a = cliente.post("/api/comandos/robo/plantio", headers=h, json={})
    b = cliente.post("/api/comandos/robo/plantio", headers=h, json={})
    assert a.status_code == 201 and b.status_code == 200
    assert b.headers["Idempotency-Replayed"] == "true" and a.json()["id"] == b.json()["id"]
    assert a.json()["origem"] == "admin"
    assert len([c for c in central.comandos if c.tipo == "plantio"]) == 1


def test_robo_com_celulas_explicitas_e_missao_invalida(ctx):
    cliente, _, central = ctx
    h = token(cliente)
    df = central.analise.df
    com_casa = df[df["casas"] > 0].iloc[0]["celula"]
    r = cliente.post("/api/comandos/robo/irrigacao", headers=h, json={"celulas": [com_casa]})
    assert r.status_code == 409 and r.json()["codigo_recusa"] == "sem_alvos_validos"
    assert com_casa in r.json()["ignoradas"]
    assert cliente.post("/api/comandos/robo/voar", headers=h).status_code == 404


def test_emergencia_clima_e_eventos(ctx):
    cliente, _, _ = ctx
    h = token(cliente)
    ultimo = cliente.get("/api/estado", headers=h).json()["ultimo_evento_id"]
    assert cliente.post("/api/simulacao/clima", headers=h, json={"cenario": "extrema"}).status_code == 201
    assert cliente.post("/api/simulacao/clima", headers=h, json={"cenario": "granizo"}).status_code == 409
    assert cliente.post("/api/comandos/emergencia", headers=h).status_code == 201
    bloqueado = cliente.post("/api/comandos/drone/voo", headers=h)
    assert bloqueado.json()["codigo_recusa"] == "frota_parada"
    assert cliente.post("/api/comandos/liberar", headers=h).status_code == 201
    tipos = [e["tipo"] for e in cliente.get(f"/api/eventos?desde={ultimo}", headers=h).json()]
    assert {"clima_mudou", "frota_parada", "frota_liberada", "comando_recusado"} <= set(tipos)
    recs = cliente.get("/api/estado", headers=h).json()["recomendacoes"]
    assert recs[0]["acao"] == "voo_drone" and recs[0]["prioridade"] == "alta"


def test_ia_em_modo_offline(ctx):
    cliente, _, central = ctx
    h = token(cliente)
    r = cliente.post("/api/ia/chat", headers=h, json={"pergunta": "Como envio o drone?"}).json()
    assert r["modo"] == "offline" and r["fontes"]
    assert "199" in cliente.post("/api/ia/sms", headers=h).json()["texto"]
    plano = cliente.post("/api/ia/plano", headers=h).json()["plano"]
    assert plano["nivel_alerta"] == central.nivel_alerta
    cel = central.analise.df.iloc[0]["celula"]
    assert "Risco" in cliente.post(f"/api/ia/explicar/{cel}", headers=h).json()["texto"]


def test_login_desativado_sem_senha():
    cfg = Config(segredo_jwt="s" * 40, admin_senha="", origens_cors=[])
    central = CentralOperacoes(MundoSimulado(cenario="seco"))
    cliente = TestClient(criar_app(cfg, central, Guardiao(ClienteLLM(api_key=""), BaseConhecimento())))
    r = cliente.post("/api/auth/login", json={"usuario": "admin", "senha": "qualquer"})
    assert r.status_code == 503 and r.json()["detail"]["codigo"] == "login_desativado"

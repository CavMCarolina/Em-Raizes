"""Chuva real (Cemaden + Open-Meteo), notificações push e análise de foto com IA."""

import base64
import json
from datetime import UTC, datetime, timedelta

import openai
import pytest
from conftest import SDKFalso, erro_http
from fastapi.testclient import TestClient

from em_raizes.api.main import criar_app
from em_raizes.config import Config
from em_raizes.fontes.chuva import Cidade, FonteChuvaReal, faixa_da_chuva, resumir_cemaden, resumir_open_meteo
from em_raizes.fontes.simulador import MundoSimulado
from em_raizes.ia.conhecimento import BaseConhecimento
from em_raizes.ia.guardiao import Guardiao
from em_raizes.ia.llm import ClienteLLM
from em_raizes.ia.visao import AnaliseFoto, ErroFoto, analisar_foto, decodificar_imagem
from em_raizes.operacoes.central import CentralOperacoes, ComandoRecusado
from em_raizes.operacoes.modelos import Evento
from em_raizes.operacoes.notificacoes import ServicoNotificacoes, deve_notificar, gerar_chave_privada

AGORA = datetime(2026, 11, 10, 21, 30, tzinfo=UTC)
CIDADE = Cidade()


def estacao(id_, acc72, acc24=0.5, horas_atras=0.5, ibge=3303906):
    hora = (AGORA - timedelta(hours=horas_atras)).strftime("%d/%m/%y %H:%M")
    return {
        "idestacao": id_,
        "codibge": ibge,
        "nomeestacao": f"E{id_}",
        "datahoraUltimovalor": hora,
        "acc72hr": acc72,
        "acc24hr": acc24,
    }


def open_meteo(chuva_por_hora=1.0, inicio=datetime(2026, 11, 10, 0, 0)):
    horas = [inicio + timedelta(hours=h) for h in range(-24 * 6, 48)]
    dias = sorted({h.date() for h in horas})
    return {
        "hourly": {
            "time": [h.strftime("%Y-%m-%dT%H:%M") for h in horas],
            "precipitation": [chuva_por_hora] * len(horas),
        },
        "daily": {"time": [d.isoformat() for d in dias], "precipitation_sum": [24 * chuva_por_hora] * len(dias)},
    }


# ------------------------------------------------------------------ chuva real


def test_cemaden_ignora_estacoes_antigas_e_usa_percentil_75():
    dados = [
        estacao(1, 10),
        estacao(2, 20),
        estacao(3, 30),
        estacao(4, 200, horas_atras=48),
        estacao(5, "-"),
        estacao(6, 40),
        estacao(7, 999, ibge=1),
    ]
    r = resumir_cemaden(dados, CIDADE, agora=AGORA)
    assert r["estacoes_validas"] == 4  # sem a antiga, a sem dado e a de outra cidade
    assert r["chuva_72h"] == pytest.approx(32.5)  # percentil 75 de 10, 20, 30, 40


def test_cemaden_estacao_especifica_e_erro_sem_dados():
    dados = [estacao(1, 10), estacao(2, 55.5)]
    r = resumir_cemaden(dados, Cidade(codigo_estacao=2), agora=AGORA)
    assert r["chuva_72h"] == 55.5 and r["estacao"] == "E2"
    with pytest.raises(ValueError, match="Nenhum pluviômetro"):
        resumir_cemaden([estacao(1, 10, horas_atras=30)], CIDADE, agora=AGORA)


def test_open_meteo_soma_as_proximas_24h():
    previsao, diario = resumir_open_meteo(open_meteo(0.5), agora_local=datetime(2026, 11, 10, 15, 20))
    assert previsao == 12.0
    assert diario[-1]["tipo"] == "prevista" and len([d for d in diario if d["tipo"] == "observada"]) == 7


def test_open_meteo_usa_o_fuso_da_resposta_mesmo_com_servidor_em_utc():
    # 10/11 às 21h30 em Brasília = 11/11 às 00h30 UTC (relógio de um container Docker)
    dados = open_meteo(0.0)
    horas = [datetime.fromisoformat(h) for h in dados["hourly"]["time"]]
    dados["hourly"]["precipitation"] = [1.0 if h.date().day == 10 and h.hour >= 21 else 0.0 for h in horas]
    dados["utc_offset_seconds"] = -3 * 3600
    previsao, diario = resumir_open_meteo(dados, agora_utc=datetime(2026, 11, 11, 0, 30, tzinfo=UTC))
    assert previsao == 3.0  # 21h, 22h e 23h de 10/11 estão nas próximas 24 h
    assert diario[-1] == {"data": "2026-11-11", "chuva_mm": 0.0, "tipo": "prevista"}
    assert [d["data"] for d in diario if d["tipo"] == "observada"][-1] == "2026-11-10"


def test_fonte_real_mantem_ultima_leitura_se_a_rede_falhar():
    agora = datetime.now(UTC)
    hora = (agora - timedelta(minutes=10)).strftime("%d/%m/%y %H:%M")
    cemaden = [
        {
            "idestacao": 1,
            "codibge": 3303906,
            "nomeestacao": "E1",
            "datahoraUltimovalor": hora,
            "acc72hr": 80.0,
            "acc24hr": 5.0,
        }
    ]
    falhar = {"agora": False}

    def baixar(url, timeout):
        if falhar["agora"]:
            raise OSError("sem internet")
        return (
            cemaden
            if "cemaden" in url
            else open_meteo(1.0, inicio=datetime.now().replace(minute=0, second=0, microsecond=0))
        )

    fonte = FonteChuvaReal(CIDADE, baixar=baixar)
    primeira = fonte.atualizar()
    assert primeira.ok and primeira.chuva_72h == 80.0 and primeira.previsao_24h == 24.0
    falhar["agora"] = True
    segunda = fonte.atualizar()
    assert segunda is fonte.ultima and fonte.ultimo_erro.startswith("OSError")


def test_faixa_da_chuva():
    assert [faixa_da_chuva(5, 0), faixa_da_chuva(40, 5), faixa_da_chuva(105, 4), faixa_da_chuva(10, 120)] == [
        "seco",
        "moderada",
        "forte",
        "extrema",
    ]


class ChuvaFalsa(FonteChuvaReal):
    """Fonte de chuva real controlada pelo teste."""

    def __init__(self, chuva_72h=20.0, previsao=2.0, ok=True):
        super().__init__(CIDADE)
        self.valores, self.ok = (chuva_72h, previsao), ok

    def atualizar(self):
        from em_raizes.fontes.chuva import LeituraChuva

        if not self.ok:
            self.ultimo_erro = "OSError: sem internet"
            return LeituraChuva(ok=False, erro=self.ultimo_erro)
        self.ultima = LeituraChuva(
            ok=True,
            chuva_72h=self.valores[0],
            previsao_24h=self.valores[1],
            estacao="E1",
            diario=[{"data": "2026-11-10", "chuva_mm": 3.0, "tipo": "observada"}],
        )
        return self.ultima

    def precisa_atualizar(self):
        return False


def test_central_com_chuva_real_sugere_voo_quando_a_chuva_aumenta():
    chuva = ChuvaFalsa(20.0, 2.0)
    mundo = MundoSimulado(cenario="real", chuva_real={"chuva_72h": 20.0, "previsao_24h": 2.0, "nome": "Chuva real"})
    c = CentralOperacoes(mundo, chuva=chuva)
    assert c.analise.mapa.cenario == "real" and c.clima_atual()["real"] is True
    assert not [r for r in c.estado()["recomendacoes"] if r["acao"] == "voo_drone"]
    chuva.valores = (95.0, 40.0)
    c._receber_chuva(chuva.atualizar())
    ev = [e for e in c.listar_eventos() if e.tipo == "chuva_atualizada"][-1]
    assert ev.nivel == "perigo" and "95 mm" in ev.mensagem
    rec = [r for r in c.estado()["recomendacoes"] if r["acao"] == "voo_drone"]
    assert rec and rec[0]["prioridade"] == "alta" and "20 → 95 mm" in rec[0]["motivo"]


def test_mudar_para_chuva_real_e_recusa_quando_indisponivel():
    c = CentralOperacoes(MundoSimulado(cenario="seco"), chuva=ChuvaFalsa(130.0, 60.0))
    cmd = c.mudar_clima("real")
    assert cmd.status == "concluido" and c.clima_atual()["chuva_72h"] == 130.0
    voo = c.enviar_drone()
    assert voo.parametros["cenario"] == "real"
    c2 = CentralOperacoes(MundoSimulado(cenario="seco"), chuva=ChuvaFalsa(ok=False))
    with pytest.raises(ComandoRecusado) as e:
        c2.mudar_clima("real")
    assert e.value.comando.codigo_recusa == "chuva_indisponivel"


# ------------------------------------------------------------------ notificações


def servico(enviados):
    def enviar(inscricao, dados, vapid, contato):
        if "expirada" in inscricao["endpoint"]:
            resp = type("R", (), {"status_code": 410})()
            raise type("WebPushException", (Exception,), {"response": resp})("gone")
        enviados.append((inscricao["endpoint"], json.loads(dados)))

    return ServicoNotificacoes(gerar_chave_privada(), enviar=enviar)


INSCRICAO = {"endpoint": "https://push.exemplo/abc", "keys": {"p256dh": "x" * 20, "auth": "y" * 10}}


def test_notificacoes_inscrever_enviar_e_remover_expiradas():
    enviados = []
    s = servico(enviados)
    assert s.habilitado and s.chave_publica and len(s.chave_publica) > 80
    with pytest.raises(ValueError):
        s.inscrever({"endpoint": "http://inseguro", "keys": {}})
    s.inscrever(INSCRICAO)
    s.inscrever({**INSCRICAO, "endpoint": "https://push.exemplo/expirada"})
    r = s.enviar("Título", "Corpo", tag="t1")
    assert r == {"enviadas": 1, "falhas": 1}
    assert enviados[0][1]["titulo"] == "Título" and s.status()["inscricoes"] == 1


def test_quais_eventos_viram_notificacao():
    ev = lambda tipo, nivel="info": Evento(id=1, quando=AGORA, tipo=tipo, nivel=nivel, mensagem="m")  # noqa: E731
    assert deve_notificar(ev("alerta_mudou", "info"))
    assert deve_notificar(ev("chuva_atualizada", "perigo")) and not deve_notificar(ev("chuva_atualizada", "info"))
    assert not deve_notificar(ev("comando_concluido", "info")) and not deve_notificar(ev("comando_recusado", "aviso"))


def test_alerta_novo_dispara_notificacao_pela_central():
    enviados = []
    s = servico(enviados)
    s.inscrever(INSCRICAO)
    s._pool = type("Imediato", (), {"submit": staticmethod(lambda f, *a: f(*a))})()
    c = CentralOperacoes(MundoSimulado(cenario="seco"))
    c.adicionar_ouvinte(s.ao_evento)
    c.mudar_clima("extrema")
    c.enviar_drone()
    c.relogio = lambda: datetime.now().astimezone() + timedelta(seconds=30)
    c.atualizar()
    titulos = [d["titulo"] for _, d in enviados]
    assert "Nível de alerta mudou" in titulos


# ------------------------------------------------------------------ foto com IA

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 200
DATA_URL = "data:image/jpeg;base64," + base64.b64encode(JPEG).decode()
ANALISE_OK = {
    "e_encosta": True,
    "risco": "alto",
    "confianca": "media",
    "resumo": "Trinca longa no solo e água minando.",
    "sinais": [{"tipo": "trinca_no_solo", "descricao": "Trinca de cerca de 2 m no barranco", "gravidade": "alta"}],
    "recomendacoes": ["Isolar a área e afastar as pessoas."],
}


def test_decodificar_imagem_valida_tipo_tamanho_e_assinatura():
    dados, tipo = decodificar_imagem(DATA_URL)
    assert tipo == "image/jpeg" and dados == JPEG
    for ruim, codigo in [
        ("data:image/gif;base64,R0lG", "tipo_invalido"),
        ("data:image/png;base64," + base64.b64encode(JPEG).decode(), "imagem_invalida"),
        ("data:image/jpeg;base64,***", "imagem_invalida"),
    ]:
        with pytest.raises(ErroFoto) as e:
            decodificar_imagem(ruim)
        assert e.value.codigo == codigo
    grande = "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff" + b"0" * (4 * 1024 * 1024)).decode()
    with pytest.raises(ErroFoto) as e:
        decodificar_imagem(grande)
    assert e.value.codigo == "imagem_grande"


def test_analise_de_foto_envia_imagem_valida_e_reforca_199():
    sdk = SDKFalso(["isto não é json", json.dumps(ANALISE_OK)])
    analise, meta = analisar_foto(
        ClienteLLM(api_key="x", modelo="m", reservas=[], cliente=sdk), JPEG, "image/jpeg", "perto da escada", "L05C12"
    )
    assert isinstance(analise, AnaliseFoto) and analise.risco == "alto"
    assert "199" in analise.recomendacoes[0]  # camada de segurança
    conteudo = sdk.chamadas[0]["messages"][1]["content"]
    assert conteudo[1]["type"] == "image_url" and conteudo[1]["image_url"]["url"].startswith("data:image/jpeg;base64,")
    assert "L05C12" in conteudo[0]["text"] and sdk.chamadas[0]["response_format"] == {"type": "json_object"}
    assert meta["modelo"] == "m" and len(sdk.chamadas) == 2


def test_foto_sem_ia_ou_com_chave_recusada():
    with pytest.raises(ErroFoto) as e:
        analisar_foto(ClienteLLM(api_key=""), JPEG, "image/jpeg")
    assert e.value.codigo == "ia_offline"
    sdk = SDKFalso([erro_http(openai.AuthenticationError, 401)])
    with pytest.raises(ErroFoto) as e:
        analisar_foto(ClienteLLM(api_key="x", modelo="m", reservas=[], cliente=sdk), JPEG, "image/jpeg")
    assert e.value.codigo == "chave_invalida"


# ------------------------------------------------------------------ API

SENHA = "senha-de-teste-123"


def cliente_api(sdk=None, chuva=None):
    enviados = []
    cfg = Config(segredo_jwt="s" * 40, admin_senha=SENHA, origens_cors=[])
    llm = ClienteLLM(api_key="x" if sdk else "", modelo="m", reservas=[], cliente=sdk)
    app = criar_app(
        cfg,
        CentralOperacoes(MundoSimulado(cenario="seco"), chuva=chuva),
        Guardiao(llm, BaseConhecimento()),
        chuva=chuva,
        notificacoes_servico=servico(enviados),
    )
    c = TestClient(app)
    token = c.post("/api/auth/login", json={"usuario": "admin", "senha": SENHA}).json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    return c, enviados, app


def test_api_foto_offline_e_online_com_evento_de_risco():
    c, _, _ = cliente_api()
    r = c.post("/api/ia/foto", json={"imagem": DATA_URL})
    assert r.status_code == 503 and r.json()["detail"]["codigo"] == "ia_offline"
    c, _, app = cliente_api(SDKFalso([json.dumps(ANALISE_OK)]))
    r = c.post("/api/ia/foto", json={"imagem": DATA_URL, "celula": "l05c12"})
    assert r.status_code == 200 and r.json()["analise"]["risco"] == "alto"
    eventos = [e for e in app.state.em_raizes.central.listar_eventos() if e.tipo == "foto_risco"]
    assert eventos and "L05C12" in eventos[0].mensagem
    assert c.post("/api/ia/foto", json={"imagem": "data:image/gif;base64,R0lG"}).status_code == 422


def test_api_notificacoes_e_info():
    c, enviados, _ = cliente_api()
    info = c.get("/api/info").json()
    assert info["push_habilitado"] is True and "real" in info["cenarios"]
    assert c.get("/api/notificacoes").json()["chave_publica"]
    assert c.post("/api/notificacoes/inscrever", json=INSCRICAO).json()["inscricoes"] == 1
    assert c.post("/api/notificacoes/teste").json()["enviadas"] == 1
    assert enviados[0][1]["tag"] == "teste"
    assert c.post("/api/notificacoes/cancelar", json={"endpoint": INSCRICAO["endpoint"]}).json()["inscricoes"] == 0


def test_api_chuva_real_no_grafico_e_no_clima():
    chuva = ChuvaFalsa(60.0, 30.0)
    c, _, _ = cliente_api(chuva=chuva)
    assert c.post("/api/simulacao/clima", json={"cenario": "real"}).status_code == 201
    estado = c.get("/api/estado").json()
    assert estado["clima_atual"]["real"] and estado["clima_atual"]["chuva_72h"] == 60.0
    assert c.get("/api/chuva").json() == chuva.ultima.diario


def test_push_de_verdade_cifrado_e_entregue_a_um_servidor_local():
    """Usa o pywebpush real (VAPID + criptografia aes128gcm) contra um endpoint local e decifra a mensagem."""
    import os
    import threading
    from http.server import BaseHTTPRequestHandler, HTTPServer

    import http_ece
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import ec

    recebido = {}

    class Endpoint(BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            recebido["headers"] = {k.lower(): v for k, v in self.headers.items()}
            recebido["corpo"] = self.rfile.read(int(self.headers["Content-Length"]))
            self.send_response(201)
            self.end_headers()

        def log_message(self, *a):
            pass

    servidor = HTTPServer(("127.0.0.1", 0), Endpoint)
    threading.Thread(target=servidor.handle_request, daemon=True).start()

    chave_navegador = ec.generate_private_key(ec.SECP256R1())
    publica = chave_navegador.public_key().public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    auth = os.urandom(16)
    b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()  # noqa: E731
    inscricao = {
        "endpoint": f"http://127.0.0.1:{servidor.server_port}/push",
        "keys": {"p256dh": b64(publica), "auth": b64(auth)},
    }

    s = ServicoNotificacoes(gerar_chave_privada())  # envio REAL (pywebpush)
    s.inscricoes[inscricao["endpoint"]] = inscricao  # endpoint http local (o app só aceita https)
    assert s.enviar("Nível de alerta mudou", "Alerta máximo em Petrópolis", tag="evento-7") == {
        "enviadas": 1,
        "falhas": 0,
    }

    assert recebido["headers"]["content-encoding"] == "aes128gcm"
    assert recebido["headers"]["authorization"].startswith("vapid t=")
    texto = http_ece.decrypt(recebido["corpo"], private_key=chave_navegador, auth_secret=auth, version="aes128gcm")
    assert json.loads(texto) == {
        "titulo": "Nível de alerta mudou",
        "corpo": "Alerta máximo em Petrópolis",
        "url": "/#/inicio",
        "tag": "evento-7",
        "nivel": "info",
    }
    servidor.server_close()

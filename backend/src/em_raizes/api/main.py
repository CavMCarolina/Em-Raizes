"""API HTTP do app do administrador.

Rodar em desenvolvimento:  uvicorn em_raizes.api.main:criar_app --factory --reload
Documentação interativa:   http://localhost:8000/docs
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Annotated, Any

from fastapi import APIRouter, Depends, FastAPI, Header, HTTPException, Query, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .. import __version__
from ..config import Config, obter_config
from ..dominio.modelos import CENARIO_REAL, CENARIOS
from ..dominio.risco import explicar_celula
from ..fontes.chuva import Cidade, FonteChuvaReal
from ..fontes.simulador import MundoSimulado, historico_chuva, imagem_aerea
from ..ia.conhecimento import BaseConhecimento
from ..ia.guardiao import Guardiao, resumo_contexto
from ..ia.llm import ClienteLLM
from ..ia.visao import ErroFoto, analisar_foto, decodificar_imagem
from ..operacoes.central import CentralOperacoes, ComandoRecusado
from ..operacoes.modelos import Comando, Evento
from ..operacoes.notificacoes import ServicoNotificacoes, obter_chave_privada
from .imagem import png_rgb
from .seguranca import Identidade, autenticar_admin, config_dep, emitir_token, identidade

log = logging.getLogger("em_raizes.api")

COLUNAS_MAPA = [
    "celula",
    "linha",
    "coluna",
    "setor",
    "risco",
    "classe_risco",
    "risco_24h",
    "classe_risco_24h",
    "tendencia",
    "umidade_pct",
    "umidade_24h",
    "cobertura_vegetal",
    "declividade_graus",
    "elevacao_m",
    "tipo_solo",
    "solo_visao",
    "confianca_visao",
    "casas",
    "moradores_estimados",
    "fissura_detectada",
    "prob_fissura",
    "vazamento",
    "plantio_recomendado",
    "plantio_manual",
    "precisa_irrigar",
    "mudas",
    "litros_irrigacao",
]


# --------------------------------------------------------------------------- esquemas de entrada


class Login(BaseModel):
    usuario: str
    senha: str


class AlvosRobo(BaseModel):
    celulas: list[str] | None = Field(default=None, description="Células (ex.: L05C12). Vazio = o sistema escolhe.")


class Clima(BaseModel):
    cenario: str = Field(description=f"Um de: {', '.join([*CENARIOS, CENARIO_REAL])} (real = pluviômetros)")


class InscricaoPush(BaseModel):
    endpoint: str
    keys: dict[str, str]
    expirationTime: float | None = None  # noqa: N815 - nome definido pelo navegador


class CancelarPush(BaseModel):
    endpoint: str


class Foto(BaseModel):
    imagem: str = Field(description="Data URL (data:image/jpeg;base64,...) ou base64 puro", max_length=6_000_000)
    tipo: str | None = Field(default=None, description="image/jpeg, image/png ou image/webp (se não vier na data URL)")
    observacao: str = Field(default="", max_length=300)
    celula: str | None = Field(default=None, max_length=8)


class Pergunta(BaseModel):
    pergunta: str = Field(min_length=1, max_length=1000)
    historico: list[dict[str, str]] = Field(default_factory=list)


# --------------------------------------------------------------------------- dependências


class Estado:
    """Objetos compartilhados pela aplicação (criados uma vez)."""

    def __init__(
        self,
        cfg: Config,
        central: CentralOperacoes | None = None,
        guardiao: Guardiao | None = None,
        chuva: FonteChuvaReal | None = None,
        notificacoes: ServicoNotificacoes | None = None,
    ):
        self.cfg = cfg
        self.chuva = chuva or FonteChuvaReal(
            Cidade(
                nome=cfg.chuva_cidade,
                uf=cfg.chuva_uf,
                codigo_ibge=cfg.chuva_ibge,
                latitude=cfg.chuva_lat,
                longitude=cfg.chuva_lon,
                codigo_estacao=cfg.chuva_estacao,
            ),
            validade_min=cfg.chuva_validade_min,
        )
        self.central = central or self._criar_central(cfg)
        if self.central.chuva is None:
            self.central.chuva = self.chuva
        self.guardiao = guardiao or Guardiao(ClienteLLM(), BaseConhecimento())
        self.notificacoes = notificacoes or ServicoNotificacoes(
            obter_chave_privada(cfg.vapid_privada, cfg.pasta_dados, cfg.producao), cfg.vapid_contato
        )
        self.central.adicionar_ouvinte(self.notificacoes.ao_evento)
        self._imagens: dict[str, bytes] = {}

    def _criar_central(self, cfg: Config) -> CentralOperacoes:
        cenario, chuva_real, aviso = cfg.sim_cenario, None, None
        if cenario == CENARIO_REAL:
            leitura = self.chuva.atualizar()
            if leitura.ok:
                chuva_real = {
                    "chuva_72h": leitura.chuva_72h,
                    "previsao_24h": leitura.previsao_24h,
                    "nome": f"Chuva real · {self.chuva.cidade.rotulo}",
                }
            else:
                cenario = "moderada"
                aviso = f"Chuva real indisponível ({leitura.erro}). Usando a chuva simulada 'moderada'."
                log.warning(aviso)
        central = CentralOperacoes(
            MundoSimulado(semente=cfg.sim_semente, cenario=cenario, tamanho=cfg.sim_tamanho, chuva_real=chuva_real),
            escala_tempo=cfg.sim_escala_tempo,
            chuva=self.chuva,
        )
        if aviso:
            central.registrar_evento("chuva_indisponivel", aviso, "aviso")
        return central

    def imagem(self) -> bytes:
        mapa = self.central.analise.mapa
        if mapa.voo_id not in self._imagens:
            self._imagens = {mapa.voo_id: png_rgb(imagem_aerea(mapa, px=10))}
        return self._imagens[mapa.voo_id]


def estado_app(request: Request) -> Estado:
    return request.app.state.em_raizes


Auth = Annotated[Identidade, Depends(identidade)]
App = Annotated[Estado, Depends(estado_app)]
ChaveIdem = Annotated[str | None, Header(alias="Idempotency-Key", description="Evita comando duplicado em repetições")]


def contexto_operacional(central: CentralOperacoes) -> str:
    est = central.estado()
    linhas = [resumo_contexto(central.analise, central.missoes)]
    clima = est["clima_atual"]
    linhas.append(
        f"CLIMA ATUAL (pluviômetro): {clima['nome']} — {clima['chuva_72h']:.0f} mm em 72 h, "
        f"{clima['previsao_24h']:.0f} mm previstos"
    )
    for d in est["dispositivos"]:
        linhas.append(
            f"FROTA: {d.nome} ({d.id}) — {d.status}, bateria {d.bateria:.0f}%"
            + (f", executando {d.comando_atual}" if d.comando_atual else "")
        )
    linhas.append("ROBÔ LIBERADO: " + ("sim" if est["robo_liberado"] else "não (alerta ativo ou frota parada)"))
    for c in est["ultimos_comandos"][:5]:
        linhas.append(
            f"COMANDO {c.id}: {c.tipo} · {c.status} · origem {c.origem}" + (f" · {c.motivo}" if c.motivo else "")
        )
    for r in est["recomendacoes"]:
        linhas.append(f"AÇÃO SUGERIDA ({r['prioridade']}): {r['titulo']} — {r['motivo']}")
    return "\n".join(linhas)


# --------------------------------------------------------------------------- rotas

publico = APIRouter(prefix="/api", tags=["público"])
auth_r = APIRouter(prefix="/api/auth", tags=["autenticação"])
leitura = APIRouter(prefix="/api", tags=["leitura"])
comandos = APIRouter(prefix="/api/comandos", tags=["comandos"])
simulacao = APIRouter(prefix="/api/simulacao", tags=["simulação"])
ia = APIRouter(prefix="/api/ia", tags=["IA"])


@publico.get("/saude")
def saude() -> dict:
    # Commit em execução: vem da imagem (build arg EM_RAIZES_COMMIT, no CI) ou do Render (RENDER_GIT_COMMIT).
    # O CI/CD usa este campo para confirmar que o site no ar é o commit que passou nos testes.
    commit = os.getenv("EM_RAIZES_COMMIT") or os.getenv("RENDER_GIT_COMMIT") or None
    return {"status": "ok", "versao": __version__, "commit": commit}


@publico.get("/info")
def info(app: App) -> dict:
    cfg = app.cfg
    return {
        "nome_app": cfg.nome_app,
        "versao": __version__,
        "ambiente": cfg.ambiente,
        "login_habilitado": bool(cfg.admin_senha),
        "ia_online": app.guardiao.online,
        "modelo_ia": app.guardiao.cliente.modelo,
        "dados_simulados": True,
        "cenarios": {CENARIO_REAL: f"Chuva real — {app.chuva.cidade.rotulo}"}
        | {k: v["nome"] for k, v in CENARIOS.items()},
        "push_habilitado": app.notificacoes.habilitado,
        "analise_foto": app.guardiao.online,
    }


@auth_r.post("/login")
def login(dados: Login, cfg: Annotated[Config, Depends(config_dep)]) -> dict:
    if not cfg.admin_senha:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            {"codigo": "login_desativado", "mensagem": "Defina EM_RAIZES_ADMIN_SENHA no servidor."},
        )
    if not autenticar_admin(dados.usuario, dados.senha, cfg):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            {"codigo": "credenciais_invalidas", "mensagem": "Usuário ou senha incorretos."},
        )
    token, expira = emitir_token(dados.usuario, cfg)
    return {"token": token, "expira_em": expira.isoformat(), "usuario": dados.usuario}


@leitura.get("/estado")
def estado(app: App, _: Auth) -> dict:
    est = app.central.estado()
    est["dispositivos"] = [d.model_dump(mode="json") for d in est["dispositivos"]]
    est["comandos_ativos"] = [c.model_dump(mode="json") for c in est["comandos_ativos"]]
    est["ultimos_comandos"] = [c.model_dump(mode="json") for c in est["ultimos_comandos"]]
    return est


@leitura.get("/mapa")
def mapa(app: App, _: Auth) -> dict:
    central = app.central
    central.atualizar()
    m, df = central.analise.mapa, central.analise.df
    registros = df[COLUNAS_MAPA].astype(object).where(df[COLUNAS_MAPA].notna(), None).to_dict(orient="records")
    return {
        "voo_id": m.voo_id,
        "data_voo": m.data_voo.isoformat(),
        "linhas": m.linhas,
        "colunas": m.colunas,
        "tamanho_celula_m": 10,
        "celulas": registros,
    }


@leitura.get("/mapa/celulas/{celula}")
def detalhe_celula(celula: str, app: App, _: Auth) -> dict:
    df = app.central.analise.df
    linha = df[df["celula"] == celula.upper()]
    if linha.empty:
        raise HTTPException(404, {"codigo": "celula_inexistente", "mensagem": f"Célula {celula} não existe."})
    dados = linha[COLUNAS_MAPA].iloc[0].to_dict()
    return {
        "celula": {k: (v.item() if hasattr(v, "item") else v) for k, v in dados.items()},
        "explicacao": explicar_celula(app.central.analise, celula.upper()),
    }


@leitura.get("/mapa/imagem.png", responses={200: {"content": {"image/png": {}}}})
def foto_aerea(app: App, _: Auth) -> Response:
    return Response(app.imagem(), media_type="image/png", headers={"Cache-Control": "max-age=60"})


@leitura.get("/chuva")
def chuva(app: App, _: Auth) -> list[dict]:
    if app.central.fonte.cenario == CENARIO_REAL and app.chuva.ultima and app.chuva.ultima.diario:
        return app.chuva.ultima.diario  # Open-Meteo (estimativa diária) para o gráfico
    h = historico_chuva(app.central.analise.mapa)
    h["data"] = h["data"].astype(str)
    return h.to_dict(orient="records")


@leitura.get("/comandos", response_model=list[Comando])
def listar_comandos(
    app: App, _: Auth, limite: int = Query(50, ge=1, le=500), status_: str | None = Query(None, alias="status")
):
    return app.central.listar_comandos(limite, status_)


@leitura.get("/eventos", response_model=list[Evento])
def eventos(app: App, _: Auth, desde: int = Query(0, ge=0), limite: int = Query(100, ge=1, le=1000)):
    return app.central.listar_eventos(desde, limite)


def _cmd(app: Estado, quem: Identidade, chave: str | None, metodo: str, *args: Any) -> JSONResponse:
    central = app.central
    func = getattr(central, metodo)
    try:
        antes = len(central.comandos)
        cmd: Comando = func(*args, origem=quem.origem, chave=chave)
    except ComandoRecusado as e:
        return JSONResponse(e.comando.model_dump(mode="json"), status_code=status.HTTP_409_CONFLICT)
    except ValueError as e:
        raise HTTPException(422, {"codigo": "parametro_invalido", "mensagem": str(e)}) from None
    replay = chave is not None and len(central.comandos) == antes
    return JSONResponse(
        cmd.model_dump(mode="json"),
        status_code=200 if replay else 201,
        headers={"Idempotency-Replayed": "true"} if replay else None,
    )


RESPOSTAS_CMD: dict = {
    201: {"model": Comando, "description": "Comando criado"},
    200: {"model": Comando, "description": "Repetição (mesma Idempotency-Key)"},
    409: {"model": Comando, "description": "Recusado por regra de segurança (veja codigo_recusa)"},
}


@comandos.post("/drone/voo", status_code=201, responses=RESPOSTAS_CMD)
def enviar_drone(app: App, quem: Auth, chave: ChaveIdem = None):
    return _cmd(app, quem, chave, "enviar_drone")


@comandos.post("/robo/{missao}", status_code=201, responses=RESPOSTAS_CMD)
def enviar_robo(missao: str, app: App, quem: Auth, alvos: AlvosRobo | None = None, chave: ChaveIdem = None):
    if missao == "recolher":
        return _cmd(app, quem, chave, "recolher_robo")
    if missao not in ("plantio", "irrigacao", "inspecao"):
        raise HTTPException(
            404, {"codigo": "missao_inexistente", "mensagem": "Use plantio, irrigacao, inspecao ou recolher."}
        )
    return _cmd(app, quem, chave, "enviar_robo", missao, (alvos.celulas if alvos else None))


@comandos.post("/emergencia", status_code=201, responses=RESPOSTAS_CMD)
def parada_emergencia(app: App, quem: Auth, chave: ChaveIdem = None):
    return _cmd(app, quem, chave, "parada_emergencia")


@comandos.post("/liberar", status_code=201, responses=RESPOSTAS_CMD)
def liberar_frota(app: App, quem: Auth, chave: ChaveIdem = None):
    return _cmd(app, quem, chave, "liberar_frota")


@simulacao.post("/clima", status_code=201, responses=RESPOSTAS_CMD)
def mudar_clima(dados: Clima, app: App, quem: Auth, chave: ChaveIdem = None):
    return _cmd(app, quem, chave, "mudar_clima", dados.cenario)


def _resposta_ia(r) -> dict:
    return {
        "texto": r.texto,
        "modo": r.modo,
        "modelo": r.modelo,
        "fontes": r.fontes,
        "aviso": r.aviso,
        "tokens": r.tokens,
        "latencia_s": r.latencia_s,
    }


@ia.post("/chat")
def chat(dados: Pergunta, app: App, _: Auth) -> dict:
    historico = [h for h in dados.historico if h.get("role") in ("user", "assistant")][-6:]
    return _resposta_ia(app.guardiao.responder(dados.pergunta, contexto_operacional(app.central), historico))


@ia.post("/explicar/{celula}")
def explicar(celula: str, app: App, _: Auth) -> dict:
    try:
        return _resposta_ia(app.guardiao.explicar_celula(app.central.analise, celula.upper()))
    except KeyError:
        raise HTTPException(404, {"codigo": "celula_inexistente", "mensagem": f"Célula {celula} não existe."}) from None


@ia.post("/sms")
def sms(app: App, _: Auth) -> dict:
    return _resposta_ia(app.guardiao.gerar_sms(app.central.analise))


@ia.post("/plano")
def plano(app: App, _: Auth) -> dict:
    p, r = app.guardiao.gerar_plano(app.central.analise, app.central.missoes)
    return {"plano": p.model_dump(), **_resposta_ia(r)}


@ia.post("/foto")
def foto(dados: Foto, app: App, quem: Auth) -> dict:
    """Triagem visual de risco por foto (IA multimodal). Não substitui vistoria."""
    try:
        imagem, tipo = decodificar_imagem(dados.imagem, dados.tipo)
        celula = dados.celula.strip().upper() if dados.celula else None
        analise, meta = analisar_foto(app.guardiao.cliente, imagem, tipo, dados.observacao, celula)
    except ErroFoto as e:
        status_http = 503 if e.codigo in ("ia_offline", "sem_chave", "chave_invalida", "sem_credito") else 422
        raise HTTPException(status_http, {"codigo": e.codigo, "mensagem": e.mensagem}) from None
    if analise.risco in ("alto", "critico"):
        local = f" na célula {celula}" if celula else ""
        app.central.registrar_evento(
            "foto_risco",
            f"Foto{local} com risco {analise.risco}: {analise.resumo}",
            "perigo" if analise.risco == "critico" else "aviso",
            quem.origem,
        )
    return {"analise": analise.model_dump(), **meta}


notificacoes = APIRouter(prefix="/api/notificacoes", tags=["notificações"])


@notificacoes.get("")
def status_notificacoes(app: App, _: Auth) -> dict:
    return app.notificacoes.status()


@notificacoes.post("/inscrever")
def inscrever(dados: InscricaoPush, app: App, _: Auth) -> dict:
    try:
        total = app.notificacoes.inscrever(dados.model_dump())
    except ValueError as e:
        raise HTTPException(422, {"codigo": "inscricao_invalida", "mensagem": str(e)}) from None
    return {"inscrito": True, "inscricoes": total}


@notificacoes.post("/cancelar")
def cancelar_inscricao(dados: CancelarPush, app: App, _: Auth) -> dict:
    return {"inscrito": False, "inscricoes": app.notificacoes.cancelar(dados.endpoint)}


@notificacoes.post("/teste")
def teste_notificacao(app: App, _: Auth) -> dict:
    if not app.notificacoes.habilitado:
        raise HTTPException(
            503, {"codigo": "push_desativado", "mensagem": "Notificações push desativadas no servidor."}
        )
    return app.notificacoes.enviar(
        "Teste de notificação", "Se você recebeu isto, os alertas vão chegar neste aparelho.", "/#/inicio", "teste"
    )


# --------------------------------------------------------------------------- aplicação


def _pasta_frontend(cfg: Config) -> Path | None:
    candidatos = [Path(cfg.pasta_frontend)] if cfg.pasta_frontend else []
    candidatos += [Path.cwd() / "frontend" / "dist", Path(__file__).resolve().parents[4] / "frontend" / "dist"]
    return next((p for p in candidatos if (p / "index.html").is_file()), None)


def criar_app(
    cfg: Config | None = None,
    central: CentralOperacoes | None = None,
    guardiao: Guardiao | None = None,
    chuva: FonteChuvaReal | None = None,
    notificacoes_servico: ServicoNotificacoes | None = None,
) -> FastAPI:
    cfg = cfg or obter_config()
    app = FastAPI(
        title=f"{cfg.nome_app} — API do administrador",
        version=__version__,
        description=(
            "Comandos do drone e do robô jardineiro (SIMULADOS), risco de deslizamento e IA generativa. "
            "Autentique com `POST /api/auth/login` (token Bearer)."
        ),
    )
    app.state.em_raizes = Estado(cfg, central, guardiao, chuva, notificacoes_servico)
    if cfg.origens_cors:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cfg.origens_cors,
            allow_methods=["*"],
            allow_headers=["*"],
            expose_headers=["Idempotency-Replayed"],
        )
    for r in (publico, auth_r, leitura, comandos, simulacao, ia, notificacoes):
        app.include_router(r)
    app.dependency_overrides[config_dep] = lambda: cfg
    pasta = _pasta_frontend(cfg)
    if pasta:
        app.mount("/", StaticFiles(directory=pasta, html=True), name="frontend")
        log.info("Servindo o app do administrador de %s", pasta)
    return app


def rodar() -> None:  # pragma: no cover - usado pelo script "em-raizes-api"
    import uvicorn

    uvicorn.run(
        "em_raizes.api.main:criar_app",
        factory=True,
        host=os.getenv("HOST", "0.0.0.0"),
        port=int(os.getenv("PORT", "8000")),
    )

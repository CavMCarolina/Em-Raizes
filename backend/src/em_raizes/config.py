"""Configuração central, lida de variáveis de ambiente (arquivo .env em dev).

Em produção (``EM_RAIZES_AMBIENTE=producao``) os segredos são obrigatórios;
em desenvolvimento há valores padrão para facilitar, com aviso no log.
"""

from __future__ import annotations

import logging
import os
import secrets
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

log = logging.getLogger("em_raizes")

# Nome do projeto (exibido no app, no prompt do Guardião e nos SMS). Também em frontend/src/config.ts.
NOME_APP_PADRAO = "Em Raízes"


def _carregar_dotenv() -> None:
    for pasta in (Path.cwd(), *Path(__file__).resolve().parents):
        arquivo = pasta / ".env"
        if arquivo.is_file():
            load_dotenv(arquivo, override=False)
            return


def _lista(valor: str | None, padrao: list[str]) -> list[str]:
    if valor is None:
        return list(padrao)
    return [v.strip() for v in valor.split(",") if v.strip()]


@dataclass(frozen=True)
class Config:
    nome_app: str = NOME_APP_PADRAO
    ambiente: str = "dev"
    segredo_jwt: str = ""
    minutos_token: int = 12 * 60
    admin_usuario: str = "admin"
    admin_senha: str = ""
    origens_cors: list[str] = field(default_factory=list)
    pasta_frontend: str = ""
    # simulação
    sim_semente: int = 42
    sim_cenario: str = "moderada"
    sim_tamanho: int = 24
    sim_escala_tempo: float = 1.0  # 0.5 = tudo 2x mais rápido
    # chuva real (Cemaden + Open-Meteo); usada quando sim_cenario = "real"
    chuva_cidade: str = "Petrópolis"
    chuva_uf: str = "RJ"
    chuva_ibge: int = 3303906
    chuva_lat: float = -22.505
    chuva_lon: float = -43.178
    chuva_estacao: int | None = None
    chuva_validade_min: float = 10.0
    # notificações push (Web Push / VAPID)
    vapid_privada: str = ""
    vapid_contato: str = "mailto:admin@example.com"
    pasta_dados: str = ".dados"

    @property
    def producao(self) -> bool:
        return self.ambiente == "producao"


class ErroConfig(RuntimeError):
    pass


@lru_cache
def obter_config() -> Config:
    _carregar_dotenv()
    env = os.getenv
    ambiente = env("EM_RAIZES_AMBIENTE", "dev").strip().lower()
    cfg = Config(
        nome_app=env("EM_RAIZES_NOME_APP", NOME_APP_PADRAO),
        ambiente=ambiente,
        segredo_jwt=env("EM_RAIZES_SEGREDO_JWT", ""),
        minutos_token=int(env("EM_RAIZES_MINUTOS_TOKEN", str(12 * 60))),
        admin_usuario=env("EM_RAIZES_ADMIN_USUARIO", "admin"),
        admin_senha=env("EM_RAIZES_ADMIN_SENHA", ""),
        origens_cors=_lista(env("EM_RAIZES_ORIGENS_CORS"), ["http://localhost:5173", "http://127.0.0.1:5173"]),
        pasta_frontend=env("EM_RAIZES_PASTA_FRONTEND", ""),
        sim_semente=int(env("EM_RAIZES_SIM_SEMENTE", "42")),
        sim_cenario=env("EM_RAIZES_SIM_CENARIO", "real"),
        sim_tamanho=int(env("EM_RAIZES_SIM_TAMANHO", "24")),
        sim_escala_tempo=float(env("EM_RAIZES_SIM_ESCALA_TEMPO", "1.0")),
        chuva_cidade=env("EM_RAIZES_CHUVA_CIDADE", "Petrópolis"),
        chuva_uf=env("EM_RAIZES_CHUVA_UF", "RJ"),
        chuva_ibge=int(env("EM_RAIZES_CHUVA_IBGE", "3303906")),
        chuva_lat=float(env("EM_RAIZES_CHUVA_LAT", "-22.505")),
        chuva_lon=float(env("EM_RAIZES_CHUVA_LON", "-43.178")),
        chuva_estacao=int(env("EM_RAIZES_CHUVA_ESTACAO")) if env("EM_RAIZES_CHUVA_ESTACAO") else None,
        chuva_validade_min=float(env("EM_RAIZES_CHUVA_VALIDADE_MIN", "10")),
        vapid_privada=env("EM_RAIZES_VAPID_PRIVADA", ""),
        vapid_contato=env("EM_RAIZES_VAPID_CONTATO", "mailto:admin@example.com"),
        pasta_dados=env("EM_RAIZES_PASTA_DADOS", ".dados"),
    )
    faltando = [
        n for n, v in [("EM_RAIZES_SEGREDO_JWT", cfg.segredo_jwt), ("EM_RAIZES_ADMIN_SENHA", cfg.admin_senha)] if not v
    ]
    if faltando and cfg.producao:
        raise ErroConfig(f"Em produção defina: {', '.join(faltando)}")
    if not cfg.segredo_jwt:
        object.__setattr__(cfg, "segredo_jwt", secrets.token_urlsafe(32))
        log.warning("EM_RAIZES_SEGREDO_JWT não definido: usando segredo temporário (tokens expiram ao reiniciar).")
    if not cfg.admin_senha:
        log.warning(
            "EM_RAIZES_ADMIN_SENHA não definida: o login do administrador fica DESATIVADO até você definir uma."
        )
    return cfg

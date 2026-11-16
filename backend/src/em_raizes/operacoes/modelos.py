"""Modelos da central de operações (também usados como respostas da API)."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

TipoComando = Literal[
    "voo_drone",
    "plantio",
    "irrigacao",
    "inspecao",
    "recolher_robo",
    "parada_emergencia",
    "liberar_frota",
    "mudar_clima",
]
StatusComando = Literal["em_execucao", "concluido", "recusado", "cancelado"]
Origem = Literal["admin", "sistema"]
StatusDispositivo = Literal["na_base", "em_missao", "parado"]


class Posicao(BaseModel):
    linha: int
    coluna: int


class Dispositivo(BaseModel):
    id: str
    tipo: Literal["drone", "robo"]
    nome: str
    status: StatusDispositivo = "na_base"
    bateria: float = 100.0
    comando_atual: str | None = None
    posicao: Posicao | None = None


class Comando(BaseModel):
    id: str
    tipo: TipoComando
    dispositivo: str | None = None
    origem: Origem
    status: StatusComando
    progresso: int = 0
    celulas: list[str] = Field(default_factory=list)
    ignoradas: dict[str, str] = Field(default_factory=dict, description="célula -> motivo de ter ficado de fora")
    parametros: dict[str, Any] = Field(default_factory=dict)
    resultado: dict[str, Any] = Field(default_factory=dict)
    codigo_recusa: str | None = None
    motivo: str | None = None
    criado_em: datetime
    iniciado_em: datetime | None = None
    concluido_em: datetime | None = None
    duracao_s: float = 0.0
    chave_idempotencia: str | None = None


class Evento(BaseModel):
    id: int
    quando: datetime
    tipo: str
    nivel: Literal["info", "aviso", "perigo"] = "info"
    mensagem: str
    origem: Origem = "sistema"
    comando_id: str | None = None


class Recomendacao(BaseModel):
    id: str
    acao: TipoComando
    prioridade: Literal["alta", "media", "baixa"]
    titulo: str
    motivo: str
    celulas: list[str] = Field(default_factory=list)

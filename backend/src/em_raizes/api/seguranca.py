"""Autenticação da API.

O administrador entra com ``POST /api/auth/login``, que devolve um token JWT (Bearer).
A origem ("admin") fica registrada em todo comando, para auditoria; o próprio sistema usa "sistema".
"""

from __future__ import annotations

import hmac
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, Request, status

from ..config import Config, obter_config

ALGORITMO = "HS256"


@dataclass(frozen=True)
class Identidade:
    usuario: str
    origem: str  # "admin"


def _iguais(a: str, b: str) -> bool:
    return bool(a) and bool(b) and hmac.compare_digest(a.encode(), b.encode())


def autenticar_admin(usuario: str, senha: str, cfg: Config) -> bool:
    if not cfg.admin_senha:
        return False
    return _iguais(usuario, cfg.admin_usuario) & _iguais(senha, cfg.admin_senha)


def emitir_token(usuario: str, cfg: Config) -> tuple[str, datetime]:
    expira = datetime.now(UTC) + timedelta(minutes=cfg.minutos_token)
    token = jwt.encode({"sub": usuario, "exp": expira, "papel": "admin"}, cfg.segredo_jwt, algorithm=ALGORITMO)
    return token, expira


def config_dep() -> Config:
    return obter_config()


def identidade(request: Request, cfg: Config = Depends(config_dep)) -> Identidade:
    auth = request.headers.get("authorization", "")
    if not auth.lower().startswith("bearer "):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            {"codigo": "nao_autenticado", "mensagem": "Faça login."},
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        dados = jwt.decode(auth[7:], cfg.segredo_jwt, algorithms=[ALGORITMO])
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, {"codigo": "sessao_expirada", "mensagem": "Sessão expirada. Entre de novo."}
        ) from None
    except jwt.InvalidTokenError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED, {"codigo": "token_invalido", "mensagem": "Token inválido."}
        ) from None
    return Identidade(usuario=dados.get("sub", "admin"), origem="admin")

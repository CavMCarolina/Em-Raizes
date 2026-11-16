"""Notificações push (Web Push) para o celular do administrador.

Funciona com o app instalado como PWA, mesmo com o app fechado:
Android (Chrome/Edge) e iPhone com iOS 16.4+ (app adicionado à tela inicial).

- Chaves VAPID: em produção vêm de ``EM_RAIZES_VAPID_PRIVADA``; em desenvolvimento
  são geradas uma vez e guardadas em ``.dados/vapid.json`` (fora do Git).
- O app reenvia a inscrição a cada abertura, então guardar as inscrições só em
  memória basta para o MVP.
- Quais eventos viram notificação: mudança do nível de alerta, chuva real piorando,
  parada de emergência, fissura confirmada e foto com sinais de risco.
"""

from __future__ import annotations

import base64
import json
import logging
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid02

from .modelos import Evento

log = logging.getLogger("em_raizes.notificacoes")

TITULOS = {
    "alerta_mudou": "Nível de alerta mudou",
    "chuva_atualizada": "A chuva aumentou",
    "frota_parada": "Parada de emergência",
    "fissura_confirmada": "Fissura confirmada",
    "foto_risco": "Foto com sinais de risco",
}
DESTINO = {"alerta_mudou": "/#/alertas", "chuva_atualizada": "/#/inicio", "foto_risco": "/#/guardiao"}


def _b64url(dados: bytes) -> str:
    return base64.urlsafe_b64encode(dados).rstrip(b"=").decode()


def gerar_chave_privada() -> str:
    v = Vapid02()
    v.generate_keys()
    return _b64url(v.private_key.private_numbers().private_value.to_bytes(32, "big"))


def carregar_vapid(chave_privada: str) -> Vapid02:
    return Vapid02.from_raw(chave_privada.encode())


def chave_publica(vapid: Vapid02) -> str:
    """Formato que o navegador espera em ``applicationServerKey``."""
    return _b64url(
        vapid.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
    )


def obter_chave_privada(configurada: str, pasta_dados: str, producao: bool) -> str | None:
    if configurada:
        return configurada
    if producao:
        log.warning("EM_RAIZES_VAPID_PRIVADA não definida: notificações push desativadas.")
        return None
    arquivo = Path(pasta_dados) / "vapid.json"
    try:
        return json.loads(arquivo.read_text(encoding="utf-8"))["privada"]
    except (OSError, ValueError, KeyError):
        chave = gerar_chave_privada()
        arquivo.parent.mkdir(parents=True, exist_ok=True)
        arquivo.write_text(json.dumps({"privada": chave}), encoding="utf-8")
        log.warning("Chaves VAPID de desenvolvimento geradas em %s", arquivo)
        return chave


def deve_notificar(ev: Evento) -> bool:
    if ev.tipo not in TITULOS:
        return False
    return ev.tipo == "alerta_mudou" or ev.nivel in ("aviso", "perigo")


def _enviar_webpush(inscricao: dict, dados: str, vapid: Vapid02, contato: str):
    from pywebpush import webpush

    return webpush(inscricao, data=dados, vapid_private_key=vapid, vapid_claims={"sub": contato}, ttl=3600, timeout=10)


class ServicoNotificacoes:
    def __init__(
        self,
        chave_privada: str | None,
        contato: str = "mailto:admin@example.com",
        enviar: Callable[[dict, str, Vapid02, str], object] = _enviar_webpush,
    ):
        self.vapid = carregar_vapid(chave_privada) if chave_privada else None
        self.contato = contato
        self._enviar = enviar
        self._lock = threading.Lock()
        self.inscricoes: dict[str, dict] = {}
        self.enviadas = 0
        self.falhas = 0
        self.ultimo_erro: str | None = None
        self._pool = ThreadPoolExecutor(max_workers=2, thread_name_prefix="push")

    @property
    def habilitado(self) -> bool:
        return self.vapid is not None

    @property
    def chave_publica(self) -> str | None:
        return chave_publica(self.vapid) if self.vapid else None

    def inscrever(self, inscricao: dict) -> int:
        endpoint = inscricao.get("endpoint", "")
        chaves = inscricao.get("keys") or {}
        if not endpoint.startswith("https://") or not chaves.get("p256dh") or not chaves.get("auth"):
            raise ValueError("Inscrição inválida: faltam endpoint https, p256dh ou auth.")
        with self._lock:
            self.inscricoes[endpoint] = {
                "endpoint": endpoint,
                "keys": {"p256dh": chaves["p256dh"], "auth": chaves["auth"]},
            }
            return len(self.inscricoes)

    def cancelar(self, endpoint: str) -> int:
        with self._lock:
            self.inscricoes.pop(endpoint, None)
            return len(self.inscricoes)

    def status(self) -> dict:
        with self._lock:
            return {
                "habilitado": self.habilitado,
                "chave_publica": self.chave_publica,
                "inscricoes": len(self.inscricoes),
                "enviadas": self.enviadas,
                "falhas": self.falhas,
                "ultimo_erro": self.ultimo_erro,
            }

    def enviar(self, titulo: str, corpo: str, url: str = "/#/inicio", tag: str = "geral", nivel: str = "info") -> dict:
        """Envia para todos os aparelhos inscritos (bloqueia). Remove inscrições expiradas (404/410)."""
        if not self.habilitado:
            return {"enviadas": 0, "falhas": 0, "motivo": "notificações desativadas no servidor"}
        dados = json.dumps(
            {"titulo": titulo, "corpo": corpo, "url": url, "tag": tag, "nivel": nivel}, ensure_ascii=False
        )
        with self._lock:
            alvos = list(self.inscricoes.values())
        ok = falhas = 0
        for inscricao in alvos:
            try:
                self._enviar(inscricao, dados, self.vapid, self.contato)
                ok += 1
            except Exception as e:  # noqa: BLE001 - rede/serviço de push
                falhas += 1
                status = getattr(getattr(e, "response", None), "status_code", None)
                if status in (404, 410):
                    self.cancelar(inscricao["endpoint"])
                with self._lock:
                    self.ultimo_erro = f"{type(e).__name__}: {str(e)[:200]}"
        with self._lock:
            self.enviadas += ok
            self.falhas += falhas
        return {"enviadas": ok, "falhas": falhas}

    def ao_evento(self, ev: Evento) -> None:
        """Ouvinte da central: dispara a notificação em segundo plano."""
        if not self.habilitado or not self.inscricoes or not deve_notificar(ev):
            return
        self._pool.submit(
            self.enviar, TITULOS[ev.tipo], ev.mensagem, DESTINO.get(ev.tipo, "/#/inicio"), f"evento-{ev.id}", ev.nivel
        )

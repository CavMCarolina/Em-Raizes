"""Chuva REAL de uma cidade: observada (Cemaden) + prevista (Open-Meteo).

- Observada: pluviômetros automáticos do Cemaden (dados abertos, sem chave).
  Usa só as estações que mandaram dado nas últimas horas e o percentil 75 do
  acumulado em 72 h (conservador, mas sem se deixar levar por um sensor isolado).
  Se ``codigo_estacao`` for informado, usa só aquele pluviômetro (o mais perto do morro).
- Prevista: soma da chuva horária das próximas 24 h no Open-Meteo (sem chave).
  O INMET seria a fonte oficial de previsão, mas a API dele exige acesso que não
  está disponível neste MVP.

Tudo com cache e tempo limite curto: se a internet falhar, o sistema mantém a
última leitura válida (ou cai para a chuva simulada) e avisa.
"""

from __future__ import annotations

import json
import statistics
import threading
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

URL_CEMADEN = "https://resources.cemaden.gov.br/graficos/interativo/getJson2.php?uf={uf}"
URL_OPEN_METEO = (
    "https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
    "&hourly=precipitation&daily=precipitation_sum&past_days=6&forecast_days=2&timezone=America%2FSao_Paulo"
)
HORAS_DADO_VALIDO = 6


@dataclass(frozen=True)
class Cidade:
    nome: str = "Petrópolis"
    uf: str = "RJ"
    codigo_ibge: int = 3303906
    latitude: float = -22.505
    longitude: float = -43.178
    codigo_estacao: int | None = None  # pluviômetro específico do Cemaden (opcional)

    @property
    def rotulo(self) -> str:
        return f"{self.nome}/{self.uf}"


@dataclass
class LeituraChuva:
    ok: bool
    chuva_72h: float = 0.0
    chuva_24h: float | None = None
    previsao_24h: float = 0.0
    estacoes_validas: int = 0
    estacao: str = ""  # nome do pluviômetro usado ou "percentil 75 de N"
    fonte_observada: str = "Cemaden"
    fonte_previsao: str = "Open-Meteo"
    atualizado_em: str = ""
    diario: list[dict] = field(default_factory=list)  # [{data, chuva_mm, tipo}] para o gráfico
    erro: str | None = None


def _baixar_json(url: str, timeout: float) -> object:
    req = urllib.request.Request(url, headers={"User-Agent": "em-raizes-mvp/0.2 (projeto academico)"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # noqa: S310 - URLs fixas https
        return json.loads(r.read().decode("utf-8"))


def _num(v) -> float | None:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _hora_cemaden(texto: str) -> datetime | None:
    try:  # formato "10/11/26 21:20", em UTC
        return datetime.strptime(texto, "%d/%m/%y %H:%M").replace(tzinfo=UTC)
    except (TypeError, ValueError):
        return None


def resumir_cemaden(estacoes: list[dict], cidade: Cidade, agora: datetime | None = None) -> dict:
    """Escolhe as estações da cidade com dado recente e calcula o acumulado representativo."""
    agora = agora or datetime.now(UTC)
    limite = agora - timedelta(hours=HORAS_DADO_VALIDO)
    da_cidade = [e for e in estacoes if e.get("codibge") == cidade.codigo_ibge]
    if cidade.codigo_estacao is not None:
        da_cidade = [e for e in da_cidade if e.get("idestacao") == cidade.codigo_estacao]
    validas = []
    for e in da_cidade:
        hora = _hora_cemaden(e.get("datahoraUltimovalor", ""))
        acc72 = _num(e.get("acc72hr"))
        if hora and hora >= limite and acc72 is not None:
            validas.append((e, acc72, _num(e.get("acc24hr"))))
    if not validas:
        raise ValueError(f"Nenhum pluviômetro do Cemaden com dado recente em {cidade.rotulo}.")
    if len(validas) == 1:
        e, acc72, acc24 = validas[0]
        return {"chuva_72h": acc72, "chuva_24h": acc24, "estacoes_validas": 1, "estacao": e.get("nomeestacao", "")}
    acc72s = sorted(v[1] for v in validas)
    acc24s = sorted(v[2] for v in validas if v[2] is not None)
    p75 = statistics.quantiles(acc72s, n=4, method="inclusive")[2]
    p75_24 = statistics.quantiles(acc24s, n=4, method="inclusive")[2] if len(acc24s) >= 2 else (acc24s or [None])[0]
    return {
        "chuva_72h": round(p75, 1),
        "chuva_24h": None if p75_24 is None else round(p75_24, 1),
        "estacoes_validas": len(validas),
        "estacao": f"percentil 75 de {len(validas)} pluviômetros",
    }


def resumir_open_meteo(
    dados: dict, agora_local: datetime | None = None, agora_utc: datetime | None = None
) -> tuple[float, list[dict]]:
    """Previsão das próximas 24 h + série diária (observada estimada e prevista) para o gráfico.

    As horas do Open-Meteo vêm no fuso pedido na URL (America/Sao_Paulo). O "agora" é calculado com o
    ``utc_offset_seconds`` da própria resposta, e não com o relógio do servidor: num container o fuso é
    UTC e a janela de 24 h ficaria 3 h adiantada (e depois das 21h o dia de hoje viraria amanhã).
    """
    horas = dados["hourly"]["time"]
    chuva = dados["hourly"]["precipitation"]
    if agora_local is None:
        deslocamento = dados.get("utc_offset_seconds")
        if deslocamento is None:  # resposta sem fuso: usa o relógio do servidor
            agora_local = datetime.now()
        else:
            agora_utc = agora_utc or datetime.now(UTC)
            agora_local = (agora_utc + timedelta(seconds=deslocamento)).replace(tzinfo=None)
    inicio = agora_local.replace(minute=0, second=0, microsecond=0)
    fim = inicio + timedelta(hours=24)
    previsao = sum((c or 0.0) for h, c in zip(horas, chuva, strict=True) if inicio <= datetime.fromisoformat(h) < fim)
    hoje = agora_local.date().isoformat()
    diario = [
        {"data": d, "chuva_mm": round(v or 0.0, 1), "tipo": "observada" if d <= hoje else "prevista"}
        for d, v in zip(dados["daily"]["time"], dados["daily"]["precipitation_sum"], strict=True)
    ]
    # o gráfico mostra 7 dias até hoje + amanhã
    passados = [x for x in diario if x["tipo"] == "observada"][-7:]
    futuros = [x for x in diario if x["tipo"] == "prevista"][:1]
    return round(previsao, 1), passados + futuros


class FonteChuvaReal:
    """Busca e guarda em cache a chuva real. Thread-safe; a atualização pode rodar em segundo plano."""

    def __init__(
        self,
        cidade: Cidade | None = None,
        validade_min: float = 10.0,
        timeout_s: float = 8.0,
        baixar: Callable[[str, float], object] = _baixar_json,
    ):
        self.cidade = cidade or Cidade()
        self.validade = timedelta(minutes=validade_min)
        self.timeout_s = timeout_s
        self._baixar = baixar
        self._lock = threading.Lock()
        self._atualizando = False
        self.ultima: LeituraChuva | None = None  # última leitura VÁLIDA
        self.ultimo_erro: str | None = None
        self._buscado_em: datetime | None = None

    def precisa_atualizar(self) -> bool:
        return self._buscado_em is None or datetime.now(UTC) - self._buscado_em >= self.validade

    def atualizar(self) -> LeituraChuva:
        """Busca agora (bloqueia por no máximo ~2x timeout). Mantém a última leitura válida se falhar."""
        with self._lock:
            self._buscado_em = datetime.now(UTC)
        try:
            estacoes = self._baixar(URL_CEMADEN.format(uf=self.cidade.uf), self.timeout_s)
            obs = resumir_cemaden(estacoes, self.cidade)  # type: ignore[arg-type]
            meteo = self._baixar(
                URL_OPEN_METEO.format(lat=self.cidade.latitude, lon=self.cidade.longitude), self.timeout_s
            )
            previsao, diario = resumir_open_meteo(meteo)  # type: ignore[arg-type]
            leitura = LeituraChuva(
                ok=True,
                previsao_24h=previsao,
                diario=diario,
                atualizado_em=datetime.now().astimezone().replace(microsecond=0).isoformat(),
                **obs,
            )
            with self._lock:
                self.ultima, self.ultimo_erro = leitura, None
            return leitura
        except Exception as e:  # noqa: BLE001 - rede, JSON, formato: tudo vira aviso
            with self._lock:
                self.ultimo_erro = f"{type(e).__name__}: {e}"
                if self.ultima:
                    return self.ultima
            return LeituraChuva(ok=False, erro=self.ultimo_erro)

    def atualizar_em_segundo_plano(self, ao_terminar: Callable[[LeituraChuva], None] | None = None) -> bool:
        """Dispara uma atualização sem travar quem chamou. Devolve False se já houver uma em andamento."""
        with self._lock:
            if self._atualizando:
                return False
            self._atualizando = True

        def tarefa():
            try:
                leitura = self.atualizar()
                if ao_terminar:
                    ao_terminar(leitura)
            finally:
                with self._lock:
                    self._atualizando = False

        threading.Thread(target=tarefa, name="chuva-real", daemon=True).start()
        return True


def faixa_da_chuva(chuva_72h: float, previsao_24h: float) -> str:
    """Traduz chuva real para o cenário equivalente (para textos e comparações)."""
    if chuva_72h >= 150 or previsao_24h >= 100:
        return "extrema"
    if chuva_72h >= 80 or previsao_24h >= 50:
        return "forte"
    if chuva_72h >= 25 or previsao_24h >= 15:
        return "moderada"
    return "seco"

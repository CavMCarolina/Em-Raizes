"""Cliente de IA generativa via OpenRouter (API compatível com a da OpenAI).

Responsabilidades:
- ler a configuração do ambiente (.env);
- chamar o modelo principal e, se ele falhar, os modelos de reserva;
- repetir com espera crescente em erros temporários (429, timeout, 5xx);
- respeitar o limite por minuto dos modelos gratuitos (``:free``);
- traduzir erros técnicos em mensagens que o usuário entende;
- transmitir a resposta aos pedaços (streaming), com as mesmas proteções.
"""

from __future__ import annotations

import os
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass, field

# Só modelos gratuitos (variante ":free" do OpenRouter, US$ 0 por token).
# Reserva 1 é de OUTRO provedor (NVIDIA): os dois Gemma gratuitos são servidos pelo Google AI Studio.
MODELO_PADRAO = "google/gemma-4-31b-it:free"
MODELOS_RESERVA_PADRAO = ["nvidia/nemotron-3.5-super-vl:free", "google/gemma-4-26b-a4b-it:free"]
OPENROUTER_URL = "https://openrouter.ai/api/v1"
# OpenRouter: modelos ":free" aceitam 20 requisições por minuto por conta (e 50 por dia sem créditos comprados).
LIMITE_GRATUITO_POR_MINUTO = 20
# Modelos de raciocínio (ex.: Nemotron) "pensam" antes de responder e gastam o max_tokens nisso: a resposta vinha
# vazia. O chat precisa de respostas curtas e rápidas, então o raciocínio fica desligado (modelos sem ele ignoram).
SEM_RACIOCINIO = {"reasoning": {"enabled": False}}

_trava_ritmo = threading.Lock()
_ultima_chamada = 0.0


def eh_gratuito(modelo: str) -> bool:
    return modelo.endswith(":free") or modelo == "openrouter/free"


def _aguardar_vez(intervalo_s: float) -> None:
    """Espaça as chamadas (de todo o processo) para não estourar o limite por minuto."""
    global _ultima_chamada
    if intervalo_s <= 0:
        return
    with _trava_ritmo:
        espera = _ultima_chamada + intervalo_s - time.monotonic()
        if espera > 0:
            time.sleep(espera)
        _ultima_chamada = time.monotonic()


@dataclass
class RespostaLLM:
    texto: str
    modelo: str
    tokens_entrada: int = 0
    tokens_saida: int = 0
    latencia_s: float = 0.0
    tentativas: list[str] = field(default_factory=list)


@dataclass
class ResultadoStream:
    """Métricas da última transmissão (streaming)."""

    texto: str = ""
    modelo: str = ""
    primeiro_pedaco_s: float | None = None  # tempo até o primeiro texto aparecer
    total_s: float = 0.0
    pedacos: int = 0
    tokens_entrada: int = 0
    tokens_saida: int = 0
    tentativas: list[str] = field(default_factory=list)


class ErroLLM(Exception):
    """Erro já traduzido para o usuário. ``codigo`` é estável para testes."""

    def __init__(self, codigo: str, mensagem: str, detalhe: str = ""):
        super().__init__(mensagem)
        self.codigo = codigo
        self.mensagem = mensagem
        self.detalhe = detalhe


MENSAGENS_ERRO = {
    "sem_chave": "Nenhuma chave de API configurada. Defina OPENROUTER_API_KEY no arquivo .env.",
    "chave_invalida": "A chave do OpenRouter foi recusada (erro 401). Gere uma nova em openrouter.ai/keys.",
    "sem_credito": "A conta do OpenRouter está sem créditos (erro 402). Use um modelo ':free' ou adicione créditos.",
    "modelo_invalido": "O modelo pedido não existe ou não está disponível no OpenRouter.",
    "limite_requisicoes": "Muitas requisições em pouco tempo (erro 429). Aguarde alguns segundos.",
    "provedor_ocupado": "O provedor gratuito deste modelo está sobrecarregado agora (erro 429). Usando o modelo reserva.",
    "tempo_esgotado": "O modelo demorou demais para responder (timeout).",
    "sem_conexao": "Não foi possível conectar ao OpenRouter. Verifique a internet.",
    "erro_servidor": "O provedor do modelo teve um erro interno (5xx). Tente de novo.",
    "resposta_vazia": "O modelo respondeu vazio.",
    "stream_interrompido": "A resposta foi interrompida no meio. O texto parcial foi mantido.",
    "desconhecido": "Erro inesperado ao chamar o modelo.",
}

# erros em que vale tentar de novo no MESMO modelo
REPETIVEIS = {"limite_requisicoes", "tempo_esgotado", "erro_servidor", "sem_conexao"}
# erros em que não adianta trocar de modelo
FATAIS = {"sem_chave", "chave_invalida"}


def classificar_erro(exc: Exception) -> str:
    """Mapeia exceções do SDK ``openai`` para códigos estáveis."""
    try:
        import openai
    except ImportError:  # pragma: no cover
        return "desconhecido"

    if isinstance(exc, openai.AuthenticationError):
        return "chave_invalida"
    if isinstance(exc, openai.RateLimitError):
        # 429 do provedor por trás do OpenRouter (ex.: Google AI Studio lotado): repetir no mesmo modelo não
        # adianta, então vai direto para a reserva. 429 da nossa conta continua "limite_requisicoes" (espera e repete).
        return "provedor_ocupado" if "provider returned error" in str(exc).lower() else "limite_requisicoes"
    if isinstance(exc, openai.APITimeoutError):
        return "tempo_esgotado"
    if isinstance(exc, openai.APIConnectionError):
        return "sem_conexao"
    if isinstance(exc, openai.NotFoundError):
        return "modelo_invalido"
    if isinstance(exc, openai.APIStatusError):
        status = getattr(exc, "status_code", 0) or 0
        texto = str(exc).lower()
        if status == 402:
            return "sem_credito"
        if status == 400 and ("model" in texto and ("valid" in texto or "exist" in texto or "not found" in texto)):
            return "modelo_invalido"
        if status >= 500:
            return "erro_servidor"
    return "desconhecido"


def _ler_reservas() -> list[str]:
    bruto = os.getenv("OPENROUTER_FALLBACK_MODELS")
    if not bruto:  # ausente ou vazio no .env -> reserva padrão
        return list(MODELOS_RESERVA_PADRAO)
    return [m.strip() for m in bruto.split(",") if m.strip()]


class ClienteLLM:
    """Wrapper fino em torno do SDK ``openai`` apontado para o OpenRouter."""

    def __init__(
        self,
        api_key: str | None = None,
        modelo: str | None = None,
        reservas: list[str] | None = None,
        timeout_s: float = 30.0,
        max_repeticoes: int = 2,
        espera_base_s: float = 1.0,
        cliente=None,
        intervalo_min_s: float | None = None,
    ):
        self.api_key = api_key if api_key is not None else os.getenv("OPENROUTER_API_KEY", "")
        self.modelo = modelo or os.getenv("OPENROUTER_MODEL") or MODELO_PADRAO
        self.reservas = reservas if reservas is not None else _ler_reservas()
        self.timeout_s = timeout_s
        self.max_repeticoes = max_repeticoes
        self.espera_base_s = espera_base_s
        self._cliente = cliente  # permite injetar um cliente falso nos testes
        self.ultimo_stream: ResultadoStream | None = None
        if intervalo_min_s is None:  # só espaça chamadas reais a modelos gratuitos (testes ficam rápidos)
            gratuito = any(eh_gratuito(m) for m in [self.modelo, *self.reservas])
            intervalo_min_s = 60 / LIMITE_GRATUITO_POR_MINUTO if gratuito and cliente is None else 0.0
        self.intervalo_min_s = intervalo_min_s

    @property
    def configurado(self) -> bool:
        return bool(self.api_key) or self._cliente is not None

    def _sdk(self):
        if self._cliente is None:
            from openai import OpenAI

            self._cliente = OpenAI(
                base_url=OPENROUTER_URL,
                api_key=self.api_key,
                timeout=self.timeout_s,
                max_retries=0,  # as repetições são controladas aqui
                default_headers={"X-Title": "Em Raizes (MVP academico)"},
            )
        return self._cliente

    def completar(
        self,
        mensagens: list[dict],
        temperatura: float = 0.3,
        max_tokens: int = 700,
        json: bool = False,
        modelo: str | None = None,
    ) -> RespostaLLM:
        if not self.configurado:
            raise ErroLLM("sem_chave", MENSAGENS_ERRO["sem_chave"])

        candidatos = [modelo or self.modelo] + [m for m in self.reservas if m != (modelo or self.modelo)]
        tentativas: list[str] = []
        ultimo: ErroLLM | None = None

        for nome in candidatos:
            for rep in range(self.max_repeticoes + 1):
                inicio = time.perf_counter()
                try:
                    kwargs = dict(
                        model=nome,
                        messages=mensagens,
                        temperature=temperatura,
                        max_tokens=max_tokens,
                        extra_body=SEM_RACIOCINIO,
                    )
                    if json:
                        kwargs["response_format"] = {"type": "json_object"}
                    _aguardar_vez(self.intervalo_min_s)
                    resp = self._sdk().chat.completions.create(**kwargs)
                    texto = (resp.choices[0].message.content or "").strip() if resp.choices else ""
                    if not texto:
                        raise ErroLLM("resposta_vazia", MENSAGENS_ERRO["resposta_vazia"])
                    uso = getattr(resp, "usage", None)
                    tentativas.append(f"{nome}: ok")
                    return RespostaLLM(
                        texto=texto,
                        modelo=getattr(resp, "model", None) or nome,
                        tokens_entrada=getattr(uso, "prompt_tokens", 0) or 0,
                        tokens_saida=getattr(uso, "completion_tokens", 0) or 0,
                        latencia_s=round(time.perf_counter() - inicio, 2),
                        tentativas=tentativas,
                    )
                except ErroLLM as e:
                    codigo, detalhe = e.codigo, e.detalhe
                except Exception as e:  # noqa: BLE001 — traduzimos qualquer erro do SDK
                    codigo, detalhe = classificar_erro(e), f"{type(e).__name__}: {e}"

                tentativas.append(f"{nome}: {codigo}")
                ultimo = ErroLLM(codigo, MENSAGENS_ERRO.get(codigo, MENSAGENS_ERRO["desconhecido"]), detalhe)
                if codigo in FATAIS:
                    ultimo.detalhe += f" | tentativas: {tentativas}"
                    raise ultimo
                if codigo in REPETIVEIS and rep < self.max_repeticoes:
                    time.sleep(self.espera_base_s * (2**rep))
                    continue
                break  # troca para o próximo modelo

        assert ultimo is not None
        ultimo.detalhe += f" | tentativas: {tentativas}"
        raise ultimo

    def transmitir(
        self,
        mensagens: list[dict],
        temperatura: float = 0.3,
        max_tokens: int = 700,
        modelo: str | None = None,
    ) -> Iterator[str]:
        """Gera a resposta aos pedaços (streaming). As métricas ficam em ``self.ultimo_stream``.

        Antes do primeiro pedaço valem as mesmas regras de ``completar`` (repetição e modelo
        reserva). Depois que o texto começou a aparecer não dá para trocar de modelo sem
        repetir o que já foi mostrado: o erro vira ``stream_interrompido`` com o texto parcial.
        """
        if not self.configurado:
            raise ErroLLM("sem_chave", MENSAGENS_ERRO["sem_chave"])
        candidatos = [modelo or self.modelo] + [m for m in self.reservas if m != (modelo or self.modelo)]
        res = ResultadoStream()
        self.ultimo_stream = res
        ultimo: ErroLLM | None = None

        for nome in candidatos:
            for rep in range(self.max_repeticoes + 1):
                _aguardar_vez(self.intervalo_min_s)
                inicio = time.perf_counter()  # depois da espera: mede só o modelo
                try:
                    fluxo = self._sdk().chat.completions.create(
                        model=nome,
                        messages=mensagens,
                        temperature=temperatura,
                        max_tokens=max_tokens,
                        stream=True,
                        stream_options={"include_usage": True},
                        extra_body=SEM_RACIOCINIO,
                    )
                    for pedaco in fluxo:
                        uso = getattr(pedaco, "usage", None)
                        if uso:
                            res.tokens_entrada = getattr(uso, "prompt_tokens", 0) or 0
                            res.tokens_saida = getattr(uso, "completion_tokens", 0) or 0
                        escolhas = getattr(pedaco, "choices", None) or []
                        texto = (getattr(escolhas[0].delta, "content", None) or "") if escolhas else ""
                        if not texto:
                            continue
                        if res.primeiro_pedaco_s is None:
                            res.primeiro_pedaco_s = round(time.perf_counter() - inicio, 2)
                            res.modelo = getattr(pedaco, "model", None) or nome
                        res.texto += texto
                        res.pedacos += 1
                        yield texto
                    if not res.texto.strip():
                        raise ErroLLM("resposta_vazia", MENSAGENS_ERRO["resposta_vazia"])
                    res.total_s = round(time.perf_counter() - inicio, 2)
                    res.tentativas.append(f"{nome}: ok")
                    return
                except ErroLLM as e:
                    codigo, detalhe = e.codigo, e.detalhe
                except Exception as e:  # noqa: BLE001
                    codigo, detalhe = classificar_erro(e), f"{type(e).__name__}: {e}"
                if res.texto:  # já mostrou parte da resposta: não dá para recomeçar em outro modelo
                    res.total_s = round(time.perf_counter() - inicio, 2)
                    res.tentativas.append(f"{nome}: stream_interrompido ({codigo})")
                    raise ErroLLM("stream_interrompido", MENSAGENS_ERRO["stream_interrompido"], detalhe)
                res.tentativas.append(f"{nome}: {codigo}")
                ultimo = ErroLLM(codigo, MENSAGENS_ERRO.get(codigo, MENSAGENS_ERRO["desconhecido"]), detalhe)
                if codigo in FATAIS:
                    raise ultimo
                if codigo in REPETIVEIS and rep < self.max_repeticoes:
                    time.sleep(self.espera_base_s * (2**rep))
                    continue
                break
        assert ultimo is not None
        ultimo.detalhe += f" | tentativas: {res.tentativas}"
        raise ultimo

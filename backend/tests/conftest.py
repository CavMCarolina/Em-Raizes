from types import SimpleNamespace

import httpx
import pytest

URL = "https://openrouter.ai/api/v1/chat/completions"


def erro_http(cls, status: int, msg: str = "erro simulado"):
    """Cria uma exceção do SDK openai como se viesse do servidor."""
    req = httpx.Request("POST", URL)
    return cls(f"{msg} ({status})", response=httpx.Response(status, request=req), body=None)


def erro_timeout():
    import openai

    return openai.APITimeoutError(request=httpx.Request("POST", URL))


class SDKFalso:
    """Imita ``OpenAI().chat.completions.create``.

    ``roteiro`` é uma lista: cada item é uma exceção (lançada) ou um texto (devolvido).
    Quando o roteiro acaba, devolve ``padrao``.
    """

    def __init__(self, roteiro=None, padrao="resposta padrão"):
        self.roteiro = list(roteiro or [])
        self.padrao = padrao
        self.chamadas: list[dict] = []
        self.chat = self
        self.completions = self

    def create(self, **kwargs):
        self.chamadas.append(kwargs)
        item = self.roteiro.pop(0) if self.roteiro else self.padrao
        if isinstance(item, Exception):
            raise item
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=item))],
            model=kwargs["model"],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20),
        )


@pytest.fixture
def analise_forte():
    from em_raizes.dominio.risco import analisar
    from em_raizes.fontes.simulador import simular_voo

    return analisar(simular_voo("forte", 42))

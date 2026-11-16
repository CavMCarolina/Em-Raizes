"""Streaming, histórico e janela de contexto do chat com o Guardião."""

import io
from types import SimpleNamespace

import openai
import pytest
from conftest import erro_http

from em_raizes.ia import prompts
from em_raizes.ia.chat_terminal import comando, responder
from em_raizes.ia.conhecimento import BaseConhecimento
from em_raizes.ia.conversa import Conversa, estimar_tokens
from em_raizes.ia.guardiao import Guardiao
from em_raizes.ia.llm import ClienteLLM, ErroLLM


def pedaco(texto=None, uso=None, modelo="m"):
    delta = SimpleNamespace(content=texto)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)] if texto is not None else [], usage=uso, model=modelo)


class SDKStream:
    """Imita o SDK com stream=True. Cada item do roteiro: lista de pedaços, exceção, ou texto (para completar)."""

    def __init__(self, roteiro):
        self.roteiro = list(roteiro)
        self.chamadas = []
        self.chat = self
        self.completions = self

    def create(self, **kw):
        self.chamadas.append(kw)
        item = self.roteiro.pop(0)
        if isinstance(item, Exception):
            raise item
        if kw.get("stream"):

            def gerar():
                for p in item:
                    if isinstance(p, Exception):
                        raise p
                    yield p

            return gerar()
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=item))],
            model=kw["model"],
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
        )


def cliente(roteiro, reservas=()):
    return ClienteLLM(
        api_key="x", modelo="principal", reservas=list(reservas), cliente=SDKStream(roteiro), espera_base_s=0
    )


# ------------------------------------------------------------------ streaming no cliente


def test_streaming_entrega_pedacos_e_mede_tempo():
    uso = SimpleNamespace(prompt_tokens=120, completion_tokens=7)
    cli = cliente([[pedaco("Olá"), pedaco(", tudo"), pedaco(" bem?"), pedaco(None, uso=uso)]])
    pedacos = list(cli.transmitir([{"role": "user", "content": "oi"}]))
    assert pedacos == ["Olá", ", tudo", " bem?"]
    r = cli.ultimo_stream
    assert r.texto == "Olá, tudo bem?" and r.pedacos == 3 and r.primeiro_pedaco_s is not None
    assert (r.tokens_entrada, r.tokens_saida) == (120, 7)
    assert cli._sdk().chamadas[0]["stream"] is True


def test_streaming_troca_de_modelo_se_falhar_antes_do_primeiro_pedaco():
    cli = cliente([erro_http(openai.NotFoundError, 404), [pedaco("resposta da reserva")]], reservas=["reserva"])
    assert "".join(cli.transmitir([{"role": "user", "content": "oi"}])) == "resposta da reserva"
    assert cli.ultimo_stream.tentativas == ["principal: modelo_invalido", "reserva: ok"]


def test_streaming_interrompido_no_meio_mantem_texto_parcial():
    cli = cliente([[pedaco("Começo da resposta"), erro_http(openai.InternalServerError, 503)]], reservas=["reserva"])
    recebidos = []
    with pytest.raises(ErroLLM) as e:
        for p in cli.transmitir([{"role": "user", "content": "oi"}]):
            recebidos.append(p)
    assert e.value.codigo == "stream_interrompido" and recebidos == ["Começo da resposta"]
    assert len(cli._sdk().chamadas) == 1  # não tenta outro modelo depois de mostrar texto


def test_streaming_vazio_vira_erro():
    cli = cliente([[pedaco(None)], [pedaco(None)]], reservas=["reserva"])
    with pytest.raises(ErroLLM) as e:
        list(cli.transmitir([{"role": "user", "content": "oi"}]))
    assert e.value.codigo == "resposta_vazia"


# ------------------------------------------------------------------ conversa com histórico


def conversa(roteiro, **kw):
    return Conversa(Guardiao(cliente(roteiro), BaseConhecimento()), contexto="ALERTA: Atenção — teste", **kw)


def test_historico_vai_para_o_modelo_com_os_papeis_certos():
    c = conversa(
        [
            [pedaco("Use o botão Enviar drone.")],
            "O botão Enviar drone funciona com chuva forte?",
            [pedaco("Sim, o drone voa mesmo com alerta.")],
        ]
    )
    c.perguntar_tudo("Como envio o drone?")
    t = c.perguntar_tudo("e com chuva forte?")
    chamadas = c.guardiao.cliente._sdk().chamadas
    reformulacao = chamadas[1]["messages"]
    assert reformulacao[0]["content"] == prompts.SYSTEM_REFORMULAR_PERGUNTA
    assert t.pergunta_busca == "O botão Enviar drone funciona com chuva forte?"
    janela = chamadas[2]["messages"]
    assert [m["role"] for m in janela] == ["system", "user", "assistant", "user"]
    assert janela[1]["content"] == "Como envio o drone?" and "CONTEXTO DO MAPEAMENTO" in janela[0]["content"]
    assert len(c.historico) == 4 and c.turnos[-1].modo == "ia"


def test_janela_de_contexto_resume_trocas_antigas():
    respostas = [[pedaco("resposta longa " * 60)] for _ in range(4)]
    c = conversa(
        [*respostas, "- Perguntou sobre o drone e o robô.", [pedaco("ok")]],
        limite_tokens_historico=800,
        turnos_recentes=1,
        usar_reformulacao=False,
    )
    for i in range(4):
        c.perguntar_tudo(f"Pergunta número {i} sobre o app Em Raízes")
    assert c.tokens_historico() > 800
    t = c.perguntar_tudo("Última pergunta sobre o mapa")
    assert t.resumiu and c.resumo == "- Perguntou sobre o drone e o robô."
    resumo_chamada = c.guardiao.cliente._sdk().chamadas[4]
    assert resumo_chamada["messages"][0]["content"] == prompts.SYSTEM_RESUMO_HISTORICO
    janela = c.guardiao.cliente._sdk().chamadas[5]["messages"]
    assert "RESUMO DA CONVERSA" in janela[0]["content"] and len(janela) == 1 + 2 + 1


def test_conversa_offline_tambem_chega_aos_pedacos_e_reformula_sem_ia():
    c = Conversa(Guardiao(ClienteLLM(api_key=""), BaseConhecimento()))
    pedacos = list(c.perguntar("Por que o botão Irrigar foi recusado?"))
    assert len(pedacos) > 5 and c.turnos[-1].modo == "offline" and "Irrigação" in "".join(pedacos)
    t = c.perguntar_tudo("e no seco?")
    assert t.pergunta_busca == "Por que o botão Irrigar foi recusado? e no seco?"


def test_erro_de_chave_cai_para_offline_e_emergencia_garante_199():
    c = conversa([erro_http(openai.AuthenticationError, 401)], usar_reformulacao=False)
    t = c.perguntar_tudo("Apareceu uma trinca nova na parede e ouvi um estalo")
    assert t.modo == "offline" and "401" in (t.aviso or "") and "199" in t.resposta
    c2 = conversa([[pedaco("Fique tranquilo.")]], usar_reformulacao=False)
    t2 = c2.perguntar_tudo("Tem água barrenta descendo o morro")
    assert t2.modo == "ia" and "199" in t2.resposta


def test_estimativa_de_tokens():
    assert estimar_tokens("a" * 400) == 100


# ------------------------------------------------------------------ chat de terminal


def test_terminal_escreve_streaming_e_rodape_e_comandos():
    c = conversa([[pedaco("Primeira"), pedaco(" resposta.")]], usar_reformulacao=False)
    saida = io.StringIO()
    responder(c, "Como envio o drone?", saida)
    texto = saida.getvalue()
    assert texto.startswith("Guardião: Primeira resposta.") and "IA · m" in texto and "janela ~" in texto
    s2 = io.StringIO()
    assert comando(c, "/tokens", s2) and "Histórico: ~" in s2.getvalue()
    assert comando(c, "/limpar", io.StringIO()) and c.historico == []
    assert comando(c, "/sair", io.StringIO()) is False

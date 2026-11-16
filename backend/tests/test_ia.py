import json

import openai
import pytest
from conftest import SDKFalso, erro_http, erro_timeout

from em_raizes.dominio.missoes import gerar_missoes
from em_raizes.dominio.risco import analisar
from em_raizes.fontes.simulador import CENARIOS, simular_voo
from em_raizes.ia.conhecimento import BaseConhecimento, tokenizar
from em_raizes.ia.guardiao import (
    Guardiao,
    PlanoAcao,
    detectar_emergencia,
    extrair_json,
    resumo_contexto,
    sms_offline,
    validar_sms,
)
from em_raizes.ia.llm import ClienteLLM, ErroLLM

# ------------------------------------------------------------------ RAG


@pytest.mark.parametrize(
    "pergunta,secao_esperada",
    [
        ("Deu erro 401, o que eu faço?", "Erro 401"),
        ("como faço um voo simulado", "Como enviar o drone"),
        ("como entro no app", "Primeiros passos"),
        ("por que o robô não está irrigando", "Irrigação"),
        ("o que é capim vetiver", "capim-vetiver"),
        ("npm não é reconhecido", "npm não é reconhecido"),
        ("o robô foi recusado com alerta_ativo", "alerta_ativo"),
        ("vi trincas na parede", "Sinais de perigo"),
        ("o que significa alerta máximo", "Níveis de alerta"),
        ("como ativo as notificações no celular", "Notificações no celular"),
        ("de onde vem a chuva do app", "Chuva real"),
        ("posso mandar uma foto da trinca para a IA", "Analisar foto"),
    ],
)
def test_busca_no_manual_acha_secao_certa(pergunta, secao_esperada):
    base = BaseConhecimento()
    titulos = [t.titulo for t, _ in base.buscar(pergunta, k=3)]
    assert any(secao_esperada.lower() in t.lower() for t in titulos), titulos


def test_tokenizacao_tira_acentos_plural_e_stopwords():
    assert tokenizar("As trincas nas paredes e as missões") == ["trinca", "parede", "missao"]


# ------------------------------------------------------------------ cliente LLM


def test_sem_chave_gera_erro_amigavel():
    with pytest.raises(ErroLLM) as e:
        ClienteLLM(api_key="").completar([{"role": "user", "content": "oi"}])
    assert e.value.codigo == "sem_chave"


def test_chave_invalida_nao_tenta_outros_modelos():
    sdk = SDKFalso([erro_http(openai.AuthenticationError, 401)])
    cli = ClienteLLM(api_key="x", modelo="a", reservas=["b"], cliente=sdk, espera_base_s=0)
    with pytest.raises(ErroLLM) as e:
        cli.completar([{"role": "user", "content": "oi"}])
    assert e.value.codigo == "chave_invalida"
    assert len(sdk.chamadas) == 1


def test_429_repete_com_espera_e_depois_responde():
    sdk = SDKFalso([erro_http(openai.RateLimitError, 429), "ok depois de esperar"])
    cli = ClienteLLM(api_key="x", modelo="a", reservas=[], cliente=sdk, espera_base_s=0)
    r = cli.completar([{"role": "user", "content": "oi"}])
    assert r.texto == "ok depois de esperar"
    assert r.tentativas == ["a: limite_requisicoes", "a: ok"]


def test_429_do_provedor_vai_direto_para_a_reserva_sem_raciocinio():
    lotado = erro_http(openai.RateLimitError, 429, "Provider returned error")
    sdk = SDKFalso([lotado, "resposta da reserva"])
    cli = ClienteLLM(api_key="x", modelo="a", reservas=["b"], cliente=sdk, espera_base_s=0)
    r = cli.completar([{"role": "user", "content": "oi"}])
    assert r.tentativas == ["a: provedor_ocupado", "b: ok"]  # sem repetir no modelo lotado
    assert all(c["extra_body"] == {"reasoning": {"enabled": False}} for c in sdk.chamadas)


def test_modelo_invalido_cai_para_reserva():
    sdk = SDKFalso([erro_http(openai.NotFoundError, 404), "resposta da reserva"])
    cli = ClienteLLM(api_key="x", modelo="nao-existe", reservas=["reserva"], cliente=sdk, espera_base_s=0)
    r = cli.completar([{"role": "user", "content": "oi"}])
    assert r.modelo == "reserva"
    assert [c["model"] for c in sdk.chamadas] == ["nao-existe", "reserva"]


def test_timeout_e_resposta_vazia_esgotam_e_informam_tentativas():
    sdk = SDKFalso([erro_timeout(), erro_timeout(), ""])
    cli = ClienteLLM(api_key="x", modelo="a", reservas=["b"], cliente=sdk, max_repeticoes=1, espera_base_s=0)
    with pytest.raises(ErroLLM) as e:
        cli.completar([{"role": "user", "content": "oi"}])
    assert e.value.codigo == "resposta_vazia"
    assert "a: tempo_esgotado" in e.value.detalhe and "b: resposta_vazia" in e.value.detalhe


def test_sem_credito_402():
    sdk = SDKFalso([erro_http(openai.APIStatusError, 402), erro_http(openai.APIStatusError, 402)])
    cli = ClienteLLM(api_key="x", modelo="a", reservas=["b"], cliente=sdk, espera_base_s=0)
    with pytest.raises(ErroLLM) as e:
        cli.completar([{"role": "user", "content": "oi"}])
    assert e.value.codigo == "sem_credito"


def test_modelos_padrao_sao_todos_gratuitos():
    from em_raizes.ia.llm import MODELO_PADRAO, MODELOS_RESERVA_PADRAO, eh_gratuito

    assert all(eh_gratuito(m) for m in [MODELO_PADRAO, *MODELOS_RESERVA_PADRAO])


def test_modelo_gratuito_espaca_as_chamadas(monkeypatch):
    import em_raizes.ia.llm as llm

    esperas: list[float] = []
    monkeypatch.setattr(llm.time, "sleep", esperas.append)
    monkeypatch.setattr(llm, "_ultima_chamada", 0.0)
    assert ClienteLLM(api_key="x", modelo="m:free", reservas=[]).intervalo_min_s == 3.0  # 60 s / 20 req
    assert ClienteLLM(api_key="x", modelo="m-pago", reservas=[]).intervalo_min_s == 0
    cli = ClienteLLM(api_key="x", modelo="m:free", reservas=[], cliente=SDKFalso(), intervalo_min_s=3.0)
    cli.completar([{"role": "user", "content": "oi"}])
    cli.completar([{"role": "user", "content": "oi"}])
    assert len(esperas) == 1 and 0 < esperas[0] <= 3.0


# ------------------------------------------------------------------ guardião


@pytest.fixture
def contexto(analise_forte):
    return resumo_contexto(analise_forte, gerar_missoes(analise_forte))


def test_contexto_tem_informacoes_essenciais(contexto):
    for trecho in ["SIMULADOS", "ALERTA:", "RISCO EM 24 H", "PONTO DE APOIO", "ROBÔ:", "L"]:
        assert trecho in contexto


def test_guardiao_offline_responde_com_manual(contexto):
    g = Guardiao(ClienteLLM(api_key=""))
    r = g.responder("Como envio o drone?", contexto)
    assert r.modo == "offline"
    assert "Enviar drone" in r.texto
    assert r.fontes


def test_guardiao_online_envia_manual_e_contexto_ao_modelo(contexto):
    sdk = SDKFalso(["Resposta da IA"])
    g = Guardiao(ClienteLLM(api_key="x", modelo="m", reservas=[], cliente=sdk))
    r = g.responder(
        "Deu erro 401", contexto, historico=[{"role": "user", "content": "oi"}, {"role": "assistant", "content": "olá"}]
    )
    assert r.modo == "ia" and r.texto == "Resposta da IA"
    msgs = sdk.chamadas[0]["messages"]
    assert msgs[0]["role"] == "system"
    assert "Erro 401" in msgs[0]["content"] and "CONTEXTO DO MAPEAMENTO" in msgs[0]["content"]
    assert [m["role"] for m in msgs[1:]] == ["user", "assistant", "user"]


def test_guardiao_cai_para_offline_quando_api_falha(contexto):
    sdk = SDKFalso([erro_http(openai.AuthenticationError, 401)])
    g = Guardiao(ClienteLLM(api_key="x", modelo="m", reservas=[], cliente=sdk))
    r = g.responder("Como faço um voo?", contexto)
    assert r.modo == "offline" and "401" in (r.aviso or "")


def test_camada_de_seguranca_garante_199(contexto):
    sdk = SDKFalso(["Fique tranquilo, deve ser normal."])
    g = Guardiao(ClienteLLM(api_key="x", modelo="m", reservas=[], cliente=sdk))
    r = g.responder("Apareceu uma trinca nova na parede e ouvi um estalo", contexto)
    assert "199" in r.texto
    assert detectar_emergencia("água barrenta descendo")
    assert not detectar_emergencia("como mudo o cenário de chuva?")


@pytest.mark.parametrize("cenario", list(CENARIOS))
def test_sms_offline_respeita_regras(cenario):
    a = analisar(simular_voo(cenario, 42))
    assert validar_sms(sms_offline(a)) == []


def test_sms_da_ia_e_corrigido_quando_quebra_regras(analise_forte):
    longo = "ALERTA: " + "chuva muito forte " * 15 + "Defesa Civil 199"
    sdk = SDKFalso([longo, "ALERTA: risco no setor Meio-Leste. Prepare-se para sair. Defesa Civil 199"])
    g = Guardiao(ClienteLLM(api_key="x", modelo="m", reservas=[], cliente=sdk))
    r = g.gerar_sms(analise_forte)
    assert r.modo == "ia" and validar_sms(r.texto) == []
    assert len(sdk.chamadas) == 2


def test_extrair_json_aceita_cercas_e_texto_em_volta():
    assert extrair_json('```json\n{"a": 1}\n```') == {"a": 1}
    assert extrair_json('Aqui está: {"a": 2} espero ter ajudado') == {"a": 2}
    with pytest.raises(ValueError):
        extrair_json("sem json aqui")


def test_plano_json_valido_via_ia(analise_forte):
    plano = {
        "nivel_alerta": analise_forte.alerta.nivel,
        "resumo": "Preparar evacuação",
        "acoes": [
            {
                "prioridade": 1,
                "tipo": "evacuacao",
                "local": "L06C17",
                "descricao": "Preparar saída",
                "responsavel": "defesa_civil",
            },
            {
                "prioridade": 2,
                "tipo": "inspecao",
                "local": "L09C23",
                "descricao": "Vistoriar fissura",
                "responsavel": "defesa_civil",
            },
            {
                "prioridade": 3,
                "tipo": "comunicacao",
                "local": "Meio-Leste",
                "descricao": "Avisar moradores",
                "responsavel": "agente_comunitario",
            },
        ],
    }
    sdk = SDKFalso(["isto não é json", json.dumps(plano)])
    g = Guardiao(ClienteLLM(api_key="x", modelo="m", reservas=[], cliente=sdk))
    p, r = g.gerar_plano(analise_forte)
    assert r.modo == "ia" and isinstance(p, PlanoAcao) and len(p.acoes) == 3
    assert sdk.chamadas[0]["response_format"] == {"type": "json_object"}


def test_plano_offline_sempre_valido():
    for c in CENARIOS:
        a = analisar(simular_voo(c, 42))
        p, r = Guardiao(ClienteLLM(api_key="")).gerar_plano(a, gerar_missoes(a))
        assert p.nivel_alerta == a.alerta.nivel and 3 <= len(p.acoes) <= 6
        if a.alerta.celulas_evacuar:
            assert p.acoes[0].tipo == "evacuacao"

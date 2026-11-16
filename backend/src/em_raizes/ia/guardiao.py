"""Guardião: helper de IA generativa do Em Raízes.

Junta três coisas a cada pergunta:
1. trechos relevantes do manual (``BaseConhecimento``);
2. um resumo do mapeamento atual (``resumo_contexto``);
3. o histórico curto da conversa.

Se a IA não estiver disponível (sem chave, sem crédito, erro), responde em
"modo offline" com regras simples — o app nunca fica sem resposta.
Uma camada determinística de segurança garante a orientação de emergência.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Literal

import pandas as pd
from pydantic import BaseModel, Field, ValidationError

from ..config import NOME_APP_PADRAO
from ..dominio.missoes import resumo_missoes
from ..dominio.modelos import CENARIOS, PONTO_DE_APOIO
from ..dominio.risco import Analise, explicar_celula
from . import prompts
from .conhecimento import BaseConhecimento, normalizar
from .llm import ClienteLLM, ErroLLM

TELEFONES = "Defesa Civil 199 · Bombeiros 193"

PALAVRAS_EMERGENCIA = [
    "trinca",
    "rachadura",
    "racha",
    "estalo",
    "estalando",
    "emperr",
    "inclinad",
    "agua barrenta",
    "desaband",
    "deslizando",
    "desmoron",
    "socorro",
    "soterr",
    "sair de casa",
    "evacuar",
    "barulho de terra",
    "minando",
]


PALAVRAS_OBRA = ["arrimo", "contencao", "corte de barranco", "cortar o barranco", "corte de talude", "aterrar"]


def detectar_emergencia(texto: str) -> bool:
    t = normalizar(texto)
    return any(p in t for p in PALAVRAS_EMERGENCIA)


# --------------------------------------------------------------------------- contexto


def resumo_contexto(analise: Analise, missoes: pd.DataFrame | None = None, max_celulas: int = 5) -> str:
    """Texto compacto com o estado do voo atual, para o prompt."""
    m, e, al, df = analise.mapa, analise.estatisticas, analise.alerta, analise.df
    linhas = [
        f"VOO: {m.voo_id} em {m.data_voo:%d/%m/%Y %H:%M} (DADOS SIMULADOS)",
        f"CENÁRIO: {m.nome_cenario} — chuva 72 h: {m.chuva_72h:.0f} mm; previsão 24 h: {m.previsao_24h:.0f} mm",
        f"ÁREA: {m.linhas}x{m.colunas} células de 10 m ({e['area_ha']:.1f} ha); {e['casas']} casas; "
        f"~{e['moradores']:.0f} moradores estimados",
        f"ALERTA: {al.titulo} — {al.mensagem} Ação: {al.acao}",
        f"PONTO DE APOIO: {PONTO_DE_APOIO}",
        "RISCO AGORA (nº de células): " + ", ".join(f"{k} {v}" for k, v in e["por_classe"].items()),
        "RISCO EM 24 H (nº de células): " + ", ".join(f"{k} {v}" for k, v in e["por_classe_24h"].items()),
    ]
    if al.celulas_evacuar:
        ev = df[df["celula"].isin(al.celulas_evacuar)]
        lista = ", ".join(
            f"{r.celula} ({r.setor}, {r.casas} casa{'s' if r.casas > 1 else ''})" for r in ev.head(12).itertuples()
        )
        extra = f" e mais {len(ev) - 12}" if len(ev) > 12 else ""
        linhas.append(f"CASAS A EVACUAR/PREPARAR: {lista}{extra}")

    top = df.sort_values("risco_24h", ascending=False).head(max_celulas)
    linhas.append("CÉLULAS MAIS PERIGOSAS (próximas 24 h):")
    for r in top.itertuples():
        linhas.append(
            f"- {r.celula} ({r.setor}): agora {r.risco:.0f} {r.classe_risco}, 24 h {r.risco_24h:.0f} "
            f"{r.classe_risco_24h}; declividade {r.declividade_graus:.0f}°, umidade {r.umidade_pct:.0f}%, "
            f"vegetação {r.cobertura_vegetal:.0%}, solo {r.tipo_solo}, casas {r.casas}, "
            f"fissura {'sim' if r.fissura_detectada else 'não'}"
        )
    linhas.append(
        f"VISÃO COMPUTACIONAL: {e['fissuras']} fissuras, {e['vazamentos']} vazamentos, "
        f"{int((df['confianca_visao'] < 0.7).sum())} células com baixa confiança"
    )
    linhas.append(
        f"PLANTIO: {e['celulas_plantio']} células ({e['mudas']} mudas de capim-vetiver; "
        f"{e['celulas_plantio_manual']} só com equipe técnica). IRRIGAÇÃO: {e['celulas_irrigar']} células "
        f"({e['litros']:.0f} L)."
    )
    if missoes is not None:
        r = resumo_missoes(missoes)
        linhas.append(
            f"ROBÔ: {r['total']} missões ({r['plantio']} plantio, {r['irrigacao']} irrigação, "
            f"{r['inspecao']} inspeção), ~{r['horas']} h de trabalho, {r['viagens']} viagens; "
            f"{r['suspensas']} suspensas por alerta"
        )
    return "\n".join(linhas)


# --------------------------------------------------------------------------- respostas


@dataclass
class RespostaGuardiao:
    texto: str
    modo: Literal["ia", "offline"]
    modelo: str | None = None
    fontes: list[str] = field(default_factory=list)
    aviso: str | None = None
    tokens: int = 0
    latencia_s: float = 0.0


class AcaoPlano(BaseModel):
    prioridade: int = Field(ge=1, le=5)
    tipo: Literal["evacuacao", "plantio", "irrigacao", "inspecao", "comunicacao", "drenagem"]
    local: str = Field(min_length=1)
    descricao: str = Field(min_length=3, max_length=220)
    responsavel: Literal["defesa_civil", "robo_jardineiro", "agente_comunitario", "moradores"]


class PlanoAcao(BaseModel):
    nivel_alerta: Literal["normal", "atencao", "alerta", "alerta_maximo"]
    resumo: str = Field(min_length=3, max_length=300)
    acoes: list[AcaoPlano] = Field(min_length=1, max_length=8)


def extrair_json(texto: str) -> dict:
    """Aceita JSON puro, dentro de ```json ...``` ou com texto em volta."""
    t = texto.strip()
    cerca = re.search(r"```(?:json)?\s*(.*?)```", t, re.DOTALL)
    if cerca:
        t = cerca.group(1).strip()
    if not t.startswith("{"):
        ini, fim = t.find("{"), t.rfind("}")
        if ini == -1 or fim <= ini:
            raise ValueError("Nenhum objeto JSON encontrado na resposta.")
        t = t[ini : fim + 1]
    return json.loads(t)


def _setores_principais(analise: Analise, n: int = 2) -> str:
    df = analise.df
    if analise.alerta.celulas_evacuar:
        base = df[df["celula"].isin(analise.alerta.celulas_evacuar)]
    else:
        base = df.sort_values("risco_24h", ascending=False).head(10)
    setores = base["setor"].value_counts().head(n).index.tolist()
    return " e ".join(setores) if setores else "do morro"


def sms_offline(analise: Analise) -> str:
    setor = _setores_principais(analise)
    nivel = analise.alerta.nivel
    if nivel == "alerta_maximo":
        return f"ALERTA MÁXIMO: risco de deslizamento no setor {setor}. Saia de casa agora e vá para a Escola Municipal. Defesa Civil 199"
    if nivel == "alerta":
        return f"ALERTA: chuva pode causar deslizamento no setor {setor}. Separe documentos e remédios e fique pronto para sair. Defesa Civil 199"
    if nivel == "atencao":
        return "ATENÇÃO: chuva no morro. Observe trincas e água barrenta. Se notar algo, saia de casa. Defesa Civil 199"
    return f"{NOME_APP_PADRAO}: sem risco alto agora. Mantenha canaletas limpas e não jogue lixo na encosta. Defesa Civil 199"


def validar_sms(texto: str) -> list[str]:
    problemas = []
    if len(texto) > 160:
        problemas.append(f"tem {len(texto)} caracteres (máximo 160)")
    if "199" not in texto:
        problemas.append("não termina com 'Defesa Civil 199'")
    if not re.match(rf"^(ALERTA MÁXIMO|ALERTA|ATENÇÃO|{re.escape(NOME_APP_PADRAO)})", texto):
        problemas.append("não começa com o nível do alerta")
    return problemas


def plano_offline(analise: Analise, missoes: pd.DataFrame | None) -> PlanoAcao:
    al, df = analise.alerta, analise.df
    acoes: list[dict] = []
    if al.celulas_evacuar:
        acoes.append(
            {
                "prioridade": 1,
                "tipo": "evacuacao",
                "local": ", ".join(al.celulas_evacuar[:6]),
                "descricao": (
                    f"Retirar ~{al.pessoas_em_risco:.0f} pessoas e levar ao ponto de apoio."
                    if al.nivel == "alerta_maximo"
                    else f"Preparar saída preventiva de ~{al.pessoas_em_risco:.0f} pessoas; sair se a chuva continuar."
                ),
                "responsavel": "defesa_civil",
            }
        )
        acoes.append(
            {
                "prioridade": 1,
                "tipo": "comunicacao",
                "local": f"setor {_setores_principais(analise)}",
                "descricao": "Avisar casa a casa e por SMS; conferir quem precisa de ajuda para sair.",
                "responsavel": "agente_comunitario",
            }
        )
    fiss = df[df["fissura_detectada"]].sort_values("risco", ascending=False)
    if not fiss.empty:
        acoes.append(
            {
                "prioridade": 2,
                "tipo": "inspecao",
                "local": ", ".join(fiss["celula"].head(5)),
                "descricao": "Vistoriar fissuras detectadas pela visão computacional.",
                "responsavel": "defesa_civil",
            }
        )
    vaz = df[df["vazamento"]]
    if not vaz.empty:
        acoes.append(
            {
                "prioridade": 3,
                "tipo": "drenagem",
                "local": ", ".join(vaz["celula"].head(5)),
                "descricao": "Consertar vazamentos de água/esgoto que encharcam o solo.",
                "responsavel": "moradores",
            }
        )
    robo_liberado = al.nivel in ("normal", "atencao")
    plantio = df[df["plantio_recomendado"]].sort_values("prioridade_plantio", ascending=False)
    if not plantio.empty:
        acoes.append(
            {
                "prioridade": 3 if robo_liberado else 5,
                "tipo": "plantio",
                "local": ", ".join(plantio["celula"].head(5)),
                "descricao": (
                    "Plantar capim-vetiver em linhas de nível."
                    if robo_liberado
                    else "Plantio de capim-vetiver adiado até o fim do alerta."
                ),
                "responsavel": "robo_jardineiro",
            }
        )
    irr = df[df["precisa_irrigar"]]
    if not irr.empty and robo_liberado:
        acoes.append(
            {
                "prioridade": 4,
                "tipo": "irrigacao",
                "local": ", ".join(irr["celula"].head(5)),
                "descricao": f"Irrigar mudas em {len(irr)} células secas (meta 25% de umidade).",
                "responsavel": "robo_jardineiro",
            }
        )
    if len(acoes) < 3:
        acoes.append(
            {
                "prioridade": 4,
                "tipo": "comunicacao",
                "local": "toda a comunidade",
                "descricao": "Orientar moradores sobre sinais de perigo e o cadastro no SMS 40199.",
                "responsavel": "agente_comunitario",
            }
        )
    return PlanoAcao(nivel_alerta=al.nivel, resumo=f"{al.titulo}: {al.mensagem}"[:300], acoes=acoes[:6])


# --------------------------------------------------------------------------- guardião


class Guardiao:
    def __init__(self, cliente: ClienteLLM | None = None, base: BaseConhecimento | None = None):
        self.cliente = cliente or ClienteLLM()
        self.base = base or BaseConhecimento()

    @property
    def online(self) -> bool:
        return self.cliente.configurado

    # ---- chat
    def responder(self, pergunta: str, contexto: str = "", historico: list[dict] | None = None) -> RespostaGuardiao:
        manual, fontes = self.base.contexto(pergunta, k=3)
        emergencia = detectar_emergencia(pergunta)
        aviso = None

        if self.online:
            sistema = (
                f"{prompts.SYSTEM_GUARDIAO}\n\n### MANUAL (trechos relevantes)\n{manual}"
                f"\n\n### CONTEXTO DO MAPEAMENTO ATUAL\n{contexto or '(nenhum voo carregado)'}"
            )
            msgs = [{"role": "system", "content": sistema}]
            for h in (historico or [])[-6:]:
                if h.get("role") in ("user", "assistant") and h.get("content"):
                    msgs.append({"role": h["role"], "content": h["content"]})
            msgs.append({"role": "user", "content": pergunta})
            try:
                r = self.cliente.completar(msgs, temperatura=0.3, max_tokens=500)
                texto = r.texto
                if emergencia and "199" not in texto:
                    texto = self._prefixo_emergencia() + texto
                return RespostaGuardiao(
                    texto, "ia", r.modelo, fontes, None, r.tokens_entrada + r.tokens_saida, r.latencia_s
                )
            except ErroLLM as e:
                aviso = e.mensagem

        texto = self._responder_offline(pergunta, contexto, manual, fontes, emergencia)
        return RespostaGuardiao(texto, "offline", None, fontes, aviso)

    @staticmethod
    def _prefixo_emergencia() -> str:
        return f"**Emergência — se isso está acontecendo agora:** saia para um local seguro e ligue para a {TELEFONES}.\n\n"

    def _responder_offline(self, pergunta, contexto, manual, fontes, emergencia) -> str:
        p = normalizar(pergunta)
        partes = ["*(modo offline — respostas por regras e pelo manual, sem IA generativa)*\n"]
        if emergencia:
            partes.append(self._prefixo_emergencia())
        if any(w in p for w in PALAVRAS_OBRA):
            partes.append(
                "**Atenção:** obras de contenção (muro de arrimo, corte de barranco, aterro) precisam de projeto de engenheiro. "
                "Não faça sozinho: procure a Defesa Civil (199) ou a prefeitura para uma vistoria.\n"
            )

        def linha_ctx(prefixo: str) -> str | None:
            achadas = [linha for linha in contexto.splitlines() if linha.startswith(prefixo)]
            return "\n- ".join(achadas[:5]) if achadas else None

        sobre_estado = any(w in p for w in ["risco", "perigo", "alerta", "evacu", "sair", "casa", "situacao", "agora"])
        sobre_robo = any(
            w in p for w in ["plant", "robo", "missao", "capim", "muda", "vetiver", "drone", "frota", "fazendo"]
        )
        sobre_agua = any(w in p for w in ["irrig", "regar", "rega", "agua", "seco"])
        sobre_erro = any(w in p for w in ["erro", "401", "402", "429", "nao funciona", "problema", "chave", "offline"])

        if contexto and sobre_estado and not sobre_erro:
            for pref in ["ALERTA:", "CASAS A EVACUAR", "RISCO EM 24 H", "PONTO DE APOIO:"]:
                achado = linha_ctx(pref)
                if achado:
                    partes.append(f"- {achado}")
        if contexto and sobre_robo and not sobre_erro:
            for pref in ["FROTA:", "ROBÔ LIBERADO:", "COMANDO ", "AÇÃO SUGERIDA", "PLANTIO:"]:
                achado = linha_ctx(pref)
                if achado:
                    partes.append(f"- {achado}")
        if contexto and sobre_agua and not sobre_erro:
            achado = linha_ctx("PLANTIO:")
            if achado:
                partes.append(f"- {achado}")

        achados = self.base.buscar(pergunta, k=1)
        if achados:
            trecho = achados[0][0]
            partes.append(f"\n**Do manual — {trecho.titulo}:**\n{trecho.texto}")
        elif len(partes) == 1:
            partes.append(
                "Não encontrei isso no manual. Posso ajudar com: como fazer um voo simulado, ler o mapa de risco, "
                "níveis de alerta, missões do robô, irrigação, visão do solo e erros comuns."
            )
        return "\n".join(partes)

    # ---- tarefas específicas
    def explicar_celula(self, analise: Analise, celula: str) -> RespostaGuardiao:
        info = explicar_celula(analise, celula)
        r = analise.df[analise.df["celula"] == celula].iloc[0]
        dados = {
            "celula": celula,
            "setor": r["setor"],
            "indice_risco": float(r["risco"]),
            "classe": r["classe_risco"],
            "indice_24h": float(r["risco_24h"]),
            "tendencia": r["tendencia"],
            "declividade_graus": float(r["declividade_graus"]),
            "umidade_pct": float(r["umidade_pct"]),
            "cobertura_vegetal_pct": round(float(r["cobertura_vegetal"]) * 100),
            "tipo_solo": r["tipo_solo"],
            "casas": int(r["casas"]),
            "fissura_detectada": bool(r["fissura_detectada"]),
            "vazamento": bool(r["vazamento"]),
            "pontos_por_fator": info["contribuicao_pts"],
            "chuva_72h_mm": analise.mapa.chuva_72h,
        }
        if self.online:
            try:
                resp = self.cliente.completar(
                    [
                        {"role": "system", "content": prompts.SYSTEM_LAUDO},
                        {"role": "user", "content": json.dumps(dados, ensure_ascii=False)},
                    ],
                    temperatura=0.2,
                    max_tokens=350,
                )
                return RespostaGuardiao(
                    resp.texto,
                    "ia",
                    resp.modelo,
                    ["SYSTEM_LAUDO"],
                    None,
                    resp.tokens_entrada + resp.tokens_saida,
                    resp.latencia_s,
                )
            except ErroLLM as e:
                aviso = e.mensagem
        else:
            aviso = None

        contrib = sorted(info["contribuicao_pts"].items(), key=lambda kv: kv[1], reverse=True)[:2]
        nomes = {
            "declividade": "inclinação do terreno",
            "saturacao": "solo encharcado",
            "chuva": "chuva acumulada",
            "vegetacao": "falta de vegetação",
            "solo": "tipo de solo",
            "sinais": "sinais visíveis (fissuras/erosão)",
        }
        acao1 = (
            "Acionar a Defesa Civil (199) para vistoria."
            if r["casas"] > 0 and r["classe_risco"] in ("alto", "critico")
            else "Plantar capim-vetiver e manter canaletas limpas."
        )
        texto = (
            f"**Risco: {r['classe_risco']} ({r['risco']:.0f}/100), tendência {r['tendencia']}**\n\n"
            f"**Por quê:** os fatores que mais pesam são {nomes[contrib[0][0]]} ({contrib[0][1]:.0f} pts) e "
            f"{nomes[contrib[1][0]]} ({contrib[1][1]:.0f} pts). Declividade {r['declividade_graus']:.0f}°, "
            f"umidade {r['umidade_pct']:.0f}%.\n\n"
            f"**O que observar:** trincas novas no chão ou nas paredes e água barrenta descendo o morro.\n\n"
            f"**O que fazer:** {acao1} Não jogar água nem lixo na encosta."
        )
        return RespostaGuardiao(texto, "offline", None, ["regras"], aviso)

    def gerar_sms(self, analise: Analise) -> RespostaGuardiao:
        dados = {
            "nivel": analise.alerta.nivel,
            "mensagem": analise.alerta.mensagem,
            "setores": _setores_principais(analise),
            "ponto_de_apoio": "Escola Municipal",
            "casas": analise.alerta.casas_em_risco,
        }
        aviso = None
        if self.online:
            msgs = [
                {"role": "system", "content": prompts.SYSTEM_ALERTA_SMS},
                {"role": "user", "content": json.dumps(dados, ensure_ascii=False)},
            ]
            try:
                for _ in range(2):  # 1 tentativa + 1 correção
                    resp = self.cliente.completar(msgs, temperatura=0.2, max_tokens=120)
                    texto = resp.texto.strip().strip('"')
                    problemas = validar_sms(texto)
                    if not problemas:
                        return RespostaGuardiao(
                            texto,
                            "ia",
                            resp.modelo,
                            ["SYSTEM_ALERTA_SMS"],
                            None,
                            resp.tokens_entrada + resp.tokens_saida,
                            resp.latencia_s,
                        )
                    msgs += [
                        {"role": "assistant", "content": texto},
                        {"role": "user", "content": "Corrija: o SMS " + "; ".join(problemas) + ". Reescreva."},
                    ]
                aviso = "A IA não respeitou as regras do SMS; usei o modelo pronto."
            except ErroLLM as e:
                aviso = e.mensagem
        return RespostaGuardiao(sms_offline(analise), "offline", None, ["modelo pronto"], aviso)

    def gerar_plano(self, analise: Analise, missoes: pd.DataFrame | None = None) -> tuple[PlanoAcao, RespostaGuardiao]:
        contexto = resumo_contexto(analise, missoes)
        aviso = None
        if self.online:
            msgs = [
                {"role": "system", "content": prompts.SYSTEM_PLANO_JSON},
                {"role": "user", "content": f"nivel_alerta: {analise.alerta.nivel}\n\n{contexto}"},
            ]
            try:
                for _ in range(2):
                    resp = self.cliente.completar(msgs, temperatura=0.1, max_tokens=900, json=True)
                    try:
                        plano = PlanoAcao.model_validate(extrair_json(resp.texto))
                        if plano.nivel_alerta != analise.alerta.nivel:
                            raise ValueError(f"nivel_alerta deveria ser {analise.alerta.nivel}")
                        return plano, RespostaGuardiao(
                            resp.texto,
                            "ia",
                            resp.modelo,
                            ["SYSTEM_PLANO_JSON"],
                            None,
                            resp.tokens_entrada + resp.tokens_saida,
                            resp.latencia_s,
                        )
                    except (ValueError, ValidationError) as err:
                        msgs += [
                            {"role": "assistant", "content": resp.texto},
                            {
                                "role": "user",
                                "content": f"JSON inválido: {str(err)[:400]}. Responda só o JSON corrigido.",
                            },
                        ]
                aviso = "A IA devolveu JSON inválido duas vezes; usei o plano por regras."
            except ErroLLM as e:
                aviso = e.mensagem
        plano = plano_offline(analise, missoes)
        return plano, RespostaGuardiao(plano.model_dump_json(indent=2), "offline", None, ["regras"], aviso)


def nome_cenario(chave: str) -> str:
    return CENARIOS[chave]["nome"]

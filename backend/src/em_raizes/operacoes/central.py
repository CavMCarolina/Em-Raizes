"""Central de operações: recebe comandos do administrador, aplica as
regras de segurança, simula a execução do drone e do robô e registra tudo.

A execução é simulada por tempo: cada comando tem uma duração e o progresso é
calculado a partir do relógio sempre que alguém consulta o estado (não há
threads em segundo plano). Nos testes o relógio é injetado.
"""

from __future__ import annotations

import logging
import random
import threading
from collections import deque
from collections.abc import Callable
from datetime import datetime, timedelta

import pandas as pd

from ..dominio.missoes import gerar_missoes, resumo_missoes
from ..dominio.modelos import CENARIO_REAL, CENARIOS, TAMANHO_CELULA_M
from ..dominio.risco import (
    DECLIVIDADE_MAX_ROBO,
    NIVEIS_ALERTA,
    UMIDADE_ALVO,
    Analise,
    analisar,
)
from ..fontes.chuva import FonteChuvaReal, LeituraChuva, faixa_da_chuva
from ..fontes.simulador import MundoSimulado
from .modelos import Comando, Dispositivo, Evento, Origem, Posicao, Recomendacao, TipoComando

DRONE, ROBO = "DRN-01", "ROB-01"

# durações em segundos (multiplicadas pela escala de tempo)
DURACAO_VOO_S = 12.0
DURACAO_POR_CELULA_S = {"plantio": 1.2, "irrigacao": 0.6, "inspecao": 1.5}
DURACAO_BASE_S = {"plantio": 6.0, "irrigacao": 4.0, "inspecao": 4.0}
CONSUMO_BATERIA = {"voo_drone": 25.0, "plantio": 2.0, "irrigacao": 1.5, "inspecao": 1.0}  # robô: por célula
BATERIA_MINIMA = {"drone": 30.0, "robo": 20.0}
RECARGA_POR_S = 1.0  # % por segundo na base
MAX_CELULAS_PADRAO = {"plantio": 8, "irrigacao": 10, "inspecao": 5}
VOO_DESATUALIZADO_MIN = 30
DIFERENCA_CHUVA_MM = 10  # mudança de chuva real que pede um novo voo
ORDEM_FAIXA = {"seco": 0, "moderada": 1, "forte": 2, "extrema": 3}

log = logging.getLogger("em_raizes.central")


class ComandoRecusado(Exception):
    """O comando foi registrado como recusado (com código e motivo)."""

    def __init__(self, comando: Comando):
        super().__init__(comando.motivo)
        self.comando = comando


def _agora() -> datetime:
    return datetime.now().astimezone().replace(microsecond=0)


class CentralOperacoes:
    def __init__(
        self,
        fonte: MundoSimulado,
        relogio: Callable[[], datetime] = _agora,
        escala_tempo: float = 1.0,
        semente: int = 7,
        chuva: FonteChuvaReal | None = None,
    ):
        self.fonte = fonte
        self.chuva = chuva  # chuva real (Cemaden + previsão); None = só simulação
        self._ouvintes: list[Callable[[Evento], None]] = []
        self.relogio = relogio
        self.escala = max(escala_tempo, 0.0)
        self._lock = threading.RLock()
        self._rng = random.Random(semente)
        self._seq_cmd = 0
        self._seq_evento = 0
        self.comandos: list[Comando] = []
        self._por_chave: dict[str, str] = {}
        self.eventos: deque[Evento] = deque(maxlen=1000)
        self.voos: list[dict] = []
        self.contadores = {"mudas_plantadas": 0, "litros_aplicados": 0.0, "fissuras_inspecionadas": 0, "voos": 0}
        self._plantadas_desde_voo: set[str] = set()
        self._irrigadas_desde_voo: set[str] = set()
        self.base = Posicao(linha=fonte.tamanho - 1, coluna=0)  # pé do morro, acesso pela rua
        self.dispositivos: dict[str, Dispositivo] = {
            DRONE: Dispositivo(id=DRONE, tipo="drone", nome="Drone de mapeamento", posicao=self.base),
            ROBO: Dispositivo(id=ROBO, tipo="robo", nome="Robô jardineiro", posicao=self.base),
        }
        self._ultima_atualizacao = self.relogio()
        self.analise: Analise
        self.missoes: pd.DataFrame
        self._registrar_voo(self.fonte.voar(self.relogio()), inicial=True)
        self._evento("sistema", f"Central iniciada. Voo inicial {self.analise.mapa.voo_id} carregado.")

    # ------------------------------------------------------------------ utilidades

    def _evento(self, tipo: str, mensagem: str, nivel="info", origem: Origem = "sistema", comando_id=None) -> Evento:
        self._seq_evento += 1
        ev = Evento(
            id=self._seq_evento,
            quando=self.relogio(),
            tipo=tipo,
            nivel=nivel,
            mensagem=mensagem,
            origem=origem,
            comando_id=comando_id,
        )
        self.eventos.append(ev)
        for ouvinte in list(self._ouvintes):
            try:
                ouvinte(ev)
            except Exception:  # noqa: BLE001 - um ouvinte com problema não pode travar a central
                log.exception("Falha num ouvinte de eventos")
        return ev

    def adicionar_ouvinte(self, funcao: Callable[[Evento], None]) -> None:
        """Recebe cada evento novo (usado pelas notificações push)."""
        self._ouvintes.append(funcao)

    def registrar_evento(self, tipo: str, mensagem: str, nivel="info", origem: Origem = "sistema") -> Evento:
        """Evento vindo de fora da central (ex.: análise de foto com IA)."""
        with self._lock:
            return self._evento(tipo, mensagem, nivel, origem)

    def _novo_id(self) -> str:
        self._seq_cmd += 1
        return f"CMD-{self._seq_cmd:04d}"

    def _repetido(self, chave: str | None) -> Comando | None:
        if chave and chave in self._por_chave:
            return self.comando(self._por_chave[chave])
        return None

    def _registrar(self, cmd: Comando) -> Comando:
        self.comandos.append(cmd)
        if cmd.chave_idempotencia:
            self._por_chave[cmd.chave_idempotencia] = cmd.id
        return cmd

    def _recusar(
        self, tipo: TipoComando, origem: Origem, codigo: str, motivo: str, chave=None, dispositivo=None, **extra
    ) -> ComandoRecusado:
        agora = self.relogio()
        cmd = self._registrar(
            Comando(
                id=self._novo_id(),
                tipo=tipo,
                dispositivo=dispositivo,
                origem=origem,
                status="recusado",
                codigo_recusa=codigo,
                motivo=motivo,
                criado_em=agora,
                concluido_em=agora,
                chave_idempotencia=chave,
                **extra,
            )
        )
        self._evento("comando_recusado", f"{cmd.id} ({tipo}) recusado: {motivo}", "aviso", origem, cmd.id)
        return ComandoRecusado(cmd)

    def _iniciar(
        self, tipo: TipoComando, origem: Origem, dispositivo: str, duracao: float, chave=None, **extra
    ) -> Comando:
        agora = self.relogio()
        cmd = self._registrar(
            Comando(
                id=self._novo_id(),
                tipo=tipo,
                dispositivo=dispositivo,
                origem=origem,
                status="em_execucao",
                criado_em=agora,
                iniciado_em=agora,
                duracao_s=round(duracao * self.escala, 1),
                chave_idempotencia=chave,
                **extra,
            )
        )
        d = self.dispositivos[dispositivo]
        d.status, d.comando_atual = "em_missao", cmd.id
        self._evento(
            "comando_iniciado", f"{cmd.id}: {self._descrever(cmd)} ({origem})", origem=origem, comando_id=cmd.id
        )
        if cmd.duracao_s <= 0:
            self._concluir(cmd, agora)
        return cmd

    @staticmethod
    def _descrever(cmd: Comando) -> str:
        n = len(cmd.celulas)
        return {
            "voo_drone": "voo de mapeamento do drone",
            "plantio": f"plantio de capim-vetiver em {n} células",
            "irrigacao": f"irrigação de {n} células",
            "inspecao": f"inspeção de fissuras em {n} células",
        }.get(cmd.tipo, cmd.tipo)

    @property
    def nivel_alerta(self) -> str:
        return self.analise.alerta.nivel

    def _alerta_ativo(self) -> bool:
        return NIVEIS_ALERTA[self.nivel_alerta]["ordem"] >= NIVEIS_ALERTA["alerta"]["ordem"]

    # ------------------------------------------------------------------ relógio

    def atualizar(self) -> None:
        """Avança a simulação até o horário atual (chamado em toda consulta)."""
        with self._lock:
            agora = self.relogio()
            dt = max((agora - self._ultima_atualizacao).total_seconds(), 0.0)
            fator = 1 / self.escala if self.escala > 0 else 1.0
            for d in self.dispositivos.values():
                if d.status == "na_base":
                    d.bateria = round(min(100.0, d.bateria + RECARGA_POR_S * dt * fator), 1)
            ativos = sorted((c for c in self.comandos if c.status == "em_execucao"), key=self._fim)
            for cmd in ativos:
                if cmd.status != "em_execucao":  # pode ter sido cancelado por um voo concluído antes
                    continue
                fim = self._fim(cmd)
                if agora >= fim:
                    self._concluir(cmd, fim)
                else:
                    cmd.progresso = int(100 * (agora - cmd.iniciado_em).total_seconds() / max(cmd.duracao_s, 1e-6))
            self._ultima_atualizacao = agora
            if self.chuva and self.fonte.cenario == CENARIO_REAL and self.chuva.precisa_atualizar():
                self.chuva.atualizar_em_segundo_plano(self._receber_chuva)

    @staticmethod
    def _dados_chuva(leitura: LeituraChuva, nome: str) -> dict:
        return {
            "chuva_72h": leitura.chuva_72h,
            "previsao_24h": leitura.previsao_24h,
            "nome": nome,
        }

    def _nome_chuva_real(self) -> str:
        return f"Chuva real · {self.chuva.cidade.rotulo}" if self.chuva else "Chuva real"

    def _receber_chuva(self, leitura: LeituraChuva) -> None:
        """Chamado (em outra thread) quando chega uma nova leitura dos pluviômetros."""
        if not leitura.ok:
            return
        with self._lock:
            if self.fonte.cenario != CENARIO_REAL:
                return
            antes_72h, antes_prev = self.fonte.chuva_atual
            self.fonte.atualizar_chuva_real(self._dados_chuva(leitura, self._nome_chuva_real()))
            faixa_antes, faixa_agora = (
                faixa_da_chuva(antes_72h, antes_prev),
                faixa_da_chuva(leitura.chuva_72h, leitura.previsao_24h),
            )
            mudou = (
                abs(leitura.chuva_72h - antes_72h) >= DIFERENCA_CHUVA_MM
                or abs(leitura.previsao_24h - antes_prev) >= DIFERENCA_CHUVA_MM
                or faixa_agora != faixa_antes
            )
            if not mudou:
                return
            piorou = ORDEM_FAIXA[faixa_agora] > ORDEM_FAIXA[faixa_antes]
            nivel = "perigo" if piorou and faixa_agora in ("forte", "extrema") else "aviso" if piorou else "info"
            self._evento(
                "chuva_atualizada",
                f"Chuva real em {self.chuva.cidade.rotulo}: {antes_72h:.0f} → {leitura.chuva_72h:.0f} mm em 72 h, "
                f"{leitura.previsao_24h:.0f} mm previstos. Envie o drone para atualizar o mapa.",
                nivel,
            )

    @staticmethod
    def _fim(cmd: Comando) -> datetime:
        return cmd.iniciado_em + timedelta(seconds=cmd.duracao_s)

    def _concluir(self, cmd: Comando, quando: datetime) -> None:
        cmd.status, cmd.progresso, cmd.concluido_em = "concluido", 100, quando
        d = self.dispositivos.get(cmd.dispositivo or "")
        if cmd.tipo == "voo_drone":
            cmd.resultado = self._registrar_voo(self.fonte.voar(quando), origem=cmd.origem)
        elif cmd.tipo == "plantio":
            self.fonte.registrar_plantio(cmd.celulas)
            self._plantadas_desde_voo.update(cmd.celulas)
            mudas = int(cmd.parametros.get("mudas", 0))
            self.contadores["mudas_plantadas"] += mudas
            cmd.resultado = {
                "mudas_plantadas": mudas,
                "observacao": "O efeito na vegetação aparece no próximo voo do drone.",
            }
        elif cmd.tipo == "irrigacao":
            litros = cmd.parametros.get("litros_por_celula", {})
            self.fonte.registrar_irrigacao(litros)
            self._irrigadas_desde_voo.update(cmd.celulas)
            total = round(sum(litros.values()), 1)
            self.contadores["litros_aplicados"] += total
            cmd.resultado = {"litros_aplicados": total, "observacao": "A umidade nova aparece no próximo voo do drone."}
        elif cmd.tipo == "inspecao":
            df = self.analise.df.set_index("celula")
            resultado = {c: self._rng.random() < max(0.3, float(df.at[c, "prob_fissura"])) for c in cmd.celulas}
            self.fonte.registrar_inspecao(resultado)
            self.contadores["fissuras_inspecionadas"] += len(resultado)
            confirmadas = [c for c, v in resultado.items() if v]
            cmd.resultado = {"confirmadas": confirmadas, "descartadas": [c for c, v in resultado.items() if not v]}
            if confirmadas:
                self._evento(
                    "fissura_confirmada",
                    f"Fissuras confirmadas pelo robô em {', '.join(confirmadas)}.",
                    "aviso",
                    comando_id=cmd.id,
                )
        if d:
            d.status, d.comando_atual = "na_base", None
            d.posicao = self.base
        self._evento("comando_concluido", f"{cmd.id} concluído: {self._descrever(cmd)}.", comando_id=cmd.id)

    def _registrar_voo(self, mapa, inicial: bool = False, origem: Origem = "sistema") -> dict:
        anterior = None if inicial else self.analise.alerta.nivel
        self.analise = analisar(mapa)
        self.missoes = gerar_missoes(self.analise)
        self._plantadas_desde_voo.clear()
        self._irrigadas_desde_voo.clear()
        self.contadores["voos"] += 1
        al, est = self.analise.alerta, self.analise.estatisticas
        resumo = {
            "voo_id": mapa.voo_id,
            "data": mapa.data_voo.isoformat(),
            "cenario": mapa.cenario,
            "chuva_72h_voo": mapa.chuva_72h,
            "previsao_24h_voo": mapa.previsao_24h,
            "nivel_alerta": al.nivel,
            "risco_medio": est["risco_medio"],
            "celulas_alto_ou_critico": est["por_classe"]["alto"] + est["por_classe"]["critico"],
            "fissuras": est["fissuras"],
            "pessoas_em_risco": al.pessoas_em_risco,
        }
        self.voos.append(resumo)
        if anterior and anterior != al.nivel:
            piorou = NIVEIS_ALERTA[al.nivel]["ordem"] > NIVEIS_ALERTA[anterior]["ordem"]
            self._evento(
                "alerta_mudou",
                f"Nível de alerta: {NIVEIS_ALERTA[anterior]['titulo']} → {al.titulo}. {al.mensagem}",
                "perigo" if piorou and al.nivel in ("alerta", "alerta_maximo") else "aviso",
                origem,
            )
            if self._alerta_ativo():
                self._suspender_robo("alerta ativo após novo voo")
        return resumo

    def _suspender_robo(self, motivo: str) -> None:
        robo = self.dispositivos[ROBO]
        if robo.comando_atual:
            cmd = self.comando(robo.comando_atual)
            if cmd and cmd.status == "em_execucao":
                cmd.status, cmd.motivo, cmd.concluido_em = "cancelado", f"Robô recolhido: {motivo}", self.relogio()
                self._evento("comando_cancelado", f"{cmd.id} cancelado: {cmd.motivo}", "aviso", comando_id=cmd.id)
        if robo.status != "parado":
            robo.status, robo.comando_atual, robo.posicao = "na_base", None, self.base

    # ------------------------------------------------------------------ consultas

    def comando(self, comando_id: str) -> Comando | None:
        return next((c for c in self.comandos if c.id == comando_id), None)

    def listar_comandos(self, limite: int = 50, status: str | None = None) -> list[Comando]:
        self.atualizar()
        with self._lock:
            itens = [c for c in self.comandos if status is None or c.status == status]
            return [c.model_copy() for c in reversed(itens[-limite:])]

    def listar_eventos(self, desde: int = 0, limite: int = 100) -> list[Evento]:
        self.atualizar()
        with self._lock:
            return [e for e in self.eventos if e.id > desde][-limite:]

    def clima_atual(self) -> dict:
        if self.fonte.cenario == CENARIO_REAL and self.chuva:
            chuva_72h, previsao = self.fonte.chuva_atual
            ult = self.chuva.ultima
            descricao = (
                f"Cemaden ({ult.estacao}) + previsão {ult.fonte_previsao}" if ult else "Leitura dos pluviômetros"
            )
            return {
                "cenario": CENARIO_REAL,
                "nome": self._nome_chuva_real(),
                "chuva_72h": round(chuva_72h, 1),
                "previsao_24h": round(previsao, 1),
                "descricao": descricao,
                "real": True,
                "faixa": faixa_da_chuva(chuva_72h, previsao),
                "atualizado_em": ult.atualizado_em if ult else None,
                "erro": self.chuva.ultimo_erro,
            }
        c = CENARIOS[self.fonte.cenario]
        return {
            "cenario": self.fonte.cenario,
            "nome": c["nome"],
            "chuva_72h": c["chuva_72h"],
            "previsao_24h": c["previsao_24h"],
            "descricao": c["descricao"],
            "real": False,
            "faixa": self.fonte.cenario,
            "atualizado_em": None,
            "erro": None,
        }

    def estado(self) -> dict:
        self.atualizar()
        with self._lock:
            m, al = self.analise.mapa, self.analise.alerta
            ativos = [c.model_copy() for c in self.comandos if c.status == "em_execucao"]
            return {
                "horario": self.relogio().isoformat(),
                "dispositivos": [d.model_copy() for d in self.dispositivos.values()],
                "comandos_ativos": ativos,
                "ultimos_comandos": [c.model_copy() for c in self.comandos[-8:]][::-1],
                "alerta": {
                    "nivel": al.nivel,
                    "titulo": al.titulo,
                    "cor": al.cor,
                    "mensagem": al.mensagem,
                    "acao": al.acao,
                    "casas_em_risco": al.casas_em_risco,
                    "pessoas_em_risco": al.pessoas_em_risco,
                    "celulas_evacuar": al.celulas_evacuar,
                },
                "robo_liberado": not self._alerta_ativo() and self.dispositivos[ROBO].status != "parado",
                "frota_parada": any(d.status == "parado" for d in self.dispositivos.values()),
                "ultimo_voo": self.voos[-1]
                | {"nome_cenario": m.nome_cenario, "chuva_72h": m.chuva_72h, "previsao_24h": m.previsao_24h},
                "clima_atual": self.clima_atual(),
                "estatisticas": self.analise.estatisticas,
                "missoes": resumo_missoes(self.missoes),
                "contadores": dict(self.contadores),
                "recomendacoes": [r.model_dump() for r in self._recomendacoes()],
                "ultimo_evento_id": self._seq_evento,
            }

    def _recomendacoes(self) -> list[Recomendacao]:
        recs: list[Recomendacao] = []
        df, ultimo = self.analise.df, self.voos[-1]
        idade_min = (self.relogio() - datetime.fromisoformat(ultimo["data"])).total_seconds() / 60
        chuva_72h, previsao = self.fonte.chuva_atual
        chuva_mudou = (
            abs(chuva_72h - ultimo["chuva_72h_voo"]) >= DIFERENCA_CHUVA_MM
            or abs(previsao - ultimo["previsao_24h_voo"]) >= DIFERENCA_CHUVA_MM
        )
        if self.fonte.cenario != ultimo["cenario"] or chuva_mudou:
            recs.append(
                Recomendacao(
                    id="REC-VOO",
                    acao="voo_drone",
                    prioridade="alta",
                    titulo="Enviar o drone",
                    motivo=(
                        f"A chuva mudou depois do último voo ({ultimo['chuva_72h_voo']:.0f} → {chuva_72h:.0f} mm "
                        f"em 72 h; {previsao:.0f} mm previstos)."
                        if chuva_mudou and self.fonte.cenario == ultimo["cenario"]
                        else f"O clima mudou para '{self.clima_atual()['nome']}' depois do último voo."
                    ),
                )
            )
        elif idade_min > VOO_DESATUALIZADO_MIN:
            recs.append(
                Recomendacao(
                    id="REC-VOO",
                    acao="voo_drone",
                    prioridade="media",
                    titulo="Enviar o drone",
                    motivo=f"O último mapeamento tem {idade_min:.0f} minutos.",
                )
            )
        elif self._plantadas_desde_voo or self._irrigadas_desde_voo:
            recs.append(
                Recomendacao(
                    id="REC-VOO",
                    acao="voo_drone",
                    prioridade="baixa",
                    titulo="Enviar o drone",
                    motivo="Medir o efeito do plantio/irrigação feitos depois do último voo.",
                )
            )
        if self._alerta_ativo():
            return recs
        for tipo, titulo in (
            ("inspecao", "Inspecionar fissuras"),
            ("plantio", "Plantar capim-vetiver"),
            ("irrigacao", "Irrigar mudas"),
        ):
            alvos, _ = self._alvos_padrao(tipo)
            if alvos:
                prioridade = "alta" if tipo == "inspecao" else "media" if tipo == "plantio" else "baixa"
                motivos = {
                    "inspecao": f"{len(alvos)} fissuras detectadas pela visão computacional em áreas sem casas.",
                    "plantio": f"{int(df['plantio_recomendado'].sum())} células com solo exposto e risco; começar pelas {len(alvos)} prioritárias.",
                    "irrigacao": f"{len(alvos)} células com vegetação em formação e solo seco.",
                }
                recs.append(
                    Recomendacao(
                        id=f"REC-{tipo.upper()}",
                        acao=tipo,
                        prioridade=prioridade,
                        titulo=titulo,
                        motivo=motivos[tipo],
                        celulas=alvos,
                    )
                )
        return recs

    # ------------------------------------------------------------------ alvos do robô

    def _alvos_padrao(self, tipo: str) -> tuple[list[str], dict[str, str]]:
        df, n = self.analise.df, MAX_CELULAS_PADRAO[tipo]
        if tipo == "plantio":
            plantio = self.missoes[(self.missoes["tipo"] == "plantio") & (self.missoes["executor"] == "robô")]
            cand = [c for c in plantio["celula"] if c not in self._plantadas_desde_voo]
        elif tipo == "irrigacao":
            cand = [
                c
                for c in df[df["precisa_irrigar"]].sort_values("umidade_pct")["celula"]
                if c not in self._irrigadas_desde_voo
            ]
        else:
            verif = self.fonte.fissuras_verificadas
            cand = [
                c
                for c in df[df["fissura_detectada"] & (df["casas"] == 0)].sort_values("risco", ascending=False)[
                    "celula"
                ]
                if c not in verif
            ]
        return cand[:n], {}

    def _validar_alvos(self, tipo: str, celulas: list[str]) -> tuple[list[str], dict[str, str]]:
        df = self.analise.df.set_index("celula")
        vai_chover = self.analise.mapa.previsao_24h >= 10
        validas, ignoradas = [], {}
        for c in dict.fromkeys(x.strip().upper() for x in celulas if x.strip()):
            if c not in df.index:
                ignoradas[c] = "célula não existe neste mapeamento"
                continue
            r = df.loc[c]
            if r["casas"] > 0:
                ignoradas[c] = "área com casas: o robô não atua aqui (encaminhar à Defesa Civil)"
            elif tipo == "plantio" and r["tipo_solo"] == "rochoso":
                ignoradas[c] = "afloramento de rocha"
            elif tipo == "plantio" and r["declividade_graus"] > DECLIVIDADE_MAX_ROBO:
                ignoradas[c] = f"inclinação de {r['declividade_graus']:.0f}° acima do limite do robô: plantio manual"
            elif tipo == "plantio" and r["cobertura_vegetal"] >= 0.8:
                ignoradas[c] = "já tem vegetação suficiente"
            elif tipo == "plantio" and c in self._plantadas_desde_voo:
                ignoradas[c] = "já plantada; aguardando novo voo"
            elif tipo == "irrigacao" and r["classe_risco"] not in ("baixo", "moderado"):
                ignoradas[c] = "risco alto: água a mais pode provocar deslizamento"
            elif tipo == "irrigacao" and vai_chover:
                ignoradas[c] = "há chuva prevista nas próximas 24 h"
            elif tipo == "irrigacao" and r["umidade_pct"] >= UMIDADE_ALVO:
                ignoradas[c] = f"solo já está úmido ({r['umidade_pct']:.0f}%)"
            elif tipo == "irrigacao" and c in self._irrigadas_desde_voo:
                ignoradas[c] = "já irrigada; aguardando novo voo"
            else:
                validas.append(c)
        return validas, ignoradas

    # ------------------------------------------------------------------ comandos

    def _checar_frota(self, tipo: TipoComando, origem: Origem, chave, dispositivo: str) -> None:
        d = self.dispositivos[dispositivo]
        if d.status == "parado":
            raise self._recusar(
                tipo, origem, "frota_parada", "Parada de emergência ativa: libere a frota primeiro.", chave, dispositivo
            )
        if d.status == "em_missao":
            raise self._recusar(
                tipo, origem, "dispositivo_ocupado", f"{d.nome} está em missão ({d.comando_atual}).", chave, dispositivo
            )
        if d.bateria < BATERIA_MINIMA[d.tipo]:
            raise self._recusar(
                tipo,
                origem,
                "bateria_baixa",
                f"Bateria do {d.nome.lower()} em {d.bateria:.0f}% (mínimo {BATERIA_MINIMA[d.tipo]:.0f}%).",
                chave,
                dispositivo,
            )

    def enviar_drone(self, origem: Origem = "admin", chave: str | None = None) -> Comando:
        self.atualizar()
        with self._lock:
            if repetido := self._repetido(chave):
                return repetido
            self._checar_frota("voo_drone", origem, chave, DRONE)
            self.dispositivos[DRONE].bateria -= CONSUMO_BATERIA["voo_drone"]
            return self._iniciar(
                "voo_drone", origem, DRONE, DURACAO_VOO_S, chave, parametros={"cenario": self.fonte.cenario}
            )

    def enviar_robo(
        self, tipo: str, celulas: list[str] | None = None, origem: Origem = "admin", chave: str | None = None
    ) -> Comando:
        if tipo not in DURACAO_BASE_S:
            raise ValueError(f"Tipo de missão do robô inválido: {tipo}")
        self.atualizar()
        with self._lock:
            if repetido := self._repetido(chave):
                return repetido
            if self._alerta_ativo():
                raise self._recusar(
                    tipo,
                    origem,
                    "alerta_ativo",
                    f"Robô recolhido por segurança: nível {self.analise.alerta.titulo}.",
                    chave,
                    ROBO,
                )
            self._checar_frota(tipo, origem, chave, ROBO)
            if celulas:
                validas, ignoradas = self._validar_alvos(tipo, celulas)
            else:
                validas, ignoradas = self._alvos_padrao(tipo)
            if not validas:
                motivo = (
                    "Nenhuma célula válida para esta missão."
                    if celulas
                    else "Não há células que precisem desta missão agora."
                )
                raise self._recusar(
                    tipo, origem, "sem_alvos_validos", motivo, chave, ROBO, ignoradas=ignoradas, celulas=[]
                )
            df = self.analise.df.set_index("celula")
            parametros: dict = {}
            if tipo == "plantio":
                parametros["mudas"] = int(sum(round(400 * (1 - float(df.at[c, "cobertura_vegetal"]))) for c in validas))
            if tipo == "irrigacao":
                area = TAMANHO_CELULA_M**2
                litros = {
                    c: round(area * 0.3 * 0.05 * max(UMIDADE_ALVO - float(df.at[c, "umidade_pct"]), 0) / 100 * 1000, 0)
                    for c in validas
                }
                parametros["litros_por_celula"] = litros
                parametros["litros"] = round(sum(litros.values()), 0)
            robo = self.dispositivos[ROBO]
            consumo = max(5.0, CONSUMO_BATERIA[tipo] * len(validas))
            if robo.bateria - consumo < 5:
                raise self._recusar(
                    tipo,
                    origem,
                    "bateria_baixa",
                    f"Bateria insuficiente para {len(validas)} células ({robo.bateria:.0f}%).",
                    chave,
                    ROBO,
                )
            robo.bateria = round(robo.bateria - consumo, 1)
            primeira = df.loc[validas[0]]
            robo.posicao = Posicao(linha=int(primeira["linha"]), coluna=int(primeira["coluna"]))
            duracao = DURACAO_BASE_S[tipo] + DURACAO_POR_CELULA_S[tipo] * len(validas)
            return self._iniciar(
                tipo, origem, ROBO, duracao, chave, celulas=validas, ignoradas=ignoradas, parametros=parametros
            )

    def recolher_robo(self, origem: Origem = "admin", chave: str | None = None) -> Comando:
        self.atualizar()
        with self._lock:
            if repetido := self._repetido(chave):
                return repetido
            robo = self.dispositivos[ROBO]
            cancelado = robo.comando_atual
            if cancelado:
                cmd = self.comando(cancelado)
                cmd.status, cmd.motivo, cmd.concluido_em = "cancelado", f"Recolhido pelo {origem}", self.relogio()
                self._evento("comando_cancelado", f"{cmd.id} cancelado: robô recolhido.", "aviso", origem, cmd.id)
            if robo.status != "parado":
                robo.status, robo.comando_atual, robo.posicao = "na_base", None, self.base
            agora = self.relogio()
            return self._registrar(
                Comando(
                    id=self._novo_id(),
                    tipo="recolher_robo",
                    dispositivo=ROBO,
                    origem=origem,
                    status="concluido",
                    progresso=100,
                    criado_em=agora,
                    iniciado_em=agora,
                    concluido_em=agora,
                    chave_idempotencia=chave,
                    resultado={"comando_cancelado": cancelado},
                )
            )

    def parada_emergencia(self, origem: Origem = "admin", chave: str | None = None) -> Comando:
        self.atualizar()
        with self._lock:
            if repetido := self._repetido(chave):
                return repetido
            agora, cancelados = self.relogio(), []
            for cmd in [c for c in self.comandos if c.status == "em_execucao"]:
                cmd.status, cmd.motivo, cmd.concluido_em = "cancelado", "Parada de emergência", agora
                cancelados.append(cmd.id)
            for d in self.dispositivos.values():
                d.status, d.comando_atual = "parado", None
                d.posicao = self.base
            self._evento(
                "frota_parada",
                f"PARADA DE EMERGÊNCIA acionada ({origem}). Cancelados: {cancelados or 'nenhum'}.",
                "perigo",
                origem,
            )
            return self._registrar(
                Comando(
                    id=self._novo_id(),
                    tipo="parada_emergencia",
                    origem=origem,
                    status="concluido",
                    progresso=100,
                    criado_em=agora,
                    iniciado_em=agora,
                    concluido_em=agora,
                    chave_idempotencia=chave,
                    resultado={"comandos_cancelados": cancelados},
                )
            )

    def liberar_frota(self, origem: Origem = "admin", chave: str | None = None) -> Comando:
        self.atualizar()
        with self._lock:
            if repetido := self._repetido(chave):
                return repetido
            for d in self.dispositivos.values():
                if d.status == "parado":
                    d.status = "na_base"
            agora = self.relogio()
            self._evento("frota_liberada", f"Frota liberada ({origem}).", origem=origem)
            return self._registrar(
                Comando(
                    id=self._novo_id(),
                    tipo="liberar_frota",
                    origem=origem,
                    status="concluido",
                    progresso=100,
                    criado_em=agora,
                    iniciado_em=agora,
                    concluido_em=agora,
                    chave_idempotencia=chave,
                )
            )

    def mudar_clima(self, cenario: str, origem: Origem = "admin", chave: str | None = None) -> Comando:
        """Ferramenta de SIMULAÇÃO: muda a chuva (como se o pluviômetro tivesse mudado)."""
        self.atualizar()
        with self._lock:
            if repetido := self._repetido(chave):
                return repetido
            if cenario not in CENARIOS and cenario != CENARIO_REAL:
                raise self._recusar(
                    "mudar_clima", origem, "cenario_invalido", f"Cenário desconhecido: {cenario}", chave
                )
            nome_anterior = self.clima_atual()["nome"]
            anterior = self.fonte.cenario
            if cenario == CENARIO_REAL:
                if not self.chuva:
                    raise self._recusar(
                        "mudar_clima", origem, "chuva_real_desativada", "Chuva real não configurada no servidor.", chave
                    )
                leitura = self.chuva.atualizar()
                if not leitura.ok:
                    raise self._recusar(
                        "mudar_clima",
                        origem,
                        "chuva_indisponivel",
                        f"Não foi possível ler os pluviômetros agora ({leitura.erro}).",
                        chave,
                    )
                self.fonte.mudar_clima(CENARIO_REAL, self._dados_chuva(leitura, self._nome_chuva_real()))
            else:
                self.fonte.mudar_clima(cenario)
            agora = self.relogio()
            self._evento(
                "clima_mudou",
                f"Clima: {nome_anterior} → {self.clima_atual()['nome']}. Envie o drone para atualizar o mapa.",
                "aviso",
                origem,
            )
            return self._registrar(
                Comando(
                    id=self._novo_id(),
                    tipo="mudar_clima",
                    origem=origem,
                    status="concluido",
                    progresso=100,
                    criado_em=agora,
                    iniciado_em=agora,
                    concluido_em=agora,
                    chave_idempotencia=chave,
                    parametros={"de": anterior, "para": cenario},
                )
            )

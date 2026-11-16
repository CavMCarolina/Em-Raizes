"""Conversa com o Guardião: histórico, janela de contexto e streaming.

É a base do chat de terminal (``python -m em_raizes.ia.chat_terminal``) e do notebook da
aula "Construindo um Chat com LLMs":

- **Roles:** ``system`` (regras + trechos do manual + situação atual + resumo), ``user`` e ``assistant``.
- **Histórico:** as últimas trocas vão inteiras; quando passam do limite de tokens, as mais
  antigas viram um resumo (prompt ``SYSTEM_RESUMO_HISTORICO``) e saem da janela.
- **Pergunta de acompanhamento:** "e no seco?" é reescrita como pergunta completa
  (``SYSTEM_REFORMULAR_PERGUNTA``) antes da busca no manual.
- **Streaming:** a resposta aparece aos pedaços; sem IA, o modo offline também é
  entregue aos pedaços, para a interface se comportar igual.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field

from . import prompts
from .guardiao import Guardiao, detectar_emergencia
from .llm import ErroLLM

PALAVRAS_DE_ACOMPANHAMENTO = re.compile(
    r"^(e |e\?|mas |então|entao|por que|porque|pq|isso|esse|essa|ele|ela|de novo|e se|tá|ta |ok)",
    re.IGNORECASE,
)


def estimar_tokens(texto: str) -> int:
    """Estimativa simples (~4 caracteres por token), igual para o modelo principal e as reservas (famílias diferentes)."""
    return max(1, round(len(texto) / 4))


def tokens_mensagens(mensagens: list[dict]) -> int:
    return sum(estimar_tokens(m["content"]) + 4 for m in mensagens)  # +4: papel e separadores


@dataclass
class Turno:
    pergunta: str
    pergunta_busca: str
    resposta: str
    modo: str  # "ia" | "offline"
    modelo: str | None = None
    fontes: list[str] = field(default_factory=list)
    primeiro_pedaco_s: float | None = None
    total_s: float = 0.0
    tokens_janela: int = 0
    resumiu: bool = False
    aviso: str | None = None


class Conversa:
    def __init__(
        self,
        guardiao: Guardiao,
        contexto: str | Callable[[], str] = "",
        limite_tokens_historico: int = 1200,
        turnos_recentes: int = 4,
        usar_reformulacao: bool = True,
    ):
        self.guardiao = guardiao
        self._contexto = contexto
        self.limite_tokens_historico = limite_tokens_historico
        self.turnos_recentes = turnos_recentes
        self.usar_reformulacao = usar_reformulacao
        self.historico: list[dict] = []  # mensagens user/assistant ainda na janela
        self.resumo = ""  # resumo das trocas antigas que saíram da janela
        self.turnos: list[Turno] = []

    # ------------------------------------------------------------------ utilidades

    @property
    def online(self) -> bool:
        return self.guardiao.online

    def contexto(self) -> str:
        return self._contexto() if callable(self._contexto) else self._contexto

    def limpar(self) -> None:
        self.historico, self.resumo, self.turnos = [], "", []

    def tokens_historico(self) -> int:
        return tokens_mensagens(self.historico)

    def _parece_acompanhamento(self, texto: str) -> bool:
        t = texto.strip()
        return bool(self.historico) and (len(t.split()) <= 6 or bool(PALAVRAS_DE_ACOMPANHAMENTO.match(t)))

    def reformular(self, pergunta: str) -> str:
        """Pergunta completa para a busca no manual (só quando parece continuação da conversa)."""
        if not self.usar_reformulacao or not self._parece_acompanhamento(pergunta):
            return pergunta
        ultimas = self.historico[-4:]
        if not self.online:  # offline: junta com a pergunta anterior do administrador
            anteriores = [m["content"] for m in ultimas if m["role"] == "user"]
            return f"{anteriores[-1]} {pergunta}" if anteriores else pergunta
        historico_txt = "\n".join(f"{m['role']}: {m['content'][:300]}" for m in ultimas)
        try:
            r = self.guardiao.cliente.completar(
                [
                    {"role": "system", "content": prompts.SYSTEM_REFORMULAR_PERGUNTA},
                    {"role": "user", "content": f"Histórico:\n{historico_txt}\n\nMensagem: {pergunta}"},
                ],
                temperatura=0.0,
                max_tokens=80,
            )
            linha = r.texto.strip().splitlines()[0].strip().strip('"')
            return linha.removeprefix("Pergunta:").strip().strip('"') or pergunta
        except ErroLLM:
            return pergunta

    def compactar(self) -> bool:
        """Se o histórico passou do limite, resume as trocas antigas e mantém só as recentes."""
        if self.tokens_historico() <= self.limite_tokens_historico:
            return False
        manter = self.turnos_recentes * 2
        antigas, recentes = self.historico[:-manter], self.historico[-manter:]
        if not antigas:
            return False
        texto = "\n".join(f"{m['role']}: {m['content']}" for m in antigas)
        if self.resumo:
            texto = f"Resumo anterior:\n{self.resumo}\n\nNovas mensagens:\n{texto}"
        novo = None
        if self.online:
            try:
                novo = self.guardiao.cliente.completar(
                    [
                        {"role": "system", "content": prompts.SYSTEM_RESUMO_HISTORICO},
                        {"role": "user", "content": texto},
                    ],
                    temperatura=0.1,
                    max_tokens=220,
                ).texto.strip()
            except ErroLLM:
                novo = None
        if not novo:  # offline ou erro: resumo simples com as perguntas do administrador
            perguntas = [m["content"][:100] for m in antigas if m["role"] == "user"]
            novo = (self.resumo + "\n" if self.resumo else "") + "\n".join(f"- Perguntou: {p}" for p in perguntas)
        self.resumo, self.historico = novo, recentes
        return True

    def montar_mensagens(self, pergunta: str, pergunta_busca: str) -> tuple[list[dict], list[str]]:
        manual, fontes = self.guardiao.base.contexto(pergunta_busca, k=3)
        sistema = (
            f"{prompts.SYSTEM_GUARDIAO}\n\n### MANUAL (trechos relevantes)\n{manual}"
            f"\n\n### CONTEXTO DO MAPEAMENTO ATUAL\n{self.contexto() or '(nenhum voo carregado)'}"
        )
        if self.resumo:
            sistema += f"\n\n### RESUMO DA CONVERSA ATÉ AQUI\n{self.resumo}"
        return [{"role": "system", "content": sistema}, *self.historico, {"role": "user", "content": pergunta}], fontes

    # ------------------------------------------------------------------ perguntar

    def perguntar(self, pergunta: str) -> Iterator[str]:
        """Responde aos pedaços. Depois de consumir o gerador, o turno fica em ``self.turnos[-1]``."""
        pergunta = pergunta.strip()
        resumiu = self.compactar()
        busca = self.reformular(pergunta)
        mensagens, fontes = self.montar_mensagens(pergunta, busca)
        turno = Turno(
            pergunta,
            busca,
            "",
            "ia" if self.online else "offline",
            fontes=fontes,
            tokens_janela=tokens_mensagens(mensagens),
            resumiu=resumiu,
        )
        inicio = time.perf_counter()

        if self.online:
            try:
                for pedaco in self.guardiao.cliente.transmitir(mensagens, temperatura=0.3, max_tokens=500):
                    turno.resposta += pedaco
                    yield pedaco
                stats = self.guardiao.cliente.ultimo_stream
                turno.modelo, turno.primeiro_pedaco_s = stats.modelo, stats.primeiro_pedaco_s
            except ErroLLM as e:
                turno.aviso = e.mensagem
                if e.codigo == "stream_interrompido" and turno.resposta:
                    aviso = f"\n\n*[{e.mensagem}]*"
                    turno.resposta += aviso
                    yield aviso
                else:
                    turno.modo = "offline"
            if turno.modo == "ia" and detectar_emergencia(pergunta) and "199" not in turno.resposta:
                extra = (
                    "\n\n**Emergência — se isso está acontecendo agora:** saia para um local seguro e ligue "
                    "para a Defesa Civil 199 · Bombeiros 193."
                )
                turno.resposta += extra
                yield extra

        if turno.modo == "offline":  # sem chave ou com erro na IA: regras + manual, entregues aos pedaços
            manual, fontes = self.guardiao.base.contexto(busca, k=3)
            texto = self.guardiao._responder_offline(
                busca, self.contexto(), manual, fontes, detectar_emergencia(pergunta)
            )
            turno.fontes = fontes
            for parte in re.split(r"(\s+)", texto):
                if parte:
                    if turno.primeiro_pedaco_s is None:
                        turno.primeiro_pedaco_s = round(time.perf_counter() - inicio, 3)
                    turno.resposta += parte
                    yield parte

        turno.total_s = round(time.perf_counter() - inicio, 2)
        self.historico += [{"role": "user", "content": pergunta}, {"role": "assistant", "content": turno.resposta}]
        self.turnos.append(turno)

    def perguntar_tudo(self, pergunta: str) -> Turno:
        """Versão sem streaming (consome o gerador e devolve o turno)."""
        for _ in self.perguntar(pergunta):
            pass
        return self.turnos[-1]

"""Chat de terminal com o Guardião (histórico + streaming).

Uso:
    python -m em_raizes.ia.chat_terminal                 # conversa interativa
    python -m em_raizes.ia.chat_terminal --pergunta "Como envio o drone?"
    echo "Como envio o drone?" | python -m em_raizes.ia.chat_terminal

Comandos durante a conversa: /ajuda, /historico, /resumo, /tokens, /limpar, /sair.
Sem OPENROUTER_API_KEY o Guardião responde em modo offline (regras + manual).
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Callable

from ..config import _carregar_dotenv
from .conhecimento import BaseConhecimento
from .conversa import Conversa
from .guardiao import Guardiao
from .llm import ClienteLLM

AJUDA = """Comandos:
  /historico  mostra as mensagens que ainda estão na janela de contexto
  /resumo     mostra o resumo das mensagens antigas (quando a conversa fica longa)
  /tokens     mostra o tamanho estimado do histórico
  /limpar     começa uma conversa nova
  /sair       encerra (ou Ctrl+C)"""


def montar_contexto(chuva_real: bool = True) -> Callable[[], str]:
    """Situação atual do morro (voo simulado + chuva real, se disponível) para o Guardião."""
    from ..api.main import contexto_operacional
    from ..fontes.chuva import FonteChuvaReal
    from ..fontes.simulador import MundoSimulado
    from ..operacoes.central import CentralOperacoes

    cenario, dados, chuva = "moderada", None, None
    if chuva_real:
        chuva = FonteChuvaReal()
        leitura = chuva.atualizar()
        if leitura.ok:
            cenario = "real"
            dados = {
                "chuva_72h": leitura.chuva_72h,
                "previsao_24h": leitura.previsao_24h,
                "nome": f"Chuva real · {chuva.cidade.rotulo}",
            }
    central = CentralOperacoes(MundoSimulado(cenario=cenario, chuva_real=dados), chuva=chuva)
    return lambda: contexto_operacional(central)


def _rodape(conversa: Conversa) -> str:
    t = conversa.turnos[-1]
    partes = [f"IA · {t.modelo}" if t.modo == "ia" else "modo offline"]
    if t.primeiro_pedaco_s is not None:
        partes.append(f"1º pedaço {t.primeiro_pedaco_s:.2f}s")
    partes.append(f"total {t.total_s:.2f}s")
    partes.append(f"janela ~{t.tokens_janela} tokens")
    if t.resumiu:
        partes.append("histórico antigo resumido")
    if t.pergunta_busca != t.pergunta:
        partes.append(f"busca: “{t.pergunta_busca[:60]}”")
    if t.aviso:
        partes.append(f"aviso: {t.aviso}")
    return "   [" + " · ".join(partes) + "]"


def responder(conversa: Conversa, pergunta: str, saida=sys.stdout) -> None:
    saida.write("Guardião: ")
    saida.flush()
    for pedaco in conversa.perguntar(pergunta):  # streaming: escreve cada pedaço assim que chega
        saida.write(pedaco)
        saida.flush()
    saida.write("\n" + _rodape(conversa) + "\n\n")
    saida.flush()


def comando(conversa: Conversa, texto: str, saida=sys.stdout) -> bool:
    """Trata /comandos. Devolve False para encerrar."""
    cmd = texto.strip().lower()
    if cmd in ("/sair", "/exit", "/quit"):
        return False
    if cmd == "/limpar":
        conversa.limpar()
        saida.write("Conversa nova.\n\n")
    elif cmd == "/historico":
        for m in conversa.historico or [{"role": "-", "content": "(vazio)"}]:
            saida.write(f"  {m['role']}: {m['content'][:160]}\n")
        saida.write("\n")
    elif cmd == "/resumo":
        saida.write((conversa.resumo or "(ainda não há resumo: a conversa cabe inteira na janela)") + "\n\n")
    elif cmd == "/tokens":
        saida.write(
            f"Histórico: ~{conversa.tokens_historico()} tokens (limite {conversa.limite_tokens_historico}).\n\n"
        )
    else:
        saida.write(AJUDA + "\n\n")
    return True


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Chat de terminal com o Guardião (Em Raízes).")
    ap.add_argument("--pergunta", action="append", help="pergunta única (pode repetir); sem ela, abre a conversa")
    ap.add_argument("--offline", action="store_true", help="força o modo offline (sem IA generativa)")
    ap.add_argument("--sem-chuva-real", action="store_true", help="usa chuva simulada no contexto")
    args = ap.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    _carregar_dotenv()

    cliente = ClienteLLM(api_key="") if args.offline else ClienteLLM()
    conversa = Conversa(Guardiao(cliente, BaseConhecimento()), contexto=montar_contexto(not args.sem_chuva_real))
    print(f"Guardião · Em Raízes — {'IA online (' + cliente.modelo + ')' if conversa.online else 'modo offline'}")
    print("Dados do morro simulados. Em emergência ligue 199. Digite /ajuda para ver os comandos.\n")

    if args.pergunta:
        for p in args.pergunta:
            print(f"Você: {p}")
            responder(conversa, p)
        return

    interativo = sys.stdin.isatty()
    while True:
        try:
            texto = input("Você: ") if interativo else sys.stdin.readline()
        except (EOFError, KeyboardInterrupt):
            print("\nAté logo!")
            return
        if not interativo:
            if not texto:
                return
            texto = texto.strip()
            print(f"Você: {texto}")
        if not texto.strip():
            continue
        if texto.startswith("/"):
            if not comando(conversa, texto):
                print("Até logo!")
                return
            continue
        try:
            responder(conversa, texto)
        except KeyboardInterrupt:
            print("\n[resposta interrompida]\n")


if __name__ == "__main__":
    main()

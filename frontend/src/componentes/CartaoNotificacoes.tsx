import { BellOff, BellRing, Send } from "lucide-react";
import { useEffect, useState } from "react";
import { api, ErroApi } from "../api/cliente";
import { useCentral } from "../contexto";
import { ativarPush, desativarPush, situacaoPush, TEXTO_SITUACAO, type SituacaoPush } from "../util/push";
import { Cartao } from "./ui";

export function CartaoNotificacoes() {
  const { info, avisar } = useCentral();
  const [situacao, setSituacao] = useState<SituacaoPush | null>(null);
  const [ocupado, setOcupado] = useState(false);

  useEffect(() => {
    void situacaoPush().then(setSituacao);
  }, []);

  if (info && !info.push_habilitado) {
    return (
      <Cartao titulo="Notificações no celular" teste="cartao-notificacoes">
        <p className="mudo">Desativadas no servidor (defina EM_RAIZES_VAPID_PRIVADA).</p>
      </Cartao>
    );
  }

  const agir = async (acao: () => Promise<void>) => {
    setOcupado(true);
    try {
      await acao();
    } catch (e) {
      avisar({ tipo: "erro", titulo: "Notificações", texto: (e as ErroApi).message });
    } finally {
      setOcupado(false);
    }
  };

  const ativar = () =>
    agir(async () => {
      const { chave_publica } = await api.notificacoes.status();
      if (!chave_publica) throw new Error("O servidor não informou a chave das notificações.");
      const nova = await ativarPush(chave_publica);
      setSituacao(nova);
      if (nova === "ativado") avisar({ tipo: "sucesso", titulo: "Notificações ativadas neste aparelho" });
    });

  const testar = () =>
    agir(async () => {
      const r = await api.notificacoes.teste();
      avisar({
        tipo: r.enviadas ? "sucesso" : "erro",
        titulo: r.enviadas ? "Teste enviado" : "Nenhum aparelho recebeu",
        texto: r.enviadas ? "Deve aparecer uma notificação em alguns segundos." : "Ative as notificações primeiro.",
      });
    });

  const desativar = () => agir(async () => setSituacao(await desativarPush()));

  return (
    <Cartao titulo="Notificações no celular" teste="cartao-notificacoes">
      <p className="mudo" data-testid="situacao-notificacoes" data-situacao={situacao ?? ""}>
        {situacao ? TEXTO_SITUACAO[situacao] : "Verificando…"}
      </p>
      <div className="acoes acoes--compactas">
        {situacao === "ativado" ? (
          <>
            <button type="button" className="botao botao--primario" data-testid="btn-teste-notificacao" disabled={ocupado} onClick={() => void testar()}>
              <Send size={18} aria-hidden /> Enviar teste
            </button>
            <button type="button" className="botao" data-testid="btn-desativar-notificacoes" disabled={ocupado} onClick={() => void desativar()}>
              <BellOff size={18} aria-hidden /> Desativar
            </button>
          </>
        ) : (
          <button
            type="button"
            className="botao botao--primario"
            data-testid="btn-ativar-notificacoes"
            disabled={ocupado || situacao !== "desativado"}
            onClick={() => void ativar()}
          >
            <BellRing size={18} aria-hidden /> Ativar notificações
          </button>
        )}
      </div>
    </Cartao>
  );
}

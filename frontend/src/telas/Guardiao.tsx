import { Camera } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api, ErroApi } from "../api/cliente";
import type { MensagemChat, RespostaFoto } from "../api/tipos";
import { AnalisarFoto } from "../componentes/AnalisarFoto";
import { Folha } from "../componentes/ui";
import { useCentral } from "../contexto";
import { Texto } from "./Mapa";

const SUGESTOES = [
  "Como envio o drone?",
  "O que o robô está fazendo agora?",
  "Por que o botão de plantar está bloqueado?",
  "Quais casas precisam sair?",
  "O que significa o código alerta_ativo?",
  "Como ativo as notificações no celular?",
];

export function Guardiao() {
  const { info } = useCentral();
  const [mensagens, setMensagens] = useState<MensagemChat[]>([]);
  const [texto, setTexto] = useState("");
  const [pensando, setPensando] = useState(false);
  const [comFoto, setComFoto] = useState(false);
  const fim = useRef<HTMLDivElement>(null);

  useEffect(() => {
    // não retornar o resultado: em navegadores novos scrollIntoView devolve uma Promise
    void fim.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [mensagens, pensando]);

  // o resultado da foto entra na conversa, para o Guardião poder comentar depois
  const registrarFoto = (r: RespostaFoto) => {
    const a = r.analise;
    const texto = [
      `**Análise de foto — risco ${a.risco}**`,
      a.resumo,
      ...a.sinais.map((s) => `- ${s.descricao} (${s.gravidade})`),
      `**O que fazer:** ${a.recomendacoes.join(" ")}`,
    ].join("\n");
    setMensagens((m) => [
      ...m,
      { role: "user", content: "Enviei uma foto para análise." },
      { role: "assistant", content: texto, meta: `IA · ${r.modelo} · triagem visual, não substitui vistoria` },
    ]);
  };

  const enviar = async (pergunta: string) => {
    const p = pergunta.trim();
    if (!p || pensando) return;
    const historico = mensagens;
    setMensagens([...historico, { role: "user", content: p }]);
    setTexto("");
    setPensando(true);
    try {
      const r = await api.chat(p, historico);
      const meta = [r.modo === "ia" ? `IA · ${r.modelo}` : "modo offline", r.fontes.length ? `fontes: ${r.fontes.join("; ")}` : "", r.aviso ? `aviso: ${r.aviso}` : ""]
        .filter(Boolean)
        .join(" · ");
      setMensagens((m) => [...m, { role: "assistant", content: r.texto, meta }]);
    } catch (e) {
      setMensagens((m) => [...m, { role: "assistant", content: `Não consegui responder: ${(e as ErroApi).message}` }]);
    } finally {
      setPensando(false);
    }
  };

  return (
    <div className="tela tela--chat" data-testid="tela-guardiao">
      <div className="chat__topo">
        <span className={`pilula ${info?.ia_online ? "pilula--ok" : "pilula--off"}`} data-testid="modo-ia">
          {info?.ia_online ? `IA online · ${info.modelo_ia}` : "Modo offline (sem chave de IA)"}
        </span>
        {mensagens.length > 0 && (
          <button type="button" className="botao botao--fantasma" data-testid="btn-limpar-chat" onClick={() => setMensagens([])}>
            Limpar
          </button>
        )}
      </div>
      <div className="chat" data-testid="chat-mensagens" aria-live="polite">
        {mensagens.length === 0 && (
          <div className="msg msg--assistant">
            <p>
              Olá! Sou o <strong>Guardião</strong>. Posso explicar como usar o app, o que o drone encontrou, o estado da frota e
              os erros e códigos de recusa. Em perigo real, ligue <strong>199</strong>.
            </p>
          </div>
        )}
        {mensagens.map((m, i) => (
          <div key={i} className={`msg msg--${m.role}`} data-testid={`msg-${i}`}>
            <Texto texto={m.content} />
            {m.meta && <span className="msg__meta">{m.meta}</span>}
          </div>
        ))}
        {pensando && <div className="msg msg--assistant msg--pensando">Guardião pensando…</div>}
        <div ref={fim} />
      </div>
      <div className="chips chips--rolagem">
        {SUGESTOES.map((s) => (
          <button key={s} type="button" className="chip" onClick={() => void enviar(s)} disabled={pensando}>
            {s}
          </button>
        ))}
      </div>
      <form
        className="chat__entrada"
        onSubmit={(e) => {
          e.preventDefault();
          void enviar(texto);
        }}
      >
        <button
          type="button"
          className="botao"
          data-testid="btn-foto-chat"
          aria-label="Analisar uma foto com IA"
          title="Analisar uma foto com IA"
          onClick={() => setComFoto(true)}
        >
          <Camera size={20} aria-hidden />
        </button>
        <input
          id="chat-pergunta"
          data-testid="chat-pergunta"
          value={texto}
          onChange={(e) => setTexto(e.target.value)}
          placeholder="Pergunte ao Guardião…"
          aria-label="Pergunta para o Guardião"
          maxLength={1000}
          autoComplete="off"
        />
        <button type="submit" className="botao botao--primario" data-testid="chat-enviar" disabled={pensando || !texto.trim()}>
          Enviar
        </button>
      </form>
      <Folha aberta={comFoto} titulo="Analisar foto com IA" aoFechar={() => setComFoto(false)} teste="folha-foto">
        <AnalisarFoto aoAnalisar={registrarFoto} />
      </Folha>
    </div>
  );
}

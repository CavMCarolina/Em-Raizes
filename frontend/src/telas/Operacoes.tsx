import { Circle, Siren, TriangleAlert, type LucideIcon } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { api } from "../api/cliente";
import type { Comando, Evento } from "../api/tipos";
import { Barra, Cartao, Pilula } from "../componentes/ui";
import { INTERVALO_LISTAS_MS } from "../config";
import { usePolling } from "../hooks/usePolling";
import { hora, resumoComando, ROTULO_STATUS, ROTULO_TIPO } from "../util/formatos";

const COR_STATUS: Record<Comando["status"], string> = {
  em_execucao: "#1565c0",
  concluido: "#2e7d32",
  recusado: "#c62828",
  cancelado: "#757575",
};
const COR_ORIGEM: Record<Comando["origem"], string> = { admin: "#455a64", sistema: "#9e9e9e" };
const ICONE_NIVEL: Record<Evento["nivel"], LucideIcon> = { info: Circle, aviso: TriangleAlert, perigo: Siren };

function IconeNivel({ nivel }: { nivel: Evento["nivel"] }) {
  const Icone = ICONE_NIVEL[nivel];
  return <Icone size={nivel === "info" ? 8 : 16} className={`evento__icone evento__icone--${nivel}`} aria-hidden />;
}

function LinhaComando({ c }: { c: Comando }) {
  const [aberto, setAberto] = useState(false);
  const ignoradas = Object.entries(c.ignoradas);
  return (
    <li className="comando" data-testid={`comando-${c.id}`} data-status={c.status} data-tipo={c.tipo} data-origem={c.origem}>
      <button type="button" className="comando__cabeca" onClick={() => setAberto(!aberto)} aria-expanded={aberto}>
        <span className="comando__id">{c.id}</span>
        <span className="comando__tipo">{ROTULO_TIPO[c.tipo]}</span>
        <Pilula cor={COR_STATUS[c.status]}>{ROTULO_STATUS[c.status]}</Pilula>
        <Pilula cor={COR_ORIGEM[c.origem]}>{c.origem}</Pilula>
      </button>
      <div className="comando__resumo">
        <span>{hora(c.criado_em)}</span> · <span>{resumoComando(c)}</span>
      </div>
      {c.status === "em_execucao" && <Barra valor={c.progresso} cor="#1565c0" rotulo={`Progresso ${c.id}`} />}
      {aberto && (
        <div className="comando__detalhe">
          {c.codigo_recusa && (
            <p>
              Código: <code>{c.codigo_recusa}</code>
            </p>
          )}
          {c.celulas.length > 0 && <p>Células: {c.celulas.join(", ")}</p>}
          {ignoradas.length > 0 && (
            <>
              <p>Ficaram de fora:</p>
              <ul>
                {ignoradas.map(([cel, motivo]) => (
                  <li key={cel}>
                    <strong>{cel}</strong>: {motivo}
                  </li>
                ))}
              </ul>
            </>
          )}
          {typeof c.resultado.observacao === "string" && <p className="mudo">{c.resultado.observacao}</p>}
          <p className="mudo">
            Duração {c.duracao_s}s · concluído {hora(c.concluido_em)}
            {c.chave_idempotencia ? ` · chave ${c.chave_idempotencia.slice(0, 18)}…` : ""}
          </p>
        </div>
      )}
    </li>
  );
}

export function Operacoes() {
  const [aba, setAba] = useState<"comandos" | "eventos">("comandos");
  const { dados: comandos } = usePolling(() => api.comandos(60), INTERVALO_LISTAS_MS);
  const [eventos, setEventos] = useState<Evento[]>([]);
  const ultimo = useRef(0);

  useEffect(() => {
    let vivo = true;
    const buscar = async () => {
      try {
        const novos = await api.eventos(ultimo.current);
        if (!vivo || novos.length === 0) return;
        ultimo.current = novos[novos.length - 1].id;
        setEventos((ev) => [...novos.reverse(), ...ev].slice(0, 200));
      } catch {
        /* tenta de novo no próximo ciclo */
      }
    };
    void buscar();
    const id = window.setInterval(buscar, INTERVALO_LISTAS_MS);
    return () => {
      vivo = false;
      window.clearInterval(id);
    };
  }, []);

  return (
    <div className="tela" data-testid="tela-operacoes">
      <div className="chips" role="tablist">
        <button type="button" role="tab" aria-selected={aba === "comandos"} className={`chip${aba === "comandos" ? " chip--ativo" : ""}`} data-testid="aba-comandos" onClick={() => setAba("comandos")}>
          Comandos
        </button>
        <button type="button" role="tab" aria-selected={aba === "eventos"} className={`chip${aba === "eventos" ? " chip--ativo" : ""}`} data-testid="aba-eventos" onClick={() => setAba("eventos")}>
          Eventos
        </button>
      </div>
      {/* no celular uma aba de cada vez; no computador as duas lado a lado (o CSS esconde a inativa só no celular) */}
      <div className="paineis">
        <div className="painel painel--comandos" data-ativo={aba === "comandos"}>
          <Cartao titulo="Histórico de comandos" acao={<span className="mudo">admin e sistema</span>}>
            {!comandos ? (
              <p className="mudo">Carregando…</p>
            ) : comandos.length === 0 ? (
              <p className="mudo">Nenhum comando ainda. Use os botões da tela Início.</p>
            ) : (
              <ul className="lista" data-testid="lista-comandos">
                {comandos.map((c) => (
                  <LinhaComando key={c.id} c={c} />
                ))}
              </ul>
            )}
          </Cartao>
        </div>
        <div className="painel painel--eventos" data-ativo={aba === "eventos"}>
          <Cartao titulo="Eventos" acao={<span className="mudo">mais recentes primeiro</span>}>
            <ul className="lista eventos" data-testid="lista-eventos">
              {eventos.map((e) => (
                <li key={e.id} className={`evento evento--${e.nivel}`} data-testid={`evento-${e.id}`} data-tipo={e.tipo}>
                  <span className="evento__hora">{hora(e.quando)}</span>
                  <IconeNivel nivel={e.nivel} />
                  <span>{e.mensagem}</span>
                </li>
              ))}
            </ul>
          </Cartao>
        </div>
      </div>
    </div>
  );
}

import { Ban, CircleCheck, Info, TriangleAlert, X, type LucideIcon } from "lucide-react";
import { useEffect, type ReactNode } from "react";
import type { Aviso } from "../contexto";

/**
 * Botão de ação. `id` vira `id` e `data-testid` — seletores estáveis para os testes.
 * Quando desabilitado, o motivo aparece embaixo e fica em `data-motivo`.
 */
export function BotaoAcao(props: {
  id: string;
  icone: ReactNode;
  rotulo: string;
  dica?: string;
  onClick: () => void;
  desabilitado?: boolean;
  motivo?: string;
  variante?: "primario" | "perigo" | "neutro" | "sucesso";
  carregando?: boolean;
}) {
  const { id, icone, rotulo, dica, onClick, desabilitado, motivo, variante = "neutro", carregando } = props;
  return (
    <button
      type="button"
      id={id}
      data-testid={id}
      className={`acao acao--${variante}`}
      onClick={onClick}
      disabled={desabilitado || carregando}
      aria-label={rotulo}
      aria-busy={carregando || undefined}
      data-motivo={desabilitado ? motivo : undefined}
    >
      <span className="acao__icone" aria-hidden>
        {icone}
      </span>
      <span className="acao__textos">
        <span className="acao__rotulo">{rotulo}</span>
        <span className="acao__dica">{desabilitado && motivo ? motivo : dica}</span>
      </span>
    </button>
  );
}

/** Texto escuro sobre cores claras (ex.: amarelo do risco moderado), branco nas demais. */
export function corDoTexto(fundo: string): string {
  const m = /^#([0-9a-f]{6})$/i.exec(fundo);
  if (!m) return "#fff";
  const n = parseInt(m[1], 16);
  const [r, g, b] = [(n >> 16) & 255, (n >> 8) & 255, n & 255];
  return (0.299 * r + 0.587 * g + 0.114 * b) / 255 > 0.62 ? "#1b1b1b" : "#fff";
}

export function Pilula({ cor, children, teste }: { cor: string; children: ReactNode; teste?: string }) {
  return (
    <span className="pilula" style={{ background: cor, color: corDoTexto(cor) }} data-testid={teste}>
      {children}
    </span>
  );
}

export function Barra({ valor, cor, rotulo }: { valor: number; cor?: string; rotulo?: string }) {
  const v = Math.max(0, Math.min(100, valor));
  return (
    <div className="barra" role="progressbar" aria-valuenow={Math.round(v)} aria-valuemin={0} aria-valuemax={100} aria-label={rotulo}>
      <div className="barra__cheio" style={{ width: `${v}%`, background: cor }} />
    </div>
  );
}

export function Cartao({ titulo, acao, children, teste }: { titulo?: ReactNode; acao?: ReactNode; children: ReactNode; teste?: string }) {
  return (
    <section className="cartao" data-testid={teste}>
      {(titulo || acao) && (
        <header className="cartao__cabeca">
          {titulo && <h2>{titulo}</h2>}
          {acao}
        </header>
      )}
      {children}
    </section>
  );
}

export function Numero({ rotulo, valor, detalhe, teste }: { rotulo: string; valor: ReactNode; detalhe?: ReactNode; teste?: string }) {
  return (
    <div className="numero" data-testid={teste}>
      <span className="numero__rotulo">{rotulo}</span>
      <span className="numero__valor">{valor}</span>
      {detalhe && <span className="numero__detalhe">{detalhe}</span>}
    </div>
  );
}

export function Dialogo(props: {
  aberto: boolean;
  titulo: string;
  children: ReactNode;
  confirmar: string;
  perigo?: boolean;
  aoConfirmar: () => void;
  aoCancelar: () => void;
  teste: string;
}) {
  const { aberto, titulo, children, confirmar, perigo, aoConfirmar, aoCancelar, teste } = props;
  useEffect(() => {
    if (!aberto) return;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && aoCancelar();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [aberto, aoCancelar]);
  if (!aberto) return null;
  return (
    <div className="veu" onClick={aoCancelar}>
      <div className="dialogo" role="dialog" aria-modal="true" aria-label={titulo} data-testid={teste} onClick={(e) => e.stopPropagation()}>
        <h2>{titulo}</h2>
        <div className="dialogo__corpo">{children}</div>
        <div className="dialogo__botoes">
          <button type="button" className="botao" data-testid={`${teste}-cancelar`} onClick={aoCancelar}>
            Cancelar
          </button>
          <button
            type="button"
            className={`botao ${perigo ? "botao--perigo" : "botao--primario"}`}
            data-testid={`${teste}-confirmar`}
            onClick={aoConfirmar}
          >
            {confirmar}
          </button>
        </div>
      </div>
    </div>
  );
}

export function Folha({ aberta, titulo, aoFechar, children, teste }: { aberta: boolean; titulo: ReactNode; aoFechar: () => void; children: ReactNode; teste: string }) {
  useEffect(() => {
    if (!aberta) return;
    const esc = (e: KeyboardEvent) => e.key === "Escape" && aoFechar();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [aberta, aoFechar]);
  if (!aberta) return null;
  return (
    <div className="veu veu--folha" onClick={aoFechar}>
      <div className="folha" role="dialog" aria-modal="true" data-testid={teste} onClick={(e) => e.stopPropagation()}>
        <div className="folha__alca" aria-hidden />
        <header className="folha__cabeca">
          <h2>{titulo}</h2>
          <button type="button" className="botao botao--fantasma" aria-label="Fechar" data-testid={`${teste}-fechar`} onClick={aoFechar}>
            <X size={20} aria-hidden />
          </button>
        </header>
        <div className="folha__corpo">{children}</div>
      </div>
    </div>
  );
}

const ICONE_AVISO: Record<Aviso["tipo"], LucideIcon> = { sucesso: CircleCheck, recusado: Ban, erro: TriangleAlert, info: Info };

export function AvisoFlutuante({ aviso, aoFechar }: { aviso: Aviso | null; aoFechar: () => void }) {
  useEffect(() => {
    if (!aviso) return;
    const t = window.setTimeout(aoFechar, aviso.tipo === "sucesso" ? 4500 : 8000);
    return () => window.clearTimeout(t);
  }, [aviso, aoFechar]);
  // O aviso flutua sobre a tela e o toque passa por ele (CSS), para não travar o que está embaixo, como o
  // seletor de clima no fim da tela Início. O aviso de sucesso some no primeiro toque; erro e recusa ficam.
  useEffect(() => {
    if (aviso?.tipo !== "sucesso") return;
    document.addEventListener("pointerdown", aoFechar);
    return () => document.removeEventListener("pointerdown", aoFechar);
  }, [aviso, aoFechar]);
  if (!aviso) return null;
  const Icone = ICONE_AVISO[aviso.tipo];
  return (
    <div
      key={aviso.id}
      className={`aviso aviso--${aviso.tipo}`}
      role={aviso.tipo === "erro" || aviso.tipo === "recusado" ? "alert" : "status"}
      data-testid="aviso"
      data-status={aviso.tipo}
      data-codigo={aviso.codigo}
    >
      <Icone size={20} className="aviso__icone" aria-hidden />
      <div>
        <strong>{aviso.titulo}</strong>
        {aviso.texto && <p>{aviso.texto}</p>}
      </div>
      <button type="button" className="botao botao--fantasma" aria-label="Fechar aviso" onClick={aoFechar}>
        <X size={18} aria-hidden />
      </button>
    </div>
  );
}

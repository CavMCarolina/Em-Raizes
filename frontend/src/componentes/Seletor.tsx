import { Check, ChevronDown } from "lucide-react";
import { useEffect, useId, useRef, useState, type KeyboardEvent } from "react";

export type OpcaoSeletor = { valor: string; nome: string; detalhe?: string };

/**
 * Dropdown desenhado pela própria página (botão + lista), no lugar de um <select>.
 * A lista nativa do <select> é desenhada pelo navegador: não abre em alguns navegadores embutidos e pode fechar
 * sozinha quando a tela se atualiza (o app consulta a central a cada 2 s). Esta lista não depende disso.
 * Teclado: setas abrem e andam, Enter/Espaço escolhem, Esc fecha. Tocar fora também fecha.
 */
export function Seletor({
  id,
  rotulo,
  opcoes,
  valor,
  aoMudar,
}: {
  id: string;
  rotulo: string;
  opcoes: OpcaoSeletor[];
  valor: string;
  aoMudar: (valor: string) => void;
}) {
  const [aberto, setAberto] = useState(false);
  const [destaque, setDestaque] = useState(0);
  const [paraCima, setParaCima] = useState(false);
  const raiz = useRef<HTMLDivElement>(null);
  const botao = useRef<HTMLButtonElement>(null);
  const idLista = useId();
  const escolhida = opcoes.find((o) => o.valor === valor);

  useEffect(() => {
    if (!aberto) return;
    const fora = (e: Event) => {
      if (!raiz.current?.contains(e.target as Node)) setAberto(false);
    };
    document.addEventListener("pointerdown", fora);
    return () => document.removeEventListener("pointerdown", fora);
  }, [aberto]);

  const abrir = () => {
    // abre para cima quando falta espaço embaixo (o cartão do clima fica no fim da tela, acima das abas)
    const r = botao.current?.getBoundingClientRect();
    const altura = Math.min(opcoes.length * 48 + 16, 320);
    setParaCima(!!r && window.innerHeight - r.bottom < altura + 80 && r.top > altura);
    setDestaque(Math.max(0, opcoes.findIndex((o) => o.valor === valor)));
    setAberto(true);
  };

  const escolher = (v: string) => {
    aoMudar(v);
    setAberto(false);
    botao.current?.focus();
  };

  const teclas = (e: KeyboardEvent) => {
    if (!aberto) {
      if (["ArrowDown", "ArrowUp", "Enter", " "].includes(e.key)) {
        e.preventDefault();
        abrir();
      }
      return;
    }
    if (e.key === "Escape") {
      e.preventDefault();
      setAberto(false);
    } else if (e.key === "ArrowDown") {
      e.preventDefault();
      setDestaque((i) => Math.min(i + 1, opcoes.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setDestaque((i) => Math.max(i - 1, 0));
    } else if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
      if (opcoes[destaque]) escolher(opcoes[destaque].valor);
    } else if (e.key === "Tab") {
      setAberto(false);
    }
  };

  return (
    <div className="seletor" ref={raiz}>
      <button
        ref={botao}
        type="button"
        id={id}
        data-testid={id}
        data-valor={valor}
        className="seletor__botao"
        role="combobox"
        aria-label={rotulo}
        aria-haspopup="listbox"
        aria-expanded={aberto}
        aria-controls={idLista}
        aria-activedescendant={aberto ? `${idLista}-${destaque}` : undefined}
        onClick={() => (aberto ? setAberto(false) : abrir())}
        onKeyDown={teclas}
      >
        <span className="seletor__texto">{escolhida?.nome ?? "Escolha uma opção"}</span>
        <ChevronDown size={18} aria-hidden className="seletor__seta" />
      </button>
      {aberto && (
        <ul
          id={idLista}
          role="listbox"
          aria-label={rotulo}
          className={`seletor__lista${paraCima ? " seletor__lista--cima" : ""}`}
          data-testid={`${id}-lista`}
        >
          {opcoes.map((o, i) => (
            <li
              key={o.valor}
              id={`${idLista}-${i}`}
              role="option"
              aria-selected={o.valor === valor}
              className="seletor__opcao"
              data-destaque={i === destaque}
              data-testid={`${id}-opcao-${o.valor}`}
              onPointerEnter={() => setDestaque(i)}
              onClick={() => escolher(o.valor)}
            >
              <span className="seletor__nome">{o.nome}</span>
              {o.detalhe && <span className="seletor__detalhe">{o.detalhe}</span>}
              {o.valor === valor && <Check size={16} aria-hidden className="seletor__marca" />}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

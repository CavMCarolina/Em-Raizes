import { Camera, ImagePlus, ScanSearch, ShieldAlert } from "lucide-react";
import { useRef, useState } from "react";
import { api, ErroApi } from "../api/cliente";
import type { AnaliseFoto, RespostaFoto } from "../api/tipos";
import { useCentral } from "../contexto";
import { prepararFoto } from "../util/imagem";
import { Pilula } from "./ui";

export const COR_RISCO_FOTO: Record<AnaliseFoto["risco"], string> = {
  baixo: "#2e7d32",
  moderado: "#fbc02d",
  alto: "#ef6c00",
  critico: "#c62828",
  indeterminado: "#607d8b",
};

const NOME_RISCO: Record<AnaliseFoto["risco"], string> = {
  baixo: "Baixo",
  moderado: "Moderado",
  alto: "Alto",
  critico: "Crítico",
  indeterminado: "Indeterminado",
};

const NOME_SINAL: Record<string, string> = {
  trinca_no_solo: "Trinca no solo",
  trinca_em_parede: "Trinca em parede",
  erosao: "Erosão",
  solo_exposto: "Solo exposto",
  agua_ou_vazamento: "Água ou vazamento",
  muro_ou_poste_inclinado: "Muro ou poste inclinado",
  arvore_inclinada: "Árvore inclinada",
  degrau_no_terreno: "Degrau no terreno",
  entulho_ou_lixo: "Entulho ou lixo",
  outro: "Outro",
};

export function ResultadoFoto({ r }: { r: RespostaFoto }) {
  const a = r.analise;
  return (
    <div className="resultado-foto" data-testid="resultado-foto" data-risco={a.risco}>
      <div className="linha-pilulas">
        <Pilula cor={COR_RISCO_FOTO[a.risco]} teste="risco-foto">
          Risco: {NOME_RISCO[a.risco]}
        </Pilula>
        <span className="mudo pequeno">confiança {a.confianca}</span>
      </div>
      <p>{a.resumo}</p>
      {a.sinais.length > 0 && (
        <>
          <h3>Sinais vistos na foto</h3>
          <ul className="sinais">
            {a.sinais.map((s, i) => (
              <li key={i} className={`sinal sinal--${s.gravidade}`}>
                <strong>{NOME_SINAL[s.tipo] ?? s.tipo}</strong> <span className="mudo">({s.gravidade})</span> — {s.descricao}
              </li>
            ))}
          </ul>
        </>
      )}
      <h3>O que fazer</h3>
      <ol className="plano">
        {a.recomendacoes.map((rec, i) => (
          <li key={i}>{rec}</li>
        ))}
      </ol>
      <p className="mudo pequeno">
        IA · {r.modelo} · {r.latencia_s}s. Triagem visual: não substitui a vistoria da Defesa Civil.
      </p>
    </div>
  );
}

/** Tirar/escolher uma foto e pedir a triagem visual à IA. */
export function AnalisarFoto({ celulaInicial, aoAnalisar }: { celulaInicial?: string; aoAnalisar?: (r: RespostaFoto) => void }) {
  const { info } = useCentral();
  const entrada = useRef<HTMLInputElement>(null);
  const [foto, setFoto] = useState<string | null>(null);
  const [celula, setCelula] = useState(celulaInicial ?? "");
  const [observacao, setObservacao] = useState("");
  const [estado, setEstado] = useState<"livre" | "preparando" | "analisando">("livre");
  const [erro, setErro] = useState<string | null>(null);
  const [resultado, setResultado] = useState<RespostaFoto | null>(null);
  const iaOnline = info?.analise_foto ?? false;

  const escolher = async (arquivo?: File) => {
    if (!arquivo) return;
    setErro(null);
    setResultado(null);
    setEstado("preparando");
    try {
      setFoto(await prepararFoto(arquivo));
    } catch (e) {
      setErro((e as Error).message);
    } finally {
      setEstado("livre");
    }
  };

  const analisar = async () => {
    if (!foto) return;
    setEstado("analisando");
    setErro(null);
    try {
      const r = await api.foto(foto, observacao, celula.trim().toUpperCase() || undefined);
      setResultado(r);
      aoAnalisar?.(r);
    } catch (e) {
      setErro((e as ErroApi).message);
    } finally {
      setEstado("livre");
    }
  };

  return (
    <div className="analisar-foto" data-testid="analisar-foto">
      {!iaOnline && (
        <p className="faixa faixa--aviso" data-testid="foto-ia-offline">
          A análise de foto precisa da IA online. Configure <code>OPENROUTER_API_KEY</code> no servidor.
        </p>
      )}
      <input
        ref={entrada}
        type="file"
        accept="image/*"
        capture="environment"
        hidden
        data-testid="foto-arquivo"
        onChange={(e) => void escolher(e.target.files?.[0])}
      />
      {foto ? (
        <button type="button" className="foto-previa" onClick={() => entrada.current?.click()} aria-label="Trocar foto">
          <img src={foto} alt="Foto escolhida para análise" />
        </button>
      ) : (
        <button type="button" className="botao botao--grande foto-escolher" data-testid="btn-escolher-foto" onClick={() => entrada.current?.click()}>
          <Camera aria-hidden /> {estado === "preparando" ? "Preparando…" : "Tirar ou escolher foto"}
        </button>
      )}
      <div className="linha-form">
        <input value={celula} onChange={(e) => setCelula(e.target.value)} placeholder="Célula (opcional, ex.: L05C12)" aria-label="Célula" maxLength={8} data-testid="foto-celula" />
      </div>
      <textarea
        className="campo"
        value={observacao}
        onChange={(e) => setObservacao(e.target.value)}
        placeholder="Observação (opcional): ex. trinca apareceu depois da chuva de ontem"
        maxLength={300}
        rows={2}
        data-testid="foto-observacao"
      />
      <div className="acoes acoes--compactas">
        {foto && (
          <button type="button" className="botao" onClick={() => entrada.current?.click()}>
            <ImagePlus size={18} aria-hidden /> Outra foto
          </button>
        )}
        <button
          type="button"
          className="botao botao--primario"
          data-testid="btn-analisar-foto"
          disabled={!foto || !iaOnline || estado !== "livre"}
          onClick={() => void analisar()}
        >
          <ScanSearch size={18} aria-hidden /> {estado === "analisando" ? "Analisando…" : "Analisar com IA"}
        </button>
      </div>
      <p className="mudo pequeno com-icone">
        <ShieldAlert size={15} aria-hidden className="ico" /> A foto vai para o provedor de IA. Evite fotografar pessoas, rostos e placas.
      </p>
      {erro && (
        <p className="faixa faixa--erro" role="alert" data-testid="foto-erro">
          {erro}
        </p>
      )}
      {resultado && <ResultadoFoto r={resultado} />}
    </div>
  );
}

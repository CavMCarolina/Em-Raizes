import { Bot, Drone } from "lucide-react";
import type { Celula, Dispositivo, Mapa } from "../api/tipos";
import { COR_CLASSE } from "../util/formatos";

export type Camada = "risco" | "risco_24h" | "umidade" | "vegetacao" | "foto";

export const CAMADAS: { id: Camada; rotulo: string }[] = [
  { id: "risco", rotulo: "Risco agora" },
  { id: "risco_24h", rotulo: "Risco 24 h" },
  { id: "umidade", rotulo: "Umidade" },
  { id: "vegetacao", rotulo: "Vegetação" },
  { id: "foto", rotulo: "Foto do drone" },
];

function escala(v: number, de: [number, number, number], para: [number, number, number]): string {
  const t = Math.max(0, Math.min(1, v));
  const c = de.map((x, i) => Math.round(x + (para[i] - x) * t));
  return `rgb(${c[0]},${c[1]},${c[2]})`;
}

export function corDaCelula(c: Celula, camada: Camada): string {
  switch (camada) {
    case "risco":
      return COR_CLASSE[c.classe_risco];
    case "risco_24h":
      return COR_CLASSE[c.classe_risco_24h];
    case "umidade":
      return escala(c.umidade_pct / 45, [237, 244, 252], [13, 71, 161]);
    case "vegetacao":
      return escala(c.cobertura_vegetal, [215, 190, 150], [27, 94, 32]);
    case "foto":
      return "transparent";
  }
}

/** Grade SVG do morro (linha 0 = topo). Cada célula tem data-testid="celula-LxxCyy" para os testes. */
export function GradeMapa(props: {
  mapa: Mapa;
  camada: Camada;
  selecionada: string | null;
  evacuar: string[];
  dispositivos: Dispositivo[];
  foto?: string | null;
  aoSelecionar: (c: Celula) => void;
}) {
  const { mapa, camada, selecionada, evacuar, dispositivos, foto, aoSelecionar } = props;
  const evac = new Set(evacuar);
  return (
    <svg
      className="grade"
      viewBox={`0 0 ${mapa.colunas} ${mapa.linhas}`}
      role="img"
      aria-label={`Mapa ${mapa.linhas} por ${mapa.colunas} células, camada ${camada}`}
      data-testid="mapa-grade"
      data-voo={mapa.voo_id}
    >
      {camada === "foto" && foto && (
        <image href={foto} x={0} y={0} width={mapa.colunas} height={mapa.linhas} preserveAspectRatio="none" />
      )}
      {mapa.celulas.map((c) => (
        <rect
          key={c.celula}
          x={c.coluna + 0.04}
          y={c.linha + 0.04}
          width={0.92}
          height={0.92}
          rx={0.12}
          fill={corDaCelula(c, camada)}
          className={`grade__celula${selecionada === c.celula ? " grade__celula--sel" : ""}`}
          data-testid={`celula-${c.celula}`}
          data-classe={c.classe_risco}
          onClick={() => aoSelecionar(c)}
        >
          <title>{`${c.celula} · ${c.setor} · risco ${Math.round(c.risco)}`}</title>
        </rect>
      ))}
      {mapa.celulas
        .filter((c) => c.casas > 0)
        .map((c) => (
          <circle key={`casa-${c.celula}`} cx={c.coluna + 0.5} cy={c.linha + 0.5} r={0.1 + 0.05 * c.casas} className="grade__casa" />
        ))}
      {mapa.celulas
        .filter((c) => evac.has(c.celula))
        .map((c) => (
          <rect key={`ev-${c.celula}`} x={c.coluna + 0.08} y={c.linha + 0.08} width={0.84} height={0.84} rx={0.1} className="grade__evacuar" />
        ))}
      {mapa.celulas
        .filter((c) => c.fissura_detectada)
        .map((c) => {
          const [x0, y0, x1, y1] = [c.coluna + 0.3, c.linha + 0.3, c.coluna + 0.7, c.linha + 0.7];
          return <path key={`f-${c.celula}`} d={`M${x0} ${y0}L${x1} ${y1}M${x0} ${y1}L${x1} ${y0}`} className="grade__fissura" />;
        })}
      {dispositivos
        .filter((d) => d.posicao)
        .map((d) => {
          const Icone = d.tipo === "drone" ? Drone : Bot;
          const { linha } = d.posicao!;
          // drone e robô na mesma célula (ex.: na base): desloca o drone uma coluna para os dois aparecerem
          const outro = dispositivos.find((o) => o.id !== d.id && o.posicao?.linha === linha && o.posicao?.coluna === d.posicao!.coluna);
          const coluna = d.posicao!.coluna + (outro && d.tipo === "drone" ? 1 : 0);
          return (
            <g key={d.id} className={`grade__dispositivo grade__dispositivo--${d.tipo}`} data-testid={`posicao-${d.id}`}>
              <circle cx={coluna + 0.5} cy={linha + 0.5} r={0.48} />
              <Icone x={coluna + 0.15} y={linha + 0.15} width={0.7} height={0.7} strokeWidth={2.4} color="#fff" />
            </g>
          );
        })}
    </svg>
  );
}

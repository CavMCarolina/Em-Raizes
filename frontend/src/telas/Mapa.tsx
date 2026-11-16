import { Camera, Droplet, Droplets, MousePointerClick, ScanSearch, Sparkles, Sprout, TriangleAlert } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api/cliente";
import type { Celula, DetalheCelula, Estado, MissaoRobo, RespostaIA } from "../api/tipos";
import { bloqueios } from "../componentes/AcoesFrota";
import { AnalisarFoto } from "../componentes/AnalisarFoto";
import { CAMADAS, GradeMapa, type Camada } from "../componentes/GradeMapa";
import { Barra, Cartao, Folha, Pilula } from "../componentes/ui";
import { useCentral } from "../contexto";
import { COR_CLASSE, dataHora, NOME_CLASSE, porcentagem } from "../util/formatos";

const NOMES_FATORES: Record<string, string> = {
  declividade: "Inclinação",
  saturacao: "Solo encharcado",
  chuva: "Chuva 72 h",
  vegetacao: "Falta de vegetação",
  solo: "Tipo de solo",
  sinais: "Fissuras/erosão",
};

/** Os mesmos símbolos desenhados no mapa, para a legenda. */
function Simbolo({ tipo }: { tipo: "casa" | "evacuar" | "fissura" }) {
  return (
    <svg className={`simbolo simbolo--${tipo}`} viewBox="0 0 10 10" aria-hidden>
      {tipo === "casa" && <circle cx={5} cy={5} r={3} />}
      {tipo === "evacuar" && <rect x={1.5} y={1.5} width={7} height={7} rx={1} />}
      {tipo === "fissura" && <path d="M2 2L8 8M2 8L8 2" />}
    </svg>
  );
}

function Legenda({ camada }: { camada: Camada }) {
  if (camada === "risco" || camada === "risco_24h" || camada === "foto") {
    return (
      <div className="legenda" data-testid="legenda">
        {(Object.keys(COR_CLASSE) as (keyof typeof COR_CLASSE)[]).map((k) =>
          camada === "foto" ? null : (
            <span key={k}>
              <i style={{ background: COR_CLASSE[k] }} /> {NOME_CLASSE[k]}
            </span>
          ),
        )}
        <span>
          <Simbolo tipo="casa" /> casas
        </span>
        <span className="legenda__evacuar">
          <Simbolo tipo="evacuar" /> evacuar
        </span>
        <span>
          <Simbolo tipo="fissura" /> fissura
        </span>
      </div>
    );
  }
  return (
    <div className="legenda" data-testid="legenda">
      <span>{camada === "umidade" ? "Mais claro = seco · mais escuro = úmido" : "Marrom = solo exposto · verde = vegetação"}</span>
      <span>
        <Simbolo tipo="casa" /> casas
      </span>
    </div>
  );
}

function DetalheDaCelula({ celula, estado, aoFechar }: { celula: Celula; estado: Estado; aoFechar: () => void }) {
  const { executar, ocupado } = useCentral();
  const [detalhe, setDetalhe] = useState<DetalheCelula | null>(null);
  const [ia, setIa] = useState<RespostaIA | null>(null);
  const [pensando, setPensando] = useState(false);
  const [comFoto, setComFoto] = useState(false);
  const { motivoRobo } = bloqueios(estado);

  useEffect(() => {
    setDetalhe(null);
    setIa(null);
    setComFoto(false);
    api.celula(celula.celula).then(setDetalhe).catch(() => undefined);
  }, [celula.celula]);

  const missao = (m: MissaoRobo) => void executar(() => api.robo(m, [celula.celula]));
  const contrib = detalhe?.explicacao.contribuicao_pts ?? {};
  const maximo = Math.max(1, ...Object.values(contrib));

  return (
    <Folha
      aberta
      teste="folha-celula"
      aoFechar={aoFechar}
      titulo={
        <>
          {celula.celula} <span className="mudo">· {celula.setor}</span>
        </>
      }
    >
      <div className="linha-pilulas">
        <Pilula cor={COR_CLASSE[celula.classe_risco]} teste="risco-celula">
          Agora: {NOME_CLASSE[celula.classe_risco]} ({Math.round(celula.risco)})
        </Pilula>
        <Pilula cor={COR_CLASSE[celula.classe_risco_24h]}>
          24 h: {NOME_CLASSE[celula.classe_risco_24h]} ({Math.round(celula.risco_24h)})
        </Pilula>
      </div>
      <dl className="dados">
        <dt>Inclinação</dt>
        <dd>{Math.round(celula.declividade_graus)}°</dd>
        <dt>Umidade</dt>
        <dd>
          {Math.round(celula.umidade_pct)}% → {Math.round(celula.umidade_24h)}% em 24 h
        </dd>
        <dt>Vegetação</dt>
        <dd>{porcentagem(celula.cobertura_vegetal)}</dd>
        <dt>Solo</dt>
        <dd>
          {celula.tipo_solo} <span className="mudo">(visão: {celula.solo_visao}, {porcentagem(celula.confianca_visao)})</span>
        </dd>
        <dt>Casas</dt>
        <dd>
          {celula.casas} {celula.casas > 0 && <span className="mudo">(~{Math.round(celula.moradores_estimados)} pessoas)</span>}
        </dd>
        <dt>Visão</dt>
        <dd>
          {celula.fissura_detectada ? (
            <span className="com-icone">
              <TriangleAlert size={15} className="ico ico--aviso" aria-hidden /> fissura
            </span>
          ) : (
            "sem fissura"
          )}{" "}
          ·{" "}
          {celula.vazamento ? (
            <span className="com-icone">
              <Droplet size={15} className="ico ico--agua" aria-hidden /> vazamento
            </span>
          ) : (
            "sem vazamento"
          )}
        </dd>
      </dl>

      <h3>Pontos por fator</h3>
      <div className="fatores">
        {Object.entries(contrib).map(([k, v]) => (
          <div key={k} className="fator">
            <span>{NOMES_FATORES[k] ?? k}</span>
            <Barra valor={(v / maximo) * 100} cor="#ef6c00" rotulo={k} />
            <span>{v.toFixed(0)}</span>
          </div>
        ))}
      </div>

      <div className="acoes acoes--compactas">
        <button type="button" className="botao botao--sucesso" data-testid="btn-celula-plantio" disabled={!!motivoRobo || ocupado} onClick={() => missao("plantio")}>
          <Sprout size={18} aria-hidden /> Plantar aqui
        </button>
        <button type="button" className="botao" data-testid="btn-celula-irrigacao" disabled={!!motivoRobo || ocupado} onClick={() => missao("irrigacao")}>
          <Droplets size={18} aria-hidden /> Irrigar aqui
        </button>
        <button type="button" className="botao" data-testid="btn-celula-inspecao" disabled={!!motivoRobo || ocupado} onClick={() => missao("inspecao")}>
          <ScanSearch size={18} aria-hidden /> Inspecionar
        </button>
        <button
          type="button"
          className="botao botao--primario"
          data-testid="btn-celula-explicar"
          disabled={pensando}
          onClick={async () => {
            setPensando(true);
            try {
              setIa(await api.explicar(celula.celula));
            } finally {
              setPensando(false);
            }
          }}
        >
          <Sparkles size={18} aria-hidden /> {pensando ? "Pensando…" : "Explicar com IA"}
        </button>
        <button type="button" className="botao" data-testid="btn-celula-foto" aria-expanded={comFoto} onClick={() => setComFoto(!comFoto)}>
          <Camera size={18} aria-hidden /> Analisar foto
        </button>
      </div>
      {motivoRobo && <p className="mudo">Robô indisponível: {motivoRobo}.</p>}
      {comFoto && (
        <div className="balao">
          <AnalisarFoto celulaInicial={celula.celula} />
        </div>
      )}
      {ia && (
        <div className="balao" data-testid="explicacao-ia">
          <Texto texto={ia.texto} />
          <p className="mudo">
            {ia.modo === "ia" ? `IA · ${ia.modelo}` : "modo offline"}
            {ia.aviso ? ` · ${ia.aviso}` : ""}
          </p>
        </div>
      )}
    </Folha>
  );
}

/** Remove emojis (e seus modificadores) de textos vindos da IA: a interface usa ícones próprios. */
export function semEmojis(texto: string): string {
  return texto
    .replace(/[\p{Extended_Pictographic}\u{1F1E6}-\u{1F1FF}\u{1F3FB}-\u{1F3FF}\uFE0F\u200D\u20E3]/gu, "")
    .replace(/^[ \t]+/gm, "")
    .replace(/ {2,}/g, " ");
}

/** Renderiza **negrito**, *itálico* e quebras de linha sem usar HTML vindo da IA. */
export function Texto({ texto }: { texto: string }) {
  const limpo = semEmojis(texto);
  return (
    <>
      {limpo.split("\n").map((linha, i) => (
        <p key={i}>
          {linha.split(/(\*\*[^*]+\*\*|\*[^*\s][^*]*\*)/g).map((parte, j) =>
            parte.startsWith("**") && parte.endsWith("**") && parte.length > 4 ? (
              <strong key={j}>{parte.slice(2, -2)}</strong>
            ) : parte.startsWith("*") && parte.endsWith("*") && parte.length > 2 ? (
              <em key={j}>{parte.slice(1, -1)}</em>
            ) : (
              parte
            ),
          )}
        </p>
      ))}
    </>
  );
}

export function Mapa({ estado }: { estado: Estado }) {
  const { mapa } = useCentral();
  const [camada, setCamada] = useState<Camada>("risco");
  const [selecionada, setSelecionada] = useState<Celula | null>(null);
  const [foto, setFoto] = useState<string | null>(null);

  useEffect(() => {
    if (camada !== "foto" || !mapa) return;
    let url: string | null = null;
    api
      .imagemAerea()
      .then((u) => {
        url = u;
        setFoto(u);
      })
      .catch(() => setFoto(null));
    return () => {
      if (url) URL.revokeObjectURL(url);
    };
  }, [camada, mapa?.voo_id]);

  if (!mapa) return <p className="mudo">Carregando mapa…</p>;
  const atual = selecionada ? (mapa.celulas.find((c) => c.celula === selecionada.celula) ?? null) : null;

  return (
    <div className="tela tela--mapa" data-testid="tela-mapa">
      <Cartao
        titulo="Mapa do morro"
        acao={<span className="mudo">{mapa.voo_id} · {dataHora(mapa.data_voo)}</span>}
      >
        <div className="chips" role="tablist" aria-label="Camada do mapa">
          {CAMADAS.map((c) => (
            <button
              key={c.id}
              type="button"
              role="tab"
              aria-selected={camada === c.id}
              className={`chip${camada === c.id ? " chip--ativo" : ""}`}
              data-testid={`camada-${c.id}`}
              onClick={() => setCamada(c.id)}
            >
              {c.rotulo}
            </button>
          ))}
        </div>
        <GradeMapa
          mapa={mapa}
          camada={camada}
          foto={foto}
          selecionada={atual?.celula ?? null}
          evacuar={estado.alerta.celulas_evacuar}
          dispositivos={estado.dispositivos}
          aoSelecionar={setSelecionada}
        />
        <p className="mudo pequeno">Topo do morro em cima, base (rua) embaixo. Toque numa célula para ver detalhes e agir.</p>
        <Legenda camada={camada} />
      </Cartao>
      {atual ? (
        <DetalheDaCelula celula={atual} estado={estado} aoFechar={() => setSelecionada(null)} />
      ) : (
        // só aparece no computador, no lugar onde o detalhe da célula fica fixo ao lado do mapa
        <aside className="cartao mapa-dica">
          <MousePointerClick size={28} className="ico" aria-hidden />
          <h2>Escolha uma célula</h2>
          <p className="mudo">
            Clique num quadrado do mapa para ver os dados, os fatores de risco e agir: plantar, irrigar, inspecionar ou
            pedir uma explicação à IA.
          </p>
        </aside>
      )}
    </div>
  );
}

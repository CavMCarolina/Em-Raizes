import { ListChecks, MessageSquareText, Phone } from "lucide-react";
import { useState } from "react";
import { api } from "../api/cliente";
import type { Estado, RespostaIA, RespostaPlano } from "../api/tipos";
import { Cartao, Numero } from "../componentes/ui";
import { useCentral } from "../contexto";
import { usePolling } from "../hooks/usePolling";
import { inteiro } from "../util/formatos";

function GraficoChuva({ vooId }: { vooId: string }) {
  const { dados } = usePolling(api.chuva, 0, !!vooId);
  if (!dados) return null;
  const max = Math.max(10, ...dados.map((d) => d.chuva_mm));
  return (
    <div className="chuva" role="img" aria-label="Chuva por dia nos últimos 7 dias e previsão de amanhã" data-testid="grafico-chuva">
      {dados.map((d) => (
        <div key={d.data} className="chuva__coluna">
          <span className="chuva__valor">{inteiro(d.chuva_mm)}</span>
          <div className={`chuva__barra chuva__barra--${d.tipo}`} style={{ height: `${(d.chuva_mm / max) * 100}%` }} />
          <span className="chuva__dia">{d.tipo === "prevista" ? "amanhã" : d.data.slice(8, 10) + "/" + d.data.slice(5, 7)}</span>
        </div>
      ))}
    </div>
  );
}

export function Alertas({ estado }: { estado: Estado }) {
  const { mapa } = useCentral();
  const [sms, setSms] = useState<RespostaIA | null>(null);
  const [plano, setPlano] = useState<RespostaPlano | null>(null);
  const [carregando, setCarregando] = useState<"sms" | "plano" | null>(null);
  const al = estado.alerta;
  const porCelula = new Map(mapa?.celulas.map((c) => [c.celula, c]));
  const evacuar = al.celulas_evacuar.map((id) => porCelula.get(id)).filter((c) => !!c);

  const gerar = async (tipo: "sms" | "plano") => {
    setCarregando(tipo);
    try {
      if (tipo === "sms") setSms(await api.sms());
      else setPlano(await api.plano());
    } finally {
      setCarregando(null);
    }
  };

  return (
    <div className="tela tela--duas" data-testid="tela-alertas">
      <div className="tela__coluna tela__coluna--principal">
        <Cartao titulo="Situação" teste="cartao-situacao">
          <div className="numeros">
            <Numero rotulo="Nível" valor={al.titulo} teste="nivel-alerta" />
            <Numero rotulo="Casas a evacuar/preparar" valor={al.casas_em_risco} />
            <Numero rotulo="Pessoas (estimativa)" valor={inteiro(al.pessoas_em_risco)} />
            <Numero rotulo="Fissuras detectadas" valor={estado.estatisticas.fissuras} />
          </div>
          <p>
            <strong>O que fazer:</strong> {al.acao}
          </p>
        </Cartao>

        <Cartao titulo="Chuva" acao={<span className="mudo">azul claro = previsão</span>}>
          <GraficoChuva vooId={`${estado.ultimo_voo.voo_id}-${estado.clima_atual.cenario}`} />
          <p className="mudo pequeno" data-testid="fonte-grafico-chuva">
            {estado.clima_atual.real
              ? `${estado.clima_atual.nome}: barras diárias estimadas pelo Open-Meteo; o acumulado de 72 h usado no risco vem dos pluviômetros do Cemaden.`
              : "Chuva simulada (cenário de teste)."}
          </p>
        </Cartao>

        <Cartao titulo={`Casas a evacuar ou preparar (${evacuar.length})`} teste="cartao-evacuar">
          {evacuar.length === 0 ? (
            <p className="mudo">Nenhuma casa precisa sair agora (dados simulados).</p>
          ) : (
            <div className="tabela-rolagem">
              <table className="tabela" data-testid="tabela-evacuar">
                <thead>
                  <tr>
                    <th>Célula</th>
                    <th>Setor</th>
                    <th>Casas</th>
                    <th>Risco 24 h</th>
                  </tr>
                </thead>
                <tbody>
                  {evacuar.map((c) => (
                    <tr key={c.celula}>
                      <td>{c.celula}</td>
                      <td>{c.setor}</td>
                      <td>{c.casas}</td>
                      <td>{Math.round(c.risco_24h)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Cartao>
      </div>

      <div className="tela__coluna tela__coluna--lateral">
        <Cartao titulo="Comunicação com IA">
          <div className="acoes acoes--compactas">
            <button type="button" className="botao botao--primario" data-testid="btn-gerar-sms" disabled={carregando !== null} onClick={() => void gerar("sms")}>
              <MessageSquareText size={18} aria-hidden /> {carregando === "sms" ? "Gerando…" : "Gerar SMS de alerta"}
            </button>
            <button type="button" className="botao" data-testid="btn-gerar-plano" disabled={carregando !== null} onClick={() => void gerar("plano")}>
              <ListChecks size={18} aria-hidden /> {carregando === "plano" ? "Gerando…" : "Gerar plano de ação"}
            </button>
          </div>
          {sms && (
            <div className="sms" data-testid="sms-gerado">
              <p>{sms.texto}</p>
              <span className="mudo">
                {sms.texto.length}/160 caracteres · {sms.modo === "ia" ? `IA · ${sms.modelo}` : "modelo pronto (offline)"}
                {sms.aviso ? ` · ${sms.aviso}` : ""} · o MVP não envia SMS de verdade
              </span>
            </div>
          )}
          {plano && (
            <div data-testid="plano-gerado">
              <p className="mudo">{plano.plano.resumo}</p>
              <ol className="plano">
                {plano.plano.acoes.map((a, i) => (
                  <li key={i}>
                    <strong>
                      P{a.prioridade} · {a.tipo}
                    </strong>{" "}
                    — {a.descricao} <span className="mudo">({a.local} · {a.responsavel})</span>
                  </li>
                ))}
              </ol>
              <span className="mudo">{plano.modo === "ia" ? `IA · ${plano.modelo} · JSON validado` : "plano por regras (offline)"}</span>
            </div>
          )}
        </Cartao>

        <p className="faixa faixa--info com-icone">
          <Phone size={18} aria-hidden className="ico" />
          <span>
            Emergência: Defesa Civil <strong>199</strong> · Bombeiros <strong>193</strong> · SAMU <strong>192</strong>
          </span>
        </p>
      </div>
    </div>
  );
}

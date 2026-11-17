import { BatteryFull, BatteryLow, BatteryMedium, BatteryWarning, Bot, CloudRain, Drone } from "lucide-react";
import { useEffect, useState } from "react";
import { api } from "../api/cliente";
import type { Dispositivo, Estado, MissaoRobo, Recomendacao } from "../api/tipos";
import { AcoesFrota } from "../componentes/AcoesFrota";
import { CartaoNotificacoes } from "../componentes/CartaoNotificacoes";
import { Seletor } from "../componentes/Seletor";
import { Barra, Cartao, Numero, Pilula } from "../componentes/ui";
import { useCentral } from "../contexto";
import { corBateria, dataHora, hora, inteiro, ROTULO_DISPOSITIVO, ROTULO_TIPO } from "../util/formatos";

const COR_STATUS: Record<Dispositivo["status"], string> = { na_base: "#546e7a", em_missao: "#1565c0", parado: "#c62828" };
const COR_PRIORIDADE: Record<Recomendacao["prioridade"], string> = { alta: "#c62828", media: "#ef6c00", baixa: "#546e7a" };

function IconeBateria({ valor }: { valor: number }) {
  const Icone = valor < 20 ? BatteryWarning : valor < 40 ? BatteryLow : valor < 75 ? BatteryMedium : BatteryFull;
  return <Icone size={18} color={corBateria(valor)} aria-hidden className="ico" />;
}

function CartaoDispositivo({ d, estado }: { d: Dispositivo; estado: Estado }) {
  const cmd = estado.comandos_ativos.find((c) => c.id === d.comando_atual);
  return (
    <div className="dispositivo" data-testid={`dispositivo-${d.id}`} data-status={d.status}>
      <div className="dispositivo__topo">
        <span className={`dispositivo__icone dispositivo__icone--${d.tipo}`} aria-hidden>
          {d.tipo === "drone" ? <Drone size={24} /> : <Bot size={24} />}
        </span>
        <div>
          <strong>{d.nome}</strong>
          <div className="mudo">{d.id}</div>
        </div>
        <Pilula cor={COR_STATUS[d.status]} teste={`status-${d.id}`}>
          {ROTULO_DISPOSITIVO[d.status]}
        </Pilula>
      </div>
      <div className="dispositivo__linha">
        <span className="com-icone">
          <IconeBateria valor={d.bateria} /> {Math.round(d.bateria)}%
        </span>
        <Barra valor={d.bateria} cor={corBateria(d.bateria)} rotulo={`Bateria ${d.nome}`} />
      </div>
      {cmd && (
        <div className="dispositivo__linha" data-testid={`progresso-${d.id}`}>
          <span>
            {ROTULO_TIPO[cmd.tipo]} · {cmd.progresso}%
          </span>
          <Barra valor={cmd.progresso} cor="#1565c0" rotulo={`Progresso ${cmd.id}`} />
        </div>
      )}
    </div>
  );
}

function Simulacao({ estado }: { estado: Estado }) {
  const { info, executar, ocupado } = useCentral();
  const atual = estado.clima_atual.cenario;
  const [cenario, setCenario] = useState(atual);
  // se o clima mudar por outro caminho (outra aba, API), o seletor acompanha
  useEffect(() => setCenario(atual), [atual]);
  const cenarios = info?.cenarios ?? {};
  return (
    <details className="cartao simulacao" data-testid="simulacao">
      <summary>
        <CloudRain size={18} aria-hidden className="ico" /> Clima: chuva real ou simulada
      </summary>
      <p className="mudo">
        "Chuva real" usa os pluviômetros do Cemaden e a previsão do Open-Meteo, atualizados a cada 10 minutos. Os cenários
        simulados servem para testar o app em qualquer clima. Depois de trocar, envie o drone para atualizar o mapa.
      </p>
      <div className="linha-form">
        {/* dropdown do próprio app, não um <select> nativo: ver o comentário em componentes/Seletor.tsx */}
        <Seletor
          id="sel-clima"
          rotulo="Fonte do clima"
          valor={cenario}
          aoMudar={setCenario}
          opcoes={Object.entries(cenarios).map(([k, nome]) => ({ valor: k, nome, detalhe: k === atual ? "atual" : undefined }))}
        />
        <button
          type="button"
          id="btn-aplicar-clima"
          data-testid="btn-aplicar-clima"
          className="botao botao--primario"
          disabled={ocupado || cenario === estado.clima_atual.cenario}
          onClick={() => void executar(() => api.mudarClima(cenario))}
        >
          Aplicar
        </button>
      </div>
    </details>
  );
}

export function Inicio({ estado }: { estado: Estado }) {
  const { executar, ocupado } = useCentral();
  const { clima_atual: clima, ultimo_voo: voo, contadores: cont, estatisticas: est } = estado;
  const desatualizado =
    clima.cenario !== voo.cenario ||
    Math.abs(clima.chuva_72h - voo.chuva_72h) >= 10 ||
    Math.abs(clima.previsao_24h - voo.previsao_24h) >= 10;

  const executarRec = (r: Recomendacao) =>
    executar(() => (r.acao === "voo_drone" ? api.enviarDrone() : api.robo(r.acao as MissaoRobo, r.celulas)), r.titulo);

  return (
    <div className="tela tela--duas" data-testid="tela-inicio">
      {/* duas colunas no computador; no celular ficam uma embaixo da outra, na mesma ordem */}
      <div className="tela__coluna tela__coluna--principal">
        <Cartao titulo="Frota" teste="cartao-frota">
          <div className="frota">
            {estado.dispositivos.map((d) => (
              <CartaoDispositivo key={d.id} d={d} estado={estado} />
            ))}
          </div>
        </Cartao>

        <Cartao titulo="Ações" teste="cartao-acoes">
          <AcoesFrota estado={estado} />
        </Cartao>

        <Cartao titulo="Ações sugeridas" teste="cartao-sugestoes">
          {estado.recomendacoes.length === 0 ? (
            <p className="mudo">Nenhuma ação pendente no momento.</p>
          ) : (
            <ul className="lista" data-testid="lista-sugestoes">
              {estado.recomendacoes.map((r) => (
                <li key={r.id} className="sugestao" data-testid={`sugestao-${r.id}`} data-acao={r.acao} data-prioridade={r.prioridade}>
                  <div>
                    <Pilula cor={COR_PRIORIDADE[r.prioridade]}>{r.prioridade}</Pilula> <strong>{r.titulo}</strong>
                    <p className="mudo">{r.motivo}</p>
                  </div>
                  <button
                    type="button"
                    className="botao botao--primario"
                    data-testid={`btn-executar-${r.id}`}
                    id={`btn-executar-${r.id}`}
                    disabled={ocupado}
                    onClick={() => void executarRec(r)}
                  >
                    Executar
                  </button>
                </li>
              ))}
            </ul>
          )}
        </Cartao>
      </div>

      <div className="tela__coluna tela__coluna--lateral">
        <CartaoNotificacoes />

        <Cartao titulo="Clima e último voo" teste="cartao-clima">
          <div className="numeros">
            <Numero rotulo="Chuva 72 h (agora)" valor={`${inteiro(clima.chuva_72h)} mm`} detalhe={clima.nome} teste="chuva-atual" />
            <Numero rotulo="Previsão 24 h" valor={`${inteiro(clima.previsao_24h)} mm`} />
            <Numero rotulo="Último voo" valor={dataHora(voo.data)} detalhe={voo.voo_id} teste="ultimo-voo" />
            <Numero rotulo="Alto/crítico" valor={voo.celulas_alto_ou_critico} detalhe={`de ${est.celulas} células`} />
          </div>
          <p className="mudo pequeno" data-testid="fonte-clima" data-real={clima.real}>
            {clima.real
              ? `Fonte: ${clima.descricao}${clima.atualizado_em ? ` · atualizado às ${hora(clima.atualizado_em).slice(0, 5)}` : ""}`
              : "Chuva simulada (cenário de teste)."}
          </p>
          {clima.erro && (
            <p className="faixa faixa--aviso" data-testid="erro-chuva-real">
              Não consegui atualizar a chuva real agora; usando a última leitura válida.
            </p>
          )}
          {desatualizado && (
            <p className="faixa faixa--aviso" data-testid="mapa-desatualizado">
              A chuva mudou depois do último voo ({inteiro(voo.chuva_72h)} → {inteiro(clima.chuva_72h)} mm em 72 h). Envie o
              drone para atualizar o mapa.
            </p>
          )}
        </Cartao>

        <Cartao titulo="Trabalho do robô" teste="cartao-contadores">
          <div className="numeros">
            <Numero rotulo="Mudas plantadas" valor={inteiro(cont.mudas_plantadas)} />
            <Numero rotulo="Água aplicada" valor={`${inteiro(cont.litros_aplicados)} L`} />
            <Numero rotulo="Fissuras inspecionadas" valor={cont.fissuras_inspecionadas} />
            <Numero rotulo="Voos" valor={cont.voos} />
          </div>
        </Cartao>

        <Simulacao estado={estado} />
      </div>
    </div>
  );
}

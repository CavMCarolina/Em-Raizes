import { ClipboardList, House, LogOut, Map as IconeMapa, MessageCircle, Siren, type LucideIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { api, quandoSessaoExpirar, sessao } from "./api/cliente";
import type { Info } from "./api/tipos";
import { AvisoFlutuante } from "./componentes/ui";
import { NOME_APP } from "./config";
import { ProvedorCentral, useCentral } from "./contexto";
import { useRota, type Rota } from "./hooks/useRota";
import { sincronizarPush } from "./util/push";
import { Alertas } from "./telas/Alertas";
import { Guardiao } from "./telas/Guardiao";
import { Inicio } from "./telas/Inicio";
import { Login } from "./telas/Login";
import { Mapa } from "./telas/Mapa";
import { Operacoes } from "./telas/Operacoes";
import { COR_ALERTA } from "./util/formatos";

const ABAS: { id: Rota; Icone: LucideIcon; rotulo: string }[] = [
  { id: "inicio", Icone: House, rotulo: "Início" },
  { id: "mapa", Icone: IconeMapa, rotulo: "Mapa" },
  { id: "operacoes", Icone: ClipboardList, rotulo: "Operações" },
  { id: "alertas", Icone: Siren, rotulo: "Alertas" },
  { id: "guardiao", Icone: MessageCircle, rotulo: "Guardião" },
];

function Casca({ aoSair }: { aoSair: () => void }) {
  const { estado, erroEstado, info, aviso, fecharAviso } = useCentral();
  const [rota, irPara] = useRota();
  const al = estado?.alerta;
  const ativos = estado?.comandos_ativos.length ?? 0;

  return (
    <div className="app" data-rota={rota}>
      <header className="topo">
        <div className="topo__marca">
          <img src="/icone.svg" alt="" width={28} height={28} />
          <span>{info?.nome_app ?? NOME_APP}</span>
          <span className="selo">SIMULADO</span>
        </div>
        <button type="button" className="botao botao--fantasma" data-testid="btn-sair" onClick={aoSair}>
          <LogOut size={18} aria-hidden /> Sair
        </button>
      </header>
      {al && (
        <div
          className="faixa-alerta"
          style={{ background: COR_ALERTA[al.nivel] }}
          data-testid="faixa-alerta"
          data-nivel={al.nivel}
          role={al.nivel === "alerta_maximo" ? "alert" : "status"}
        >
          <strong>{al.titulo}</strong>
          <span>{al.mensagem}</span>
        </div>
      )}
      {erroEstado && (
        <p className="faixa faixa--erro" data-testid="erro-conexao">
          Sem resposta do servidor: {erroEstado.message}. Tentando de novo…
        </p>
      )}
      <main className="conteudo">
        {!estado ? (
          <p className="mudo">Conectando à central…</p>
        ) : rota === "inicio" ? (
          <Inicio estado={estado} />
        ) : rota === "mapa" ? (
          <Mapa estado={estado} />
        ) : rota === "operacoes" ? (
          <Operacoes />
        ) : rota === "alertas" ? (
          <Alertas estado={estado} />
        ) : (
          <Guardiao />
        )}
      </main>
      <AvisoFlutuante aviso={aviso} aoFechar={fecharAviso} />
      <nav className="abas" aria-label="Navegação principal">
        {ABAS.map((a) => (
          <button
            key={a.id}
            type="button"
            className={`aba${rota === a.id ? " aba--ativa" : ""}`}
            aria-current={rota === a.id ? "page" : undefined}
            data-testid={`aba-${a.id}`}
            onClick={() => irPara(a.id)}
          >
            <span aria-hidden className="aba__icone">
              <a.Icone size={22} strokeWidth={rota === a.id ? 2.4 : 1.8} />
              {a.id === "operacoes" && ativos > 0 && <span className="aba__contador">{ativos}</span>}
            </span>
            <span>{a.rotulo}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}

export function App() {
  const [info, setInfo] = useState<Info | null>(null);
  const [logado, setLogado] = useState(() => !!sessao.obter());

  useEffect(() => {
    api.info().then(setInfo).catch(() => undefined);
    quandoSessaoExpirar(() => setLogado(false));
  }, []);

  useEffect(() => {
    document.title = `${info?.nome_app ?? NOME_APP} · Administração`;
  }, [info?.nome_app]);

  useEffect(() => {
    // reenvia a inscrição de notificações (o servidor guarda em memória)
    if (logado) void sincronizarPush();
  }, [logado]);

  if (!logado) return <Login info={info} aoEntrar={() => setLogado(true)} />;
  return (
    <ProvedorCentral info={info}>
      <Casca
        aoSair={() => {
          sessao.limpar();
          setLogado(false);
        }}
      />
    </ProvedorCentral>
  );
}

import { Droplets, Drone, OctagonX, ScanSearch, ShieldCheck, Sprout, Undo2 } from "lucide-react";
import { useState } from "react";
import { api } from "../api/cliente";
import type { Estado, MissaoRobo } from "../api/tipos";
import { useCentral } from "../contexto";
import { BotaoAcao, Dialogo } from "./ui";

/** Por que cada botão está bloqueado (null = liberado). Mesmas regras do backend. */
export function bloqueios(estado: Estado) {
  const drone = estado.dispositivos.find((d) => d.tipo === "drone")!;
  const robo = estado.dispositivos.find((d) => d.tipo === "robo")!;
  const motivoDrone =
    drone.status === "parado"
      ? "Parada de emergência ativa"
      : drone.status === "em_missao"
        ? "Drone em voo"
        : drone.bateria < 30
          ? `Bateria baixa (${Math.round(drone.bateria)}%)`
          : null;
  const motivoRobo =
    robo.status === "parado"
      ? "Parada de emergência ativa"
      : !estado.robo_liberado
        ? `Robô recolhido: ${estado.alerta.titulo}`
        : robo.status === "em_missao"
          ? "Robô em missão"
          : robo.bateria < 20
            ? `Bateria baixa (${Math.round(robo.bateria)}%)`
            : null;
  return { drone, robo, motivoDrone, motivoRobo };
}

export function AcoesFrota({ estado }: { estado: Estado }) {
  const { executar, ocupado } = useCentral();
  const [confirmar, setConfirmar] = useState<null | "emergencia" | "recolher">(null);
  const { robo, motivoDrone, motivoRobo } = bloqueios(estado);
  const missao = (m: MissaoRobo) => () => void executar(() => api.robo(m));

  return (
    <div className="acoes" data-testid="acoes-frota">
      <BotaoAcao
        id="btn-enviar-drone"
        icone={<Drone />}
        rotulo="Enviar drone"
        dica="Mapear o morro agora"
        variante="primario"
        onClick={() => void executar(api.enviarDrone)}
        desabilitado={!!motivoDrone}
        motivo={motivoDrone ?? undefined}
        carregando={ocupado}
      />
      <BotaoAcao
        id="btn-robo-plantio"
        icone={<Sprout />}
        rotulo="Plantar capim"
        dica="Capim-vetiver nas áreas prioritárias"
        variante="sucesso"
        onClick={missao("plantio")}
        desabilitado={!!motivoRobo}
        motivo={motivoRobo ?? undefined}
        carregando={ocupado}
      />
      <BotaoAcao
        id="btn-robo-irrigacao"
        icone={<Droplets />}
        rotulo="Irrigar mudas"
        dica="Só onde o solo está seco e sem risco"
        onClick={missao("irrigacao")}
        desabilitado={!!motivoRobo}
        motivo={motivoRobo ?? undefined}
        carregando={ocupado}
      />
      <BotaoAcao
        id="btn-robo-inspecao"
        icone={<ScanSearch />}
        rotulo="Inspecionar fissuras"
        dica="Conferir o que a visão detectou"
        onClick={missao("inspecao")}
        desabilitado={!!motivoRobo}
        motivo={motivoRobo ?? undefined}
        carregando={ocupado}
      />
      <BotaoAcao
        id="btn-robo-recolher"
        icone={<Undo2 />}
        rotulo="Recolher robô"
        dica="Cancela a missão e volta à base"
        onClick={() => setConfirmar("recolher")}
        desabilitado={robo.status !== "em_missao"}
        motivo="O robô já está na base"
        carregando={ocupado}
      />
      {estado.frota_parada ? (
        <BotaoAcao
          id="btn-liberar-frota"
          icone={<ShieldCheck />}
          rotulo="Liberar frota"
          dica="Encerrar a parada de emergência"
          variante="primario"
          onClick={() => void executar(api.liberarFrota)}
          carregando={ocupado}
        />
      ) : (
        <BotaoAcao
          id="btn-emergencia"
          icone={<OctagonX />}
          rotulo="Parada de emergência"
          dica="Para drone e robô imediatamente"
          variante="perigo"
          onClick={() => setConfirmar("emergencia")}
          carregando={ocupado}
        />
      )}

      <Dialogo
        aberto={confirmar === "emergencia"}
        titulo="Acionar parada de emergência?"
        confirmar="Parar tudo"
        perigo
        teste="dialogo-emergencia"
        aoCancelar={() => setConfirmar(null)}
        aoConfirmar={() => {
          setConfirmar(null);
          void executar(api.emergencia);
        }}
      >
        <p>Todas as missões em andamento serão canceladas e o drone e o robô ficarão bloqueados até você liberar a frota.</p>
      </Dialogo>
      <Dialogo
        aberto={confirmar === "recolher"}
        titulo="Recolher o robô?"
        confirmar="Recolher"
        teste="dialogo-recolher"
        aoCancelar={() => setConfirmar(null)}
        aoConfirmar={() => {
          setConfirmar(null);
          void executar(api.recolherRobo);
        }}
      >
        <p>A missão atual ({robo.comando_atual}) será cancelada e o robô voltará para a base.</p>
      </Dialogo>
    </div>
  );
}

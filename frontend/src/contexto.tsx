import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { api, ErroApi } from "./api/cliente";
import type { Comando, Estado, Info, Mapa } from "./api/tipos";
import { INTERVALO_ESTADO_MS } from "./config";
import { usePolling } from "./hooks/usePolling";
import { ROTULO_TIPO } from "./util/formatos";

export type TipoAviso = "sucesso" | "recusado" | "erro" | "info";
export interface Aviso {
  id: number;
  tipo: TipoAviso;
  titulo: string;
  texto?: string;
  codigo?: string;
}

interface ContextoCentral {
  info: Info | null;
  estado: Estado | null;
  erroEstado: Error | null;
  mapa: Mapa | null;
  recarregarEstado: () => Promise<Estado | null>;
  executar: (acao: () => Promise<Comando>, rotulo?: string) => Promise<Comando | null>;
  ocupado: boolean;
  aviso: Aviso | null;
  avisar: (a: Omit<Aviso, "id">) => void;
  fecharAviso: () => void;
}

const Contexto = createContext<ContextoCentral | null>(null);

export function useCentral(): ContextoCentral {
  const c = useContext(Contexto);
  if (!c) throw new Error("useCentral fora do ProvedorCentral");
  return c;
}

export function ProvedorCentral({ info, children }: { info: Info | null; children: ReactNode }) {
  const { dados: estado, erro: erroEstado, recarregar } = usePolling(api.estado, INTERVALO_ESTADO_MS);
  const [mapa, setMapa] = useState<Mapa | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [aviso, setAviso] = useState<Aviso | null>(null);
  const seq = useRef(0);
  const vooId = estado?.ultimo_voo.voo_id;

  // O mapa só muda quando o drone termina um voo: recarrega quando o voo_id muda.
  useEffect(() => {
    if (!vooId) return;
    let vivo = true;
    api.mapa().then((m) => vivo && setMapa(m)).catch(() => undefined);
    return () => {
      vivo = false;
    };
  }, [vooId]);

  const fecharAviso = useCallback(() => setAviso(null), []);

  const avisar = useCallback((a: Omit<Aviso, "id">) => {
    seq.current += 1;
    setAviso({ ...a, id: seq.current });
  }, []);

  const executar = useCallback(
    async (acao: () => Promise<Comando>, rotulo?: string) => {
      setOcupado(true);
      try {
        const cmd = await acao();
        const nome = rotulo ?? ROTULO_TIPO[cmd.tipo];
        if (cmd.status === "recusado") {
          avisar({ tipo: "recusado", titulo: `${nome}: recusado`, texto: cmd.motivo ?? undefined, codigo: cmd.codigo_recusa ?? undefined });
        } else {
          const ign = Object.keys(cmd.ignoradas).length;
          avisar({
            tipo: "sucesso",
            titulo: `${nome}: ${cmd.status === "em_execucao" ? "enviado" : "feito"} (${cmd.id})`,
            texto: ign ? `${ign} célula(s) ficaram de fora — veja em Operações.` : undefined,
          });
        }
        void recarregar();
        return cmd;
      } catch (e) {
        const erro = e as ErroApi;
        avisar({ tipo: "erro", titulo: "Não foi possível enviar o comando", texto: erro.message, codigo: erro.codigo });
        return null;
      } finally {
        setOcupado(false);
      }
    },
    [avisar, recarregar],
  );

  return (
    <Contexto.Provider
      value={{
        info,
        estado,
        erroEstado,
        mapa,
        recarregarEstado: recarregar,
        executar,
        ocupado,
        aviso,
        avisar,
        fecharAviso,
      }}
    >
      {children}
    </Contexto.Provider>
  );
}

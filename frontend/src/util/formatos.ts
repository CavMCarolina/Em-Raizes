import type { ClasseRisco, Comando, Dispositivo, NivelAlerta, StatusComando, TipoComando } from "../api/tipos";

export const COR_CLASSE: Record<ClasseRisco, string> = {
  baixo: "#2e7d32",
  moderado: "#fbc02d",
  alto: "#ef6c00",
  critico: "#c62828",
};

export const NOME_CLASSE: Record<ClasseRisco, string> = {
  baixo: "Baixo",
  moderado: "Moderado",
  alto: "Alto",
  critico: "Crítico",
};

export const COR_ALERTA: Record<NivelAlerta, string> = {
  normal: "#2e7d32",
  atencao: "#f57f17",
  alerta: "#e65100",
  alerta_maximo: "#c62828",
};

export const ROTULO_TIPO: Record<TipoComando, string> = {
  voo_drone: "Voo do drone",
  plantio: "Plantio de capim",
  irrigacao: "Irrigação",
  inspecao: "Inspeção de fissuras",
  recolher_robo: "Recolher robô",
  parada_emergencia: "Parada de emergência",
  liberar_frota: "Liberar frota",
  mudar_clima: "Troca de clima",
};

export const ROTULO_STATUS: Record<StatusComando, string> = {
  em_execucao: "Em execução",
  concluido: "Concluído",
  recusado: "Recusado",
  cancelado: "Cancelado",
};

export const ROTULO_DISPOSITIVO: Record<Dispositivo["status"], string> = {
  na_base: "Na base",
  em_missao: "Em missão",
  parado: "Parado (emergência)",
};

const numeroBR = new Intl.NumberFormat("pt-BR");

export function numero(valor: number, casas = 0): string {
  return new Intl.NumberFormat("pt-BR", { maximumFractionDigits: casas, minimumFractionDigits: casas }).format(valor);
}

export function inteiro(valor: number): string {
  return numeroBR.format(Math.round(valor));
}

export function porcentagem(fracao: number): string {
  return `${Math.round(fracao * 100)}%`;
}

export function hora(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleTimeString("pt-BR", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

export function dataHora(iso: string | null | undefined): string {
  if (!iso) return "—";
  const d = new Date(iso);
  return Number.isNaN(d.getTime())
    ? "—"
    : d.toLocaleString("pt-BR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

/** Uma linha que resume o que o comando fez (ou por que não fez). */
export function resumoComando(c: Comando): string {
  if (c.status === "recusado" || c.status === "cancelado") return c.motivo ?? ROTULO_STATUS[c.status];
  const partes: string[] = [];
  if (c.celulas.length) partes.push(`${c.celulas.length} ${c.celulas.length === 1 ? "célula" : "células"}`);
  const mudas = (c.resultado.mudas_plantadas ?? c.parametros.mudas) as number | undefined;
  if (mudas) partes.push(`${inteiro(mudas)} mudas`);
  const litros = (c.resultado.litros_aplicados ?? c.parametros.litros) as number | undefined;
  if (litros) partes.push(`${inteiro(litros)} L`);
  if (typeof c.resultado.voo_id === "string") partes.push(c.resultado.voo_id);
  const confirmadas = c.resultado.confirmadas as string[] | undefined;
  if (confirmadas) partes.push(`${confirmadas.length} fissuras confirmadas`);
  const ignoradas = Object.keys(c.ignoradas).length;
  if (ignoradas) partes.push(`${ignoradas} ignoradas`);
  return partes.join(" · ") || ROTULO_STATUS[c.status];
}

export function corBateria(bateria: number): string {
  if (bateria < 30) return "#c62828";
  if (bateria < 60) return "#f9a825";
  return "#2e7d32";
}

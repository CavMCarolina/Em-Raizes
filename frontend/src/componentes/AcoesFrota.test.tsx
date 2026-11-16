import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import type { Estado } from "../api/tipos";
import { ProvedorCentral } from "../contexto";
import { AcoesFrota, bloqueios } from "./AcoesFrota";

function estado(parcial: Partial<Estado> = {}, robo: Partial<Estado["dispositivos"][number]> = {}): Estado {
  return {
    horario: "",
    dispositivos: [
      { id: "DRN-01", tipo: "drone", nome: "Drone", status: "na_base", bateria: 100, comando_atual: null, posicao: null },
      { id: "ROB-01", tipo: "robo", nome: "Robô", status: "na_base", bateria: 100, comando_atual: null, posicao: null, ...robo },
    ],
    comandos_ativos: [],
    ultimos_comandos: [],
    alerta: { nivel: "normal", titulo: "Normal", cor: "", mensagem: "", acao: "", casas_em_risco: 0, pessoas_em_risco: 0, celulas_evacuar: [] },
    robo_liberado: true,
    frota_parada: false,
    recomendacoes: [],
    ultimo_evento_id: 0,
    ...parcial,
  } as Estado;
}

afterEach(cleanup);

describe("bloqueios", () => {
  it("libera tudo com frota na base e sem alerta", () => {
    const b = bloqueios(estado());
    expect(b.motivoDrone).toBeNull();
    expect(b.motivoRobo).toBeNull();
  });
  it("bloqueia o robô em alerta, mas não o drone", () => {
    const b = bloqueios(estado({ robo_liberado: false, alerta: { ...estado().alerta, nivel: "alerta", titulo: "Alerta" } }));
    expect(b.motivoRobo).toContain("Alerta");
    expect(b.motivoDrone).toBeNull();
  });
  it("bloqueia por bateria baixa", () => {
    expect(bloqueios(estado({}, { bateria: 10 })).motivoRobo).toContain("Bateria baixa");
  });
});

describe("AcoesFrota", () => {
  it("expõe seletores estáveis (data-testid)", () => {
    render(
      <ProvedorCentral info={null}>
        <AcoesFrota estado={estado()} />
      </ProvedorCentral>,
    );
    for (const id of ["btn-enviar-drone", "btn-robo-plantio", "btn-robo-irrigacao", "btn-robo-inspecao", "btn-robo-recolher", "btn-emergencia"]) {
      expect(screen.getByTestId(id)).toBeTruthy();
    }
    expect((screen.getByTestId("btn-robo-recolher") as HTMLButtonElement).disabled).toBe(true);
  });
  it("troca emergência por liberar frota quando parada", () => {
    render(
      <ProvedorCentral info={null}>
        <AcoesFrota estado={estado({ frota_parada: true })} />
      </ProvedorCentral>,
    );
    expect(screen.queryByTestId("btn-emergencia")).toBeNull();
    expect(screen.getByTestId("btn-liberar-frota")).toBeTruthy();
  });
});

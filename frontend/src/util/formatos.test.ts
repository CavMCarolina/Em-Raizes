import { describe, expect, it } from "vitest";
import type { Comando } from "../api/tipos";
import { corBateria, inteiro, resumoComando } from "./formatos";

const base: Comando = {
  id: "CMD-0001",
  tipo: "plantio",
  dispositivo: "ROB-01",
  origem: "admin",
  status: "em_execucao",
  progresso: 10,
  celulas: ["L01C01", "L01C02"],
  ignoradas: { L05C05: "área com casas" },
  parametros: { mudas: 1200 },
  resultado: {},
  codigo_recusa: null,
  motivo: null,
  criado_em: "2026-11-10T09:00:00-03:00",
  iniciado_em: "2026-11-10T09:00:00-03:00",
  concluido_em: null,
  duracao_s: 8,
  chave_idempotencia: null,
};

describe("resumoComando", () => {
  it("resume células, mudas e ignoradas", () => {
    expect(resumoComando(base)).toBe("2 células · 1.200 mudas · 1 ignoradas");
  });
  it("mostra o motivo quando recusado", () => {
    expect(resumoComando({ ...base, status: "recusado", motivo: "Robô recolhido por segurança" })).toBe(
      "Robô recolhido por segurança",
    );
  });
  it("mostra o voo gerado", () => {
    expect(resumoComando({ ...base, tipo: "voo_drone", celulas: [], ignoradas: {}, parametros: {}, resultado: { voo_id: "VOO-0002" } })).toBe(
      "VOO-0002",
    );
  });
});

describe("formatos", () => {
  it("formata inteiros no padrão brasileiro", () => {
    expect(inteiro(29188)).toBe("29.188");
  });
  it("cor da bateria muda nos limites", () => {
    expect(corBateria(20)).toBe("#c62828");
    expect(corBateria(50)).toBe("#f9a825");
    expect(corBateria(90)).toBe("#2e7d32");
  });
});

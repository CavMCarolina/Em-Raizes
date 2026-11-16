import { describe, expect, it } from "vitest";
import { dimensoesReduzidas } from "./imagem";
import { chaveParaBytes } from "./push";

describe("chaveParaBytes", () => {
  it("decodifica base64url sem padding (formato da chave VAPID)", () => {
    // "AQID_-8" = bytes 1, 2, 3, 255, 239
    expect(Array.from(chaveParaBytes("AQID_-8"))).toEqual([1, 2, 3, 255, 239]);
  });
});

describe("dimensoesReduzidas", () => {
  it("reduz o lado maior para 1280 mantendo a proporção", () => {
    expect(dimensoesReduzidas(4000, 3000)).toEqual([1280, 960]);
    expect(dimensoesReduzidas(1080, 1920)).toEqual([720, 1280]);
  });
  it("não aumenta fotos pequenas", () => {
    expect(dimensoesReduzidas(800, 600)).toEqual([800, 600]);
  });
});

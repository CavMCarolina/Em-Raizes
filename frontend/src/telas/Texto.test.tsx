import { cleanup, render } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { semEmojis, Texto } from "./Mapa";

afterEach(cleanup);

it("renderiza negrito e itálico sem mostrar os asteriscos", () => {
  const { container } = render(<Texto texto={"*(modo offline)*\n**Risco: alto** e 5 * 3"} />);
  expect(container.querySelector("em")?.textContent).toBe("(modo offline)");
  expect(container.querySelector("strong")?.textContent).toBe("Risco: alto");
  expect(container.textContent).not.toContain("**");
  expect(container.textContent).toContain("5 * 3");
});

it("remove emojis vindos da IA (a interface usa ícones próprios)", () => {
  expect(semEmojis("🚨 Saia agora ⚠️ e ligue 199 👍🏽")).toBe("Saia agora e ligue 199 ");
  expect(semEmojis("Umidade 13% → 20%")).toBe("Umidade 13% → 20%");
});

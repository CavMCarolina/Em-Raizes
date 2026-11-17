import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it } from "vitest";
import { Seletor } from "./Seletor";

const OPCOES = [
  { valor: "real", nome: "Chuva real", detalhe: "atual" },
  { valor: "seco", nome: "Tempo seco" },
  { valor: "extrema", nome: "Tempestade extrema" },
];

function Exemplo() {
  const [valor, setValor] = useState("real");
  return (
    <>
      <Seletor id="sel" rotulo="Clima" opcoes={OPCOES} valor={valor} aoMudar={setValor} />
      <p data-testid="fora">escolhido: {valor}</p>
    </>
  );
}

const botao = () => screen.getByTestId("sel");
const lista = () => screen.queryByRole("listbox");

afterEach(cleanup);

describe("Seletor (dropdown do app)", () => {
  it("abre a lista ao clicar e troca o valor ao escolher uma opção", () => {
    render(<Exemplo />);
    expect(botao().textContent).toContain("Chuva real");
    expect(lista()).toBeNull();

    fireEvent.click(botao());
    expect(lista()).not.toBeNull();
    expect(screen.getAllByRole("option")).toHaveLength(3);
    expect(screen.getByTestId("sel-opcao-real").getAttribute("aria-selected")).toBe("true");

    fireEvent.click(screen.getByTestId("sel-opcao-seco"));
    expect(lista()).toBeNull();
    expect(botao().textContent).toContain("Tempo seco");
    expect(screen.getByTestId("fora").textContent).toBe("escolhido: seco");
  });

  it("funciona pelo teclado: seta abre e anda, Enter escolhe, Esc fecha", () => {
    render(<Exemplo />);
    fireEvent.keyDown(botao(), { key: "ArrowDown" });
    expect(lista()).not.toBeNull();
    fireEvent.keyDown(botao(), { key: "ArrowDown" });
    fireEvent.keyDown(botao(), { key: "ArrowDown" });
    fireEvent.keyDown(botao(), { key: "Enter" });
    expect(lista()).toBeNull();
    expect(botao().getAttribute("data-valor")).toBe("extrema");

    fireEvent.keyDown(botao(), { key: "Enter" });
    expect(lista()).not.toBeNull();
    fireEvent.keyDown(botao(), { key: "Escape" });
    expect(lista()).toBeNull();
    expect(botao().getAttribute("data-valor")).toBe("extrema");
  });

  it("fecha ao tocar fora, sem trocar o valor", () => {
    render(<Exemplo />);
    fireEvent.click(botao());
    expect(lista()).not.toBeNull();
    fireEvent.pointerDown(screen.getByTestId("fora"));
    expect(lista()).toBeNull();
    expect(botao().getAttribute("data-valor")).toBe("real");
  });

  it("continua aberto quando a tela é redesenhada (o app atualiza a cada 2 s)", () => {
    const { rerender } = render(<Exemplo />);
    fireEvent.click(botao());
    rerender(<Exemplo />);
    expect(lista()).not.toBeNull();
  });
});

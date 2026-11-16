import { useEffect, useState } from "react";

export const ROTAS = ["inicio", "mapa", "operacoes", "alertas", "guardiao"] as const;
export type Rota = (typeof ROTAS)[number];

function lerRota(): Rota {
  const atual = window.location.hash.replace(/^#\/?/, "").split("?")[0] as Rota;
  return ROTAS.includes(atual) ? atual : "inicio";
}

/** Navegação por hash (#/mapa): funciona em qualquer hospedagem estática e permite links diretos. */
export function useRota(): [Rota, (r: Rota) => void] {
  const [rota, setRota] = useState<Rota>(lerRota);
  useEffect(() => {
    const ouvir = () => setRota(lerRota());
    window.addEventListener("hashchange", ouvir);
    return () => window.removeEventListener("hashchange", ouvir);
  }, []);
  return [rota, (r: Rota) => (window.location.hash = `/${r}`)];
}

import { useCallback, useEffect, useRef, useState } from "react";

/** Carrega dados e recarrega a cada `intervalo` ms enquanto a aba estiver visível. */
export function usePolling<T>(carregar: () => Promise<T>, intervalo: number, ativo = true) {
  const [dados, setDados] = useState<T | null>(null);
  const [erro, setErro] = useState<Error | null>(null);
  const ref = useRef(carregar);
  ref.current = carregar;

  const recarregar = useCallback(async () => {
    try {
      const novo = await ref.current();
      setDados(novo);
      setErro(null);
      return novo;
    } catch (e) {
      setErro(e as Error);
      return null;
    }
  }, []);

  useEffect(() => {
    if (!ativo) return;
    void recarregar();
    if (!intervalo) return;
    const id = window.setInterval(() => {
      if (document.visibilityState === "visible") void recarregar();
    }, intervalo);
    return () => window.clearInterval(id);
  }, [recarregar, intervalo, ativo]);

  return { dados, erro, recarregar };
}

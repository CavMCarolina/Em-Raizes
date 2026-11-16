// Reduz a foto no próprio aparelho antes de enviar: upload mais rápido no 4G e IA mais barata.

export const LADO_MAXIMO = 1280;

export function dimensoesReduzidas(largura: number, altura: number, maximo = LADO_MAXIMO): [number, number] {
  const escala = Math.min(1, maximo / Math.max(largura, altura));
  return [Math.round(largura * escala), Math.round(altura * escala)];
}

/** Lê a foto, reduz para no máximo 1280 px e devolve como data URL JPEG. */
export async function prepararFoto(arquivo: File): Promise<string> {
  if (!arquivo.type.startsWith("image/")) throw new Error("Escolha um arquivo de imagem.");
  const url = URL.createObjectURL(arquivo);
  try {
    const img = new Image();
    img.src = url;
    await img.decode();
    const [l, a] = dimensoesReduzidas(img.naturalWidth, img.naturalHeight);
    const canvas = document.createElement("canvas");
    canvas.width = l;
    canvas.height = a;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("Não foi possível processar a foto neste aparelho.");
    ctx.drawImage(img, 0, 0, l, a);
    return canvas.toDataURL("image/jpeg", 0.82);
  } finally {
    URL.revokeObjectURL(url);
  }
}

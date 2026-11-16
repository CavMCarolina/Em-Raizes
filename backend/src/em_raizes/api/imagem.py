"""Codificador PNG mínimo (evita depender de Pillow só para a foto aérea simulada)."""

from __future__ import annotations

import struct
import zlib

import numpy as np


def png_rgb(imagem: np.ndarray) -> bytes:
    if imagem.ndim != 3 or imagem.shape[2] != 3:
        raise ValueError("Esperada imagem RGB (altura x largura x 3).")
    img = np.ascontiguousarray(imagem, dtype=np.uint8)
    altura, largura, _ = img.shape
    bruto = b"".join(b"\x00" + img[y].tobytes() for y in range(altura))

    def bloco(tipo: bytes, dados: bytes) -> bytes:
        return struct.pack(">I", len(dados)) + tipo + dados + struct.pack(">I", zlib.crc32(tipo + dados) & 0xFFFFFFFF)

    cabecalho = struct.pack(">IIBBBBB", largura, altura, 8, 2, 0, 0, 0)
    return (
        b"\x89PNG\r\n\x1a\n" + bloco(b"IHDR", cabecalho) + bloco(b"IDAT", zlib.compress(bruto, 6)) + bloco(b"IEND", b"")
    )

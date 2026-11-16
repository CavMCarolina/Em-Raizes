"""Triagem visual de risco por foto, com IA multimodal (o mesmo modelo do Guardião).

O administrador manda uma foto de encosta, trinca ou muro; o modelo devolve um
JSON com os sinais visíveis, o risco e recomendações. A resposta é validada com
Pydantic; se vier inválida, o modelo recebe o erro e tenta mais uma vez.
Sem IA online não há análise (não inventamos resultado).
"""

from __future__ import annotations

import base64
import binascii
import re
from typing import Literal

from pydantic import BaseModel, Field, ValidationError

from . import prompts
from .guardiao import extrair_json
from .llm import ClienteLLM, ErroLLM

TIPOS_ACEITOS = {"image/jpeg", "image/png", "image/webp"}
TAMANHO_MAX_BYTES = 4 * 1024 * 1024


class SinalFoto(BaseModel):
    tipo: Literal[
        "trinca_no_solo",
        "trinca_em_parede",
        "erosao",
        "solo_exposto",
        "agua_ou_vazamento",
        "muro_ou_poste_inclinado",
        "arvore_inclinada",
        "degrau_no_terreno",
        "entulho_ou_lixo",
        "outro",
    ]
    descricao: str = Field(min_length=3, max_length=220)
    gravidade: Literal["baixa", "media", "alta"]


class AnaliseFoto(BaseModel):
    e_encosta: bool
    risco: Literal["baixo", "moderado", "alto", "critico", "indeterminado"]
    confianca: Literal["baixa", "media", "alta"]
    resumo: str = Field(min_length=3, max_length=320)
    sinais: list[SinalFoto] = Field(default_factory=list, max_length=8)
    recomendacoes: list[str] = Field(min_length=1, max_length=5)


class ErroFoto(Exception):
    def __init__(self, codigo: str, mensagem: str):
        super().__init__(mensagem)
        self.codigo = codigo
        self.mensagem = mensagem


def decodificar_imagem(imagem: str, tipo: str | None = None) -> tuple[bytes, str]:
    """Aceita data URL (data:image/jpeg;base64,...) ou base64 puro + tipo."""
    m = re.match(r"^data:(image/[a-z+.-]+);base64,(.*)$", imagem.strip(), re.DOTALL)
    if m:
        tipo, conteudo = m.group(1), m.group(2)
    else:
        conteudo = imagem
    tipo = (tipo or "").lower()
    if tipo not in TIPOS_ACEITOS:
        raise ErroFoto("tipo_invalido", "Envie uma foto JPG, PNG ou WEBP.")
    try:
        dados = base64.b64decode(conteudo, validate=True)
    except (binascii.Error, ValueError):
        raise ErroFoto("imagem_invalida", "Não consegui ler a imagem enviada.") from None
    if len(dados) > TAMANHO_MAX_BYTES:
        raise ErroFoto("imagem_grande", "A foto passa de 4 MB. Tire outra ou reduza a qualidade.")
    assinaturas = {"image/jpeg": b"\xff\xd8\xff", "image/png": b"\x89PNG", "image/webp": b"RIFF"}
    if not dados.startswith(assinaturas[tipo]):
        raise ErroFoto("imagem_invalida", "O arquivo não parece ser uma foto do tipo informado.")
    return dados, tipo


def _reforcar_seguranca(analise: AnaliseFoto) -> AnaliseFoto:
    """Camada determinística: risco alto/crítico sempre começa por acionar a Defesa Civil."""
    if analise.risco in ("alto", "critico") and not any("199" in r for r in analise.recomendacoes):
        analise.recomendacoes = ["Acione a Defesa Civil (199) para uma vistoria no local.", *analise.recomendacoes][:5]
    return analise


def analisar_foto(
    cliente: ClienteLLM, dados: bytes, tipo: str, observacao: str = "", celula: str | None = None
) -> tuple[AnaliseFoto, dict]:
    if not cliente.configurado:
        raise ErroFoto(
            "ia_offline", "A análise de foto precisa da IA online: configure OPENROUTER_API_KEY no servidor."
        )
    contexto = "Foto enviada pelo administrador do app."
    if celula:
        contexto += f" Local informado: célula {celula}."
    if observacao:
        contexto += f" Observação de quem tirou a foto: {observacao[:300]}"
    url = f"data:{tipo};base64,{base64.b64encode(dados).decode()}"
    mensagens: list[dict] = [
        {"role": "system", "content": prompts.SYSTEM_FOTO},
        {
            "role": "user",
            "content": [{"type": "text", "text": contexto}, {"type": "image_url", "image_url": {"url": url}}],
        },
    ]
    for _ in range(2):
        try:
            r = cliente.completar(mensagens, temperatura=0.1, max_tokens=800, json=True)
        except ErroLLM as e:
            raise ErroFoto(e.codigo, e.mensagem) from None
        try:
            analise = _reforcar_seguranca(AnaliseFoto.model_validate(extrair_json(r.texto)))
            meta = {"modelo": r.modelo, "tokens": r.tokens_entrada + r.tokens_saida, "latencia_s": r.latencia_s}
            return analise, meta
        except (ValueError, ValidationError) as err:
            mensagens += [
                {"role": "assistant", "content": r.texto},
                {"role": "user", "content": f"JSON inválido: {str(err)[:400]}. Responda só o JSON corrigido."},
            ]
    raise ErroFoto("resposta_invalida", "A IA não devolveu uma análise válida. Tente de novo ou use outra foto.")

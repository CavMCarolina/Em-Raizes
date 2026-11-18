"""Correção do achado do Semgrep (dynamic-urllib-use-detected) em fontes/chuva.py."""

import pytest

from em_raizes.fontes.chuva import URL_CEMADEN, URL_OPEN_METEO, _baixar_json


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "http://api.open-meteo.com/v1/forecast",  # sem TLS
        "https://exemplo-malicioso.com/x.json",
        "https://api.open-meteo.com.atacante.com/v1",  # domínio parecido
    ],
)
def test_baixar_json_recusa_url_fora_da_lista(url):
    with pytest.raises(ValueError, match="fora da lista permitida"):
        _baixar_json(url, timeout=1)


def test_urls_oficiais_estao_na_lista_permitida():
    from em_raizes.fontes.chuva import ORIGENS_PERMITIDAS

    assert URL_CEMADEN.format(uf="RJ").startswith(ORIGENS_PERMITIDAS)
    assert URL_OPEN_METEO.format(lat=0, lon=0).startswith(ORIGENS_PERMITIDAS)

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest
from playwright.sync_api import TimeoutError as PWTimeout

from src.sri import submission as sub
from src.sri.signature import BOTON_ACEPTAR
from src.utils.exceptions import ComprobanteInvalido, ConfigError, EnvioIncierto, PortalChanged
from tests.test_verificacion import HOY, LINEAS, PERIODO, RUC, _pdf_minimo


class _Loc:
    def __init__(self, page, sel):
        self.page, self.sel = page, sel

    @property
    def first(self):
        return self

    def filter(self, **_):
        return self

    def wait_for(self, **_):
        self.page.eventos.append(("espera", self.sel))
        if self.sel in self.page.sin_aparecer:
            raise PWTimeout("no aparece")

    def is_enabled(self):
        return self.sel not in self.page.deshabilitados

    def click(self):
        self.page.eventos.append(("clic", self.sel))
        if self.sel == BOTON_ACEPTAR and self.page.falla_en_aceptar:
            raise self.page.falla_en_aceptar


class _Descarga:
    def __init__(self, datos, falla):
        self.datos, self.falla = datos, falla

    def save_as(self, ruta):
        if self.falla:
            raise self.falla
        Path(ruta).write_bytes(self.datos)


class _Pagina:
    def __init__(self, pdf=None, sin_aparecer=(), deshabilitados=(), sin_descarga=False, falla_save=None,
                 falla_en_aceptar=None):
        self.eventos = []
        self.pdf = pdf if pdf is not None else _pdf_minimo(LINEAS)
        self.sin_aparecer, self.deshabilitados = set(sin_aparecer), set(deshabilitados)
        self.sin_descarga, self.falla_save, self.falla_en_aceptar = sin_descarga, falla_save, falla_en_aceptar

    def locator(self, sel):
        return _Loc(self, sel)

    @contextmanager
    def expect_download(self, timeout=None):
        caja = SimpleNamespace(value=None)
        yield caja
        if self.sin_descarga:
            raise PWTimeout("sin descarga")
        caja.value = _Descarga(self.pdf, self.falla_save)

    def clics(self, sel):
        return [e for e in self.eventos if e == ("clic", sel)]


def _enviar(pagina, tmp_path, ruc=RUC):
    return sub.enviar_declaracion(pagina, ruc, PERIODO, tmp_path / "ev", envio_autorizado=True, hoy=HOY,
                                  ahora=datetime(2026, 11, 6, 14, 30, 5))


@pytest.mark.parametrize("valor", [False, None, "si", 1])
def test_sin_autorizacion_estricta_ni_se_toca_la_pagina(tmp_path, valor):
    with pytest.raises(ConfigError, match="no autorizado"):
        sub.enviar_declaracion(None, RUC, PERIODO, tmp_path, envio_autorizado=valor)


def test_flujo_completo_un_solo_clic_y_comprobante_archivado(tmp_path):
    p = _Pagina()
    ruta = _enviar(p, tmp_path)
    assert ruta.name == f"111111111111_{RUC}_20261106143005.pdf" and ruta.exists()
    assert len(p.clics(BOTON_ACEPTAR)) == 1 and len(p.clics(sub.BOTON_IMPRIMIR)) == 1
    orden = [e for e in p.eventos if e[1] in (BOTON_ACEPTAR, sub.MENSAJE_EXITO, sub.BOTON_IMPRIMIR)]
    assert orden == [("espera", BOTON_ACEPTAR), ("clic", BOTON_ACEPTAR), ("espera", sub.MENSAJE_EXITO),
                     ("clic", sub.BOTON_IMPRIMIR)]


def test_aceptar_ausente_o_deshabilitado_no_se_pulsa(tmp_path):
    p = _Pagina(sin_aparecer={BOTON_ACEPTAR})
    with pytest.raises(PortalChanged):
        _enviar(p, tmp_path)
    assert p.clics(BOTON_ACEPTAR) == []
    p = _Pagina(deshabilitados={BOTON_ACEPTAR})
    with pytest.raises(PortalChanged):
        _enviar(p, tmp_path)
    assert p.clics(BOTON_ACEPTAR) == []


def test_sin_mensaje_de_exito_no_se_reintenta_y_no_se_descarga(tmp_path):
    p = _Pagina(sin_aparecer={sub.MENSAJE_EXITO})
    with pytest.raises(EnvioIncierto, match="pudo haberse enviado"):
        _enviar(p, tmp_path)
    assert len(p.clics(BOTON_ACEPTAR)) == 1 and p.clics(sub.BOTON_IMPRIMIR) == []


def test_si_no_se_puede_descargar_el_comprobante_queda_para_revision(tmp_path):
    p = _Pagina(sin_descarga=True)
    with pytest.raises(ComprobanteInvalido, match="no se pudo descargar"):
        _enviar(p, tmp_path)
    assert len(p.clics(BOTON_ACEPTAR)) == 1


def test_comprobante_de_otro_ruc_se_aparta_y_no_se_archiva_como_valido(tmp_path):
    p = _Pagina()
    with pytest.raises(ComprobanteInvalido, match="RUC"):
        _enviar(p, tmp_path, ruc="1790000000002")
    nombres = [f.name for f in (tmp_path / "ev").iterdir()]
    assert len(nombres) == 1 and nombres[0].startswith("RECHAZADO_")


def test_cualquier_fallo_tras_el_clic_nunca_es_un_error_comun(tmp_path):
    # un error comun se reintentaria en la siguiente corrida, y la declaracion pudo haberse enviado
    p = _Pagina(falla_save=RuntimeError("disco lleno"))
    with pytest.raises(EnvioIncierto, match="RuntimeError"):
        _enviar(p, tmp_path)
    p = _Pagina(falla_en_aceptar=RuntimeError("se cerro el navegador"))
    with pytest.raises(EnvioIncierto, match="RuntimeError"):
        _enviar(p, tmp_path)
    assert len(p.clics(BOTON_ACEPTAR)) == 1
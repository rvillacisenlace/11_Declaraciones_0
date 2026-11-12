from datetime import date, datetime

import pytest

from src.sri import verification as v
from src.utils.exceptions import ComprobanteInvalido

RUC = "1790000000001"
HOY = date(2026, 11, 5)
PERIODO = (2026, 10)
LINEAS = [
    "Comprobante", "Electrónico para pago", "www.sri.gob.ec", "Número de serie: 111111111111",
    "Razón social:", "FIDEICOMISO DE PRUEBA", "Identificación: Fecha y hora de declaración:",
    f"{RUC} 05/11/2026 a las 11:23:49", "Detalle de las obligaciones pagadas", "Período fiscal: OCTUBRE 2026",
    "Impuesto: 2011  DECLARACION DE IVA", "Tipo de declaración: ORIGINAL", "Declaración sin valor a pagar.",
]


def _pdf_minimo(lineas):
    """PDF de una pagina con texto, sin librerias externas (WinAnsi para tildes)."""
    esc = lambda t: t.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    cuerpo = ("BT /F1 12 Tf 14 TL 50 750 Td\n" + "\n".join(f"({esc(l)}) Tj T*" for l in lineas) + "\nET").encode("cp1252")
    objs = [b"<< /Type /Catalog /Pages 2 0 R >>", b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R /Resources << /Font << /F1 5 0 R >> >> >>",
            b"<< /Length %d >>\nstream\n" % len(cuerpo) + cuerpo + b"\nendstream",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"]
    out, offs = bytearray(b"%PDF-1.4\n"), []
    for i, o in enumerate(objs, 1):
        offs.append(len(out))
        out += f"{i} 0 obj\n".encode() + o + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    for off in offs:
        out += f"{off:010d} 00000 n \n".encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)


def _pdf(tmp_path, lineas=LINEAS, nombre="descarga.pdf"):
    ruta = tmp_path / nombre
    ruta.write_bytes(_pdf_minimo(lineas))
    return ruta


def _con(**cambios):
    return [l for l in LINEAS if not any(l.startswith(k) for k in cambios)] + list(cambios.values())


def test_lee_todos_los_campos(tmp_path):
    c = v.leer_pdf(_pdf(tmp_path))
    assert (c.serie, c.ruc, c.periodo, c.tipo) == ("111111111111", RUC, "OCTUBRE 2026", "ORIGINAL")
    assert c.impuesto.startswith("2011") and c.sin_valor_a_pagar
    assert c.fecha_declaracion == datetime(2026, 11, 5, 11, 23, 49)


def test_lo_correcto_pasa(tmp_path):
    v.verificar(v.leer_pdf(_pdf(tmp_path)), RUC, PERIODO, HOY)


@pytest.mark.parametrize("ruc,periodo,hoy,esperado", [
    ("1790000000002", PERIODO, HOY, "RUC"),
    (RUC, (2026, 9), HOY, "periodo"),
    (RUC, PERIODO, date(2026, 11, 6), "antiguo"),
])
def test_rechaza_lo_que_no_coincide(tmp_path, ruc, periodo, hoy, esperado):
    with pytest.raises(ComprobanteInvalido, match=esperado):
        v.verificar(v.leer_pdf(_pdf(tmp_path)), ruc, periodo, hoy)


def test_rechaza_una_sustitutiva(tmp_path):
    c = v.leer_pdf(_pdf(tmp_path, _con(**{"Tipo de declaración": "Tipo de declaración: SUSTITUTIVA"})))
    with pytest.raises(ComprobanteInvalido, match="SUSTITUTIVA"):
        v.verificar(c, RUC, PERIODO, HOY)


def test_rechaza_si_hay_valor_a_pagar(tmp_path):
    lineas = [l for l in LINEAS if "sin valor" not in l] + ["Valor a pagar: 12.50"]
    with pytest.raises(ComprobanteInvalido, match="no fue en cero"):
        v.verificar(v.leer_pdf(_pdf(tmp_path, lineas)), RUC, PERIODO, HOY)


def test_rechaza_otro_impuesto(tmp_path):
    c = v.leer_pdf(_pdf(tmp_path, _con(Impuesto="Impuesto: 1011 RENTA")))
    with pytest.raises(ComprobanteInvalido, match="2011"):
        v.verificar(c, RUC, PERIODO, HOY)


def test_el_mensaje_nunca_incluye_el_ruc(tmp_path):
    with pytest.raises(ComprobanteInvalido) as e:
        v.verificar(v.leer_pdf(_pdf(tmp_path)), "1790000000002", PERIODO, HOY)
    assert RUC not in str(e.value) and "1790000000002" not in str(e.value)


def test_un_html_guardado_como_pdf_no_es_un_comprobante(tmp_path):
    ruta = tmp_path / "x.pdf"
    ruta.write_bytes(b"<html><body>Acceso denegado</body></html>")
    with pytest.raises(ComprobanteInvalido, match="no es un PDF"):
        v.leer_pdf(ruta)


def test_pdf_sin_texto_o_danado(tmp_path):
    with pytest.raises(ComprobanteInvalido):
        v.leer_pdf(_pdf(tmp_path, [""]))
    ruta = tmp_path / "roto.pdf"
    ruta.write_bytes(b"%PDF-1.4\nbasura sin estructura")
    with pytest.raises(ComprobanteInvalido):
        v.leer_pdf(ruta)


def test_falta_un_campo(tmp_path):
    lineas = [l for l in LINEAS if not l.startswith("Período")]
    with pytest.raises(ComprobanteInvalido, match="periodo fiscal"):
        v.leer_pdf(_pdf(tmp_path, lineas))


def test_nombre_definitivo_con_tres_partes():
    c = v.parsear("\n".join(LINEAS))
    assert v.nombre_archivo(c, datetime(2026, 11, 6, 14, 30, 5)) == f"111111111111_{RUC}_20261106143005.pdf"


def test_archivar_verifica_renombra_y_mueve(tmp_path):
    origen = _pdf(tmp_path)
    final = v.archivar(origen, tmp_path / "evidencia", RUC, PERIODO, ahora=datetime(2026, 11, 6, 14, 30, 5), hoy=HOY)
    assert final.name == f"111111111111_{RUC}_20261106143005.pdf" and final.exists() and not origen.exists()


def test_archivar_no_mueve_nada_si_no_pasa_la_verificacion(tmp_path):
    origen = _pdf(tmp_path)
    with pytest.raises(ComprobanteInvalido):
        v.archivar(origen, tmp_path / "evidencia", "1790000000002", PERIODO, hoy=HOY)
    assert origen.exists() and not (tmp_path / "evidencia").exists()


def test_el_mensaje_de_archivado_no_incluye_el_ruc(tmp_path, caplog):
    import logging
    pdf = tmp_path / "d.pdf"
    pdf.write_bytes(_pdf_minimo(LINEAS))
    with caplog.at_level(logging.INFO):
        v.archivar(pdf, tmp_path / "ev", RUC, PERIODO, ahora=datetime(2026, 11, 6, 14, 30, 5), hoy=HOY)
    assert "Comprobante archivado" in caplog.text and RUC not in caplog.text


def test_periodo_de_convierte_el_nombre_del_mes_en_numero():
    meses = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE",
             "NOVIEMBRE", "DICIEMBRE"]
    for n, nombre in enumerate(meses, start=1):
        c = v.parsear("\n".join(l.replace("OCTUBRE 2026", f"{nombre} 2027") for l in LINEAS))
        assert v.periodo_de(c) == (2027, n)


def test_periodo_de_rechaza_un_mes_desconocido():
    c = v.parsear("\n".join(l.replace("OCTUBRE 2026", "OCTUBREX 2026") for l in LINEAS))
    with pytest.raises(ComprobanteInvalido, match="periodo"):
        v.periodo_de(c)

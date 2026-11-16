import io

import pytest
from msoffcrypto.format.ooxml import OOXMLFile
from openpyxl import Workbook

from src.microsoft.excel_repository import ArchivoGraph, ControlGraph
from src.security import credential_repository as repo
from src.security.workbook_decryption import abrir_en_memoria
from src.services import control_writer
from src.services.fideicomiso_service import leer_control, leer_directorio
from src.utils.exceptions import ConfigError, GraphError
from tests.graph_falsos import ClienteControlFalso

ENC = ["ID", "NOMBRE", "RUC", "DECLARA_0", "RETENCION_0", "RESPONSABLE"]
FILAS = [ENC,
         ["A1", "uno", "1790000000001", "SI", "NO", "Ana"],
         ["A2", "dos", "1790000000002", "NO", "SI", "Luis"],
         ["A3", "tres", "1790000000003", "SI", "SI", "Ana"]]


def _control(filas=FILAS, **kw):
    cliente = ClienteControlFalso(filas, **kw)
    return ControlGraph(cliente, "drive1", "item1"), cliente


# ---- lectura ----

def test_leer_filas_desde_a1():
    c, _ = _control()
    assert c.leer_filas() == [tuple(f) for f in FILAS]


def test_leer_filas_conserva_la_posicion_real_si_el_rango_no_empieza_en_a1():
    c, _ = _control(origen="B3")
    filas = c.leer_filas()
    assert filas[:2] == [(), ()] and filas[2] == (None,) + tuple(ENC)


def test_encabezado_fuera_de_la_fila_1_se_rechaza_igual_que_en_local():
    c, _ = _control(origen="B3")
    with pytest.raises(ConfigError, match="Faltan columnas"):
        leer_control(c, "declara_0")


def test_rango_ilegible():
    class Raro:
        def get_json(self, ruta, *, contexto):
            return {"address": "???", "values": [[1]]}
    with pytest.raises(GraphError, match="rango"):
        ControlGraph(Raro(), "d", "i").leer_filas()


def test_leer_control_por_graph_da_lo_mismo_que_en_local():
    c, _ = _control()
    r = leer_control(c, "declara_0")
    assert [p.id for p in r.pendientes] == ["A1", "A3"] and r.omitidos == 1 and r.total == 3
    assert [p.fila for p in r.pendientes] == [2, 4]
    assert [p.id for p in leer_control(c, "retencion_0").pendientes] == ["A2", "A3"]


def test_filas_correctas_aunque_el_rango_empiece_en_la_columna_b():
    c, _ = _control(origen="B1")
    assert [p.fila for p in leer_control(c, "declara_0").pendientes] == [2, 4]


def test_directorio_por_graph():
    c, _ = _control()
    d = leer_directorio(c)
    assert d.por_id["A2"] == ("1790000000002", "Luis") and d.por_ruc["1790000000001"] == "Ana"


def test_hoja_sin_filas():
    c, _ = _control(filas=[])
    with pytest.raises(ConfigError):
        c.marcar_declarado(2, "A1", "declara_0", None)


# ---- escritura ----

def test_marca_una_sola_celda_con_respaldo(tmp_path):
    c, cl = _control()
    assert c.marcar_declarado(2, "A1", "declara_0", tmp_path) is True
    escrituras = cl.escrituras()
    assert len(escrituras) == 1
    assert escrituras[0][1].endswith("/workbook/worksheets/Fideicomisos/range(address='D2')")
    assert escrituras[0][2] == {"values": [["DECLARADO"]]}
    assert cl.filas[1][3] == "DECLARADO" and cl.filas[1][4] == "NO" and cl.filas[3][3] == "SI"
    respaldos = list(tmp_path.glob("Control_Graph.respaldo_*.xlsx"))
    assert len(respaldos) == 1 and respaldos[0].read_bytes() == b"libro-original"


def test_el_respaldo_va_antes_de_escribir(tmp_path):
    c, cl = _control()
    c.marcar_declarado(2, "A1", "declara_0", tmp_path)
    nombres = [x[0] for x in cl.llamadas]
    assert nombres.index("DESCARGA") < nombres.index("PATCH")


def test_columna_de_retenciones(tmp_path):
    c, cl = _control()
    assert c.marcar_declarado(3, "A2", "retencion_0", tmp_path) is True
    assert cl.escrituras()[0][1].endswith("range(address='E3')")


def test_con_rango_desplazado_la_celda_es_la_real(tmp_path):
    c, cl = _control(origen="B1")
    assert c.marcar_declarado(2, "A1", "declara_0", tmp_path) is True
    assert cl.escrituras()[0][1].endswith("range(address='E2')")  # el rango empieza en B: DECLARA_0 queda en la columna E
    assert cl.filas[1][3] == "DECLARADO"


def test_un_solo_respaldo_por_ejecucion(tmp_path):
    c, cl = _control()
    c.marcar_declarado(2, "A1", "declara_0", tmp_path)
    c.marcar_declarado(4, "A3", "declara_0", tmp_path)
    assert len(cl.descargas()) == 1 and len(cl.escrituras()) == 2


def test_si_la_fila_ya_es_otro_id_no_se_toca(tmp_path):
    c, cl = _control()
    assert c.marcar_declarado(2, "OTRO", "declara_0", tmp_path) is False
    assert not cl.escrituras() and not cl.descargas() and not list(tmp_path.iterdir())


def test_si_la_celda_ya_no_dice_si_no_se_pisa(tmp_path):
    c, cl = _control()
    assert c.marcar_declarado(3, "A2", "declara_0", tmp_path) is False  # A2 tiene NO en declara_0
    assert not cl.escrituras() and not cl.descargas()


def test_celda_ya_declarada_es_exito_sin_escribir(tmp_path):
    filas = [ENC, ["A1", "uno", "1790000000001", "DECLARADO", "NO", "Ana"]]
    c, cl = _control(filas)
    assert c.marcar_declarado(2, "A1", "declara_0", tmp_path) is True
    assert not cl.escrituras() and not cl.descargas()


@pytest.mark.parametrize("fila", [1, 0, 99])
def test_fila_fuera_de_rango_o_encabezado(tmp_path, fila):
    c, cl = _control()
    assert c.marcar_declarado(fila, "A1", "declara_0", tmp_path) is False
    assert not cl.escrituras()


def test_marca_desconocida(tmp_path):
    c, _ = _control()
    with pytest.raises(ConfigError, match="Marca desconocida"):
        c.marcar_declarado(2, "A1", "otra", tmp_path)


def test_faltan_columnas(tmp_path):
    c, _ = _control([["ID", "NOMBRE"], ["A1", "x"]])
    with pytest.raises(ConfigError, match="Faltan columnas"):
        c.marcar_declarado(2, "A1", "declara_0", tmp_path)


def test_si_graph_no_confirma_la_anotacion_se_avisa(tmp_path):
    c, _ = _control(ignorar_escritura=True)
    with pytest.raises(ConfigError, match="no confirmo"):
        c.marcar_declarado(2, "A1", "declara_0", tmp_path)


def test_control_writer_delega_en_graph(tmp_path):
    c, cl = _control()
    assert control_writer.marcar_declarado(c, 2, "A1", "declara_0", tmp_path) is True
    assert cl.filas[1][3] == "DECLARADO"


# ---- credenciales: bytes en memoria, descifrado local ----

def _bytes_cifrados(password="maestra"):
    wb = Workbook()
    ws = wb.active
    ws.title = "Accesos"
    ws.append(["ID fideicomiso", "Usuario SRI", "Contraseña SRI", "Correo"])
    ws.append([7, "1790000000001", "clave-uno", None])
    plano = io.BytesIO()
    wb.save(plano)
    plano.seek(0)
    salida = io.BytesIO()
    OOXMLFile(plano).encrypt(password, salida)
    return salida.getvalue()


class _ArchivoFalso:
    def __init__(self, datos):
        self.datos = datos

    def leer_bytes(self):
        return self.datos


def test_archivo_graph_descarga_el_contenido():
    cl = ClienteControlFalso([], contenido=b"zzz")
    assert ArchivoGraph(cl, "d1", "i1").leer_bytes() == b"zzz"
    assert cl.llamadas == [("DESCARGA", "/drives/d1/items/i1/content")]


def test_descifra_en_memoria_desde_graph():
    libro = abrir_en_memoria(_ArchivoFalso(_bytes_cifrados()), "maestra")
    assert b"PK" == libro.getvalue()[:2]


def test_clave_incorrecta_desde_graph():
    with pytest.raises(ConfigError):
        abrir_en_memoria(_ArchivoFalso(_bytes_cifrados()), "otra")


def test_archivo_sin_cifrar_desde_graph_se_rechaza():
    wb = Workbook()
    plano = io.BytesIO()
    wb.save(plano)
    with pytest.raises(ConfigError, match="NO esta cifrado"):
        abrir_en_memoria(_ArchivoFalso(plano.getvalue()), "maestra")


def test_bytes_que_no_son_un_libro():
    with pytest.raises(ConfigError):
        abrir_en_memoria(_ArchivoFalso(b"esto no es excel"), "maestra")


def test_el_repositorio_de_credenciales_usa_graph_si_esta_configurado(monkeypatch):
    from src.microsoft import fuentes
    monkeypatch.setattr(fuentes, "credenciales_graph", lambda: _ArchivoFalso(_bytes_cifrados()))
    c = repo.cargar_contribuyente("7", "1790000000001", "maestra")
    assert c.clave == "clave-uno" and "clave-uno" not in repr(c)

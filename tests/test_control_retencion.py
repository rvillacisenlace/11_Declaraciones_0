from openpyxl import Workbook

from src.services.fideicomiso_service import leer_control


def _libro(tmp_path, filas):
    wb = Workbook()
    ws = wb.active
    ws.title = "Fideicomisos"
    ws.append(["ID", "NOMBRE", "RUC", "DECLARA_0", "RETENCION_0", "RESPONSABLE"])  # RETENCION_0 en E, RESPONSABLE en F
    for f in filas:
        ws.append(f)
    ruta = tmp_path / "control.xlsx"
    wb.save(ruta)
    return ruta


def test_la_columna_nueva_no_rompe_la_lectura_y_el_responsable_sigue_siendo_el_correcto(tmp_path):
    r = leer_control(_libro(tmp_path, [["1", "Uno", "1790000000001", "SI", "NO", "Ana"]]))
    assert r.pendientes[0].responsable == "Ana"


def test_por_ahora_retencion_0_no_dispara_nada(tmp_path):
    # RETENCION_0 = SI con DECLARA_0 = NO: hoy no se procesa nada (el flujo de retenciones aun no existe)
    r = leer_control(_libro(tmp_path, [["1", "Uno", "1790000000001", "NO", "SI", "Ana"]]))
    assert r.pendientes == [] and r.omitidos == 1
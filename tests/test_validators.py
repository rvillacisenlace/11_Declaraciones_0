from datetime import date

from src.utils.validators import enmascarar_digitos, enmascarar_ruc, nombre_mes, periodo_a_declarar, url_corta


def test_periodo_mes_normal():
    assert periodo_a_declarar(date(2026, 11, 5)) == (2026, 10)


def test_periodo_enero_apunta_a_diciembre_anterior():
    assert periodo_a_declarar(date(2027, 1, 3)) == (2026, 12)


def test_nombre_mes():
    assert nombre_mes(1) == "Enero" and nombre_mes(12) == "Diciembre"


def test_mascara_ruc():
    assert enmascarar_ruc("1790012345001") == "1790***001"
    assert enmascarar_ruc("123") == "***"


def test_url_corta_quita_sesion_y_query():
    assert url_corta("https://x.ec/a/b;jsessionid=ABC?x=1#f") == "https://x.ec/a/b"


def test_enmascarar_digitos():
    assert enmascarar_digitos("ruc 1790012345001 ok") == "ruc *** ok"

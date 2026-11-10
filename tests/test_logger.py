from src.utils.logger import redactar


def test_redacta_clave_y_token():
    assert "secreto" not in redactar("password=secreto")
    assert "A" * 90 not in redactar("t " + "A" * 90)


def test_redacta_query_y_jsessionid():
    assert redactar("ir a https://x.ec/p;jsessionid=ZZZ?a=1 fin").startswith("ir a https://x.ec/p")
    assert "jsessionid" not in redactar("https://x.ec/p;jsessionid=ZZZ?a=1")


def test_redacta_un_ruc_dentro_de_un_nombre_de_archivo():
    t = redactar("Comprobante archivado: 873125312753_1792082404001_20261110152543.pdf")
    assert "1792082404001" not in t and "1792***001" in t
    assert "873125312753" in t and "20261110152543" in t  # la serie y la fecha-hora se conservan


def test_no_toca_numeros_que_no_son_un_ruc():
    for texto in ("serie 873125312753", "fecha 20261110152543", "id 12345", "ya enmascarado 1792***001"):
        assert redactar(texto) == texto
from src.utils.logger import redactar

def test_redacta_clave_y_token():
    assert "secreto" not in redactar("password=secreto")
    assert "A" * 90 not in redactar("t " + "A" * 90)

def test_redacta_query_y_jsessionid():
    assert redactar("ir a https://x.ec/p;jsessionid=ZZZ?a=1 fin").startswith("ir a https://x.ec/p")
    assert "jsessionid" not in redactar("https://x.ec/p;jsessionid=ZZZ?a=1")

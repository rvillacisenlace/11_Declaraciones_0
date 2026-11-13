import os
import tempfile

import pytest

os.environ.setdefault("ZERO_HOME", tempfile.mkdtemp(prefix="zero_test_"))


@pytest.fixture(autouse=True)
def _sin_graph(monkeypatch):
    """Ninguna prueba debe llegar a Microsoft Graph aunque el entorno de quien las corre tenga GRAPH_* o MICROSOFT_*."""
    for nombre in list(os.environ):
        if nombre.startswith(("GRAPH_", "MICROSOFT_")):
            monkeypatch.delenv(nombre, raising=False)
    from src.microsoft import fuentes
    fuentes.reiniciar()

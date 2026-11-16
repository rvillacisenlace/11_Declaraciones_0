import subprocess
import sys
import textwrap

import pytest

import main as zero_main
from src.utils.candado import candado_de_ejecucion
from src.utils.exceptions import EjecucionEnCurso


def test_toma_y_suelta(tmp_path):
    ruta = tmp_path / "zero.lock"
    with candado_de_ejecucion(ruta):
        pass
    with candado_de_ejecucion(ruta):  # si no se hubiera soltado, esta segunda vez fallaria
        pass


def test_crea_la_carpeta_si_no_existe(tmp_path):
    ruta = tmp_path / "nueva" / "zero.lock"
    with candado_de_ejecucion(ruta):
        assert ruta.exists()


def test_una_segunda_toma_mientras_esta_tomado_falla(tmp_path):
    ruta = tmp_path / "zero.lock"
    with candado_de_ejecucion(ruta):
        with pytest.raises(EjecucionEnCurso, match="otra ejecucion"):
            with candado_de_ejecucion(ruta):
                pytest.fail("no debio entrar")


def test_la_segunda_toma_fallida_no_suelta_la_primera(tmp_path):
    ruta = tmp_path / "zero.lock"
    with candado_de_ejecucion(ruta):
        with pytest.raises(EjecucionEnCurso):
            with candado_de_ejecucion(ruta):
                pass
        with pytest.raises(EjecucionEnCurso):  # sigue ocupado
            with candado_de_ejecucion(ruta):
                pass


def test_se_suelta_aunque_haya_un_error(tmp_path):
    ruta = tmp_path / "zero.lock"
    with pytest.raises(RuntimeError):
        with candado_de_ejecucion(ruta):
            raise RuntimeError("fallo")
    with candado_de_ejecucion(ruta):
        pass


def test_otro_proceso_real_lo_respeta(tmp_path):
    """Verificacion de verdad entre procesos (en Windows prueba msvcrt, en Linux fcntl)."""
    ruta = tmp_path / "zero.lock"
    codigo = textwrap.dedent("""
        import sys
        from pathlib import Path
        from src.utils.candado import candado_de_ejecucion
        with candado_de_ejecucion(Path(sys.argv[1])):
            print("listo", flush=True)
            sys.stdin.readline()
    """)
    hijo = subprocess.Popen([sys.executable, "-c", codigo, str(ruta)], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    try:
        assert hijo.stdout.readline().strip() == "listo"
        with pytest.raises(EjecucionEnCurso):
            with candado_de_ejecucion(ruta):
                pass
        hijo.stdin.write("\n")
        hijo.stdin.flush()
        hijo.wait(timeout=20)
        with candado_de_ejecucion(ruta):  # al terminar el otro proceso queda libre
            pass
    finally:
        if hijo.poll() is None:
            hijo.kill()


# ---- integracion con main ----

def test_main_no_hace_nada_si_ya_hay_otra_ejecucion(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(zero_main.settings, "HOME", tmp_path)

    def no_debe_correr(*a, **k):
        raise AssertionError("se ejecuto el flujo con otra ejecucion en curso")
    monkeypatch.setattr(zero_main, "_main", no_debe_correr)
    with candado_de_ejecucion(tmp_path / "zero.lock"):
        assert zero_main.main(["--simular"]) == 1
    assert "otra ejecucion" in capsys.readouterr().out


def test_main_libera_el_candado_al_terminar(tmp_path, monkeypatch):
    monkeypatch.setattr(zero_main.settings, "HOME", tmp_path)
    monkeypatch.setattr(zero_main, "_main", lambda argv=None: 0)
    assert zero_main.main([]) == 0
    assert zero_main.main([]) == 0  # la segunda vez tambien: se solto la primera


def test_main_libera_el_candado_si_el_flujo_revienta(tmp_path, monkeypatch):
    monkeypatch.setattr(zero_main.settings, "HOME", tmp_path)

    def revienta(argv=None):
        raise RuntimeError("x")
    monkeypatch.setattr(zero_main, "_main", revienta)
    with pytest.raises(RuntimeError):
        zero_main.main([])
    with candado_de_ejecucion(tmp_path / "zero.lock"):
        pass

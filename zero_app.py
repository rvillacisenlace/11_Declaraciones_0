"""Punto de entrada del .exe (PyInstaller). Que el error SE VEA: si algo falla, incluso al importar, la ventana no se
cierra sola; y al terminar espera ENTER para poder leer el resultado. En desarrollo se sigue usando: py -m main"""
import sys


def ejecutar() -> int:
    try:
        from main import main
        return main()
    except SystemExit as e:  # argparse y similares
        return e.code if isinstance(e.code, int) else (0 if e.code is None else 1)
    except Exception:
        import traceback
        print("\n" + "=" * 70)
        print("ERROR INESPERADO - Zero se detuvo")
        print("=" * 70 + "\n")
        traceback.print_exc()
        print("\n" + "=" * 70)
        return 2


def principal() -> int:
    codigo = ejecutar()
    if getattr(sys, "frozen", False):  # solo en el .exe: en desarrollo no se pide nada
        try:
            input("\nPresione ENTER para cerrar...")
        except EOFError:
            pass
    return codigo


if __name__ == "__main__":
    sys.exit(principal())

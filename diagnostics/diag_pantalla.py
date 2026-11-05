"""Diagnostico: describe la pantalla actual SIN pulsar nada. Solo ids, clases y textos cortos.
Uso:  py -m diagnostics.diag_pantalla
Revise la salida antes de pegarla: oculta cadenas de 10+ digitos y valores de campos."""
import re

from src.sri import navigation
from src.sri.browser import open_context
from src.utils.logger import configurar_logging
from src.utils.validators import enmascarar_digitos, url_corta

JS_RESUMEN = """() => {
  const t = (e) => (e.innerText || e.value || '').trim().slice(0, 60);
  const fila = (e) => ({tag: e.tagName.toLowerCase(), id: e.id || null,
      cls: (e.className && e.className.toString ? e.className.toString() : '').slice(0, 80),
      texto: t(e), deshabilitado: !!e.disabled || /disabled/.test(e.className || '')});
  const q = (s) => Array.from(document.querySelectorAll(s)).map(fila);
  return {
    titulo: document.title,
    encabezados: q('h1,h2,h3,h4'),
    botones: q('button, a[role=button], input[type=submit], input[type=button], a.ui-button'),
    radios_checks: q('input[type=radio], input[type=checkbox]'),
    desplegables: q('.ui-selectonemenu'),
    campos: Array.from(document.querySelectorAll('input[type=text], input[type=password], textarea'))
        .map(e => ({id: e.id || null, type: e.type, readonly: e.readOnly})),
    mensajes: q('.ui-messages, .ui-message, .ui-growl-message'),
    month_picker: !!document.querySelector('table.month-picker-month-table'),
  };
}"""

JS_HTML = """(sel) => { const e = document.querySelector(sel); return e ? e.outerHTML.slice(0, 4000) : null; }"""


def _limpio(texto: str) -> str:
    texto = re.sub(r'value="[^"]*"', 'value="***"', texto)
    return enmascarar_digitos(texto)


def main() -> None:
    configurar_logging()
    with open_context() as ctx:
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        navigation.abrir_login(page)
        input("Inicie sesion manualmente y presione ENTER... ")
        while True:
            input("\nVaya MANUALMENTE a la pantalla que quiere inspeccionar y presione ENTER... ")
            print("URL:", url_corta(page.url))
            for clave, valor in page.evaluate(JS_RESUMEN).items():
                print(f"\n[{clave}]")
                items = valor if isinstance(valor, list) else [valor]
                for it in items:
                    print("  ", _limpio(str(it)))
            sel = input("\nSelector CSS para ver su HTML (ENTER = omitir, q = salir): ").strip()
            if sel.lower() == "q":
                break
            if sel:
                html = page.evaluate(JS_HTML, sel)
                print(_limpio(html) if html else "No encontrado")


if __name__ == "__main__":
    main()

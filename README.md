# Zero

Automatiza la presentación de declaraciones **en cero** ante el SRI (Ecuador) para fideicomisos:

- **IVA** (formulario 2011)
- **Retenciones en la fuente** (formulario 1031)

Está hecho en Python con Playwright. Controla un Microsoft Edge real, sin captcha, y trabaja de a un fideicomiso a la vez.

> **Aviso:** una declaración enviada no se deshace. Por eso el programa nunca envía por defecto y tiene varios candados (ver [Seguridad](#seguridad)). Pruebe siempre en seco antes de enviar.

## Qué hace

1. Lee del **Control** (Excel) qué fideicomisos declarar y su responsable, y del archivo cifrado de **Credenciales** las cuentas del SRI y la del contador.
2. Por cada fideicomiso: inicia sesión con su cuenta, abre el formulario, elige la obligación y el periodo (el **mes anterior** al actual), responde que no requiere informar valores, completa los datos del contador, envía, descarga el comprobante PDF, lo **verifica** y lo archiva.
3. Guarda el estado en una base SQLite (un registro por fideicomiso, periodo e impuesto), anota `DECLARADO` en el Control y guarda capturas de pantalla.
4. Si el SRI avisa que ya existe una declaración de ese periodo, **rechaza el aviso** (nunca pulsa "Aceptar", que invalidaría la anterior), lo registra como `ya_declarado` y sigue con el siguiente.

## Seguridad

- `DRY_RUN=true` por defecto: no se envía nada.
- `--enviar` exige `--lote`, `--max N`, `--hasta contador`, `DRY_RUN=false` y **dos confirmaciones escritas** (`SI` y luego `ENVIAR`).
- El único clic en "Aceptar" (el que envía) está en `src/sri/submission.py`; una prueba automática lo vigila.
- Antes de enviar se revisa que **interés y multa sean cero**; si no, no se envía y el fideicomiso pasa a revisión manual.
- El comprobante descargado se verifica (RUC, periodo, impuesto, tipo ORIGINAL, "sin valor a pagar" y fecha de hoy). Si no coincide, no se archiva como válido.
- Un solo intento de inicio de sesión por fideicomiso; ante la duda, el programa se detiene en vez de adivinar.
- Los estados finales (`declarado`, `ya_declarado`, `obligacion_no_disponible`) no se reintentan: la base impide declarar dos veces lo mismo.
- Si algo falla **después** de pulsar "Aceptar", el resultado es `EnvioIncierto`: el lote se detiene y hay que verificar en el SRI antes de reintentar.
- Las claves nunca se guardan: la contraseña del archivo de credenciales se pide por teclado y el archivo se descifra solo en memoria. Los logs enmascaran RUC y claves.

## Requisitos

- Windows y Microsoft Edge instalado.
- Python 3.10 o superior (probado con 3.14).
- Dependencias de `requirements.txt` (Playwright, openpyxl, pypdf, msoffcrypto-tool, python-dotenv, tzdata). Para desarrollo, además `pytest` y `pyflakes`.

## Instalación

```powershell
git clone <url-del-repositorio>
cd zero
py -m pip install -r requirements.txt
py -m pip install pytest pyflakes   # solo para desarrollo
```

Copie `.env.example` a `%APPDATA%\Zero\.env` y complete los valores. Si define `ZERO_HOME`, esa carpeta reemplaza a `%APPDATA%\Zero`.

| Variable | Obligatoria | Descripción |
|---|---|---|
| `SRI_LOGIN_URL` | Sí | URL de entrada al portal del SRI (ver `.env.example`) |
| `CONTROL_XLSX` | Sí | Ruta del Control. Use `/` y sin comillas |
| `CREDENCIALES_XLSX` | Con `--credenciales excel` (por defecto) | Ruta del archivo cifrado de credenciales |
| `DRY_RUN` | No (`true`) | `false` solo mientras dura un envío real |
| `ZERO_DOCS` | No | Carpeta raíz de `Declaraciones` y `Evidencias`. Sin ella, quedan dentro de la carpeta de trabajo |
| `PAUSA_ENTRE_S` | No (`30`) | Segundos entre fideicomisos (se le suma una variación al azar) |
| `DEFAULT_TIMEOUT_MS` | No (`30000`) | Espera máxima por elemento de la página |
| `LOG_RETENTION_DAYS` | No (`30`) | Días de historial de logs |
| `ZERO_HOME` | No | Carpeta de trabajo (por defecto `%APPDATA%\Zero`) |

Las variables `MICROSOFT_*`, `EXCEL_PATH` y `EXCEL_SECRET_TARGET` están reservadas para la integración con Microsoft Graph, que todavía no existe.

## Archivos de datos

Viven **fuera del repositorio** (el `.gitignore` excluye `.xlsx`, `.env`, logs y bases de datos).

### Control

Libro de Excel con una hoja `Fideicomisos` y estos encabezados:

| Columna | Contenido |
|---|---|
| `ID` | Identificador único del fideicomiso |
| `NOMBRE` | Nombre |
| `RUC` | 13 dígitos, único |
| `DECLARA_0` | Marca para IVA |
| `RETENCION_0` | Marca para retenciones |
| `RESPONSABLE` | Quién lo lleva; da nombre a una carpeta |

Valores de las marcas:

- `SI`: se procesa.
- `NO` o vacío: se omite.
- `DECLARADO`: ya hecho; se omite.
- Cualquier otro valor: la fila se excluye con un aviso.

El programa escribe `DECLARADO` solo, en la celda del impuesto procesado, después de un envío real o de un "ya declarado". **Hay que reiniciar esas marcas (a `NO` o `SI`) al empezar cada mes**; si no, esos fideicomisos se omiten sin avisar.

### Credenciales

Libro de Excel **cifrado con contraseña**:

- Hoja `Accesos`: `ID fideicomiso`, `Usuario SRI` (es el RUC del fideicomiso), `Contraseña SRI`, `Correo`.
- Hoja `Contador`: `Usuario SRI` y `Contraseña SRI`, **una sola fila**: el contador firma todas las declaraciones.

El cruce con el Control es por RUC.

## Uso

Siempre en este orden: **prueba en seco** y después **envío real**.

```powershell
# En seco: recorre todo el lote hasta los datos del contador, sin enviar
py -m main --lote --hasta contador

# Lo mismo para retenciones
py -m main --lote --impuesto 1031 --hasta contador

# Un solo fideicomiso, por ID del Control
py -m main --contribuyente 123 --hasta contador

# Envío real (con DRY_RUN=false en el .env): de uno en uno al principio
py -m main --lote --hasta contador --enviar --max 1
py -m main --lote --hasta contador --enviar --max 50
```

El programa pide por teclado la contraseña del archivo de credenciales y la confirmación `SI`. Con `--enviar` pide además `ENVIAR`.

| Opción | Descripción |
|---|---|
| `--lote` | Procesa todos los fideicomisos marcados con `SI` |
| `--contribuyente ID` | Procesa uno solo (ID del Control) |
| `--impuesto {2011,1031}` | `2011` = IVA (por defecto); `1031` = retenciones |
| `--hasta` | Hasta dónde llegar: `periodo` (por defecto), `siguiente`, `valores`, `firma`, `contador` |
| `--enviar` | **Envía de verdad.** Exige `--lote`, `--max N`, `--hasta contador` y `DRY_RUN=false` |
| `--max N` | Máximo de fideicomisos en esta ejecución |
| `--pausa S` | Segundos entre fideicomisos |
| `--incluir-revision` | Reintenta también los de `revision_manual`. **Solo en seco, nunca con `--enviar`** |
| `--credenciales {excel,consola}` | `excel` (por defecto): archivo cifrado. `consola`: por teclado (solo desarrollo) |
| `--login {auto,manual}` | `auto` (por defecto): con las credenciales. `manual`: solo desarrollo |

`--hasta` vale `periodo` por defecto, así que sin `--hasta contador` la corrida se detiene al elegir el periodo.

**Durante una corrida:** cierre el Control en Excel (si está abierto no se puede anotar `DECLARADO`), no abra ni mueva ventanas encima de Edge y mantenga el equipo despierto. Cada declaración tarda cerca de un minuto.

Códigos de salida: `0` correcto, `1` error controlado (configuración, datos, portal), `2` error inesperado, `3` lote detenido por un problema general.

## Dónde queda todo

```text
<ZERO_DOCS>/
├── Declaraciones/<Responsable>/<RUC>/<MM-AAAA>/<código - impuesto>/<serie>_<ruc>_<fecha>.pdf
└── Evidencias/<Responsable>/<RUC>/<AAAA-MM>_<impuesto>_<paso>_<fecha>_<hora>.png

%APPDATA%\Zero\
├── .env
├── .auth/                      perfil de Edge
├── logs/zero.log               rotación diaria, 30 días
└── data/
    ├── execution_history.db    estado de cada declaración
    └── respaldos/              copia del Control antes de la primera anotación de cada ejecución
```

Las capturas son cuatro por declaración, justo antes de cada clic: `01_periodo`, `02_preguntas`, `03_resumen` y `04_confirmacion`. Además, `ya_declarado` y `error` cuando corresponde.

Un valor vacío en `RESPONSABLE` usa la carpeta `SIN RESPONSABLE`. Los nombres se ajustan a caracteres válidos en Windows.

## Estados

| Estado | Significado | Qué hacer |
|---|---|---|
| `declarado` | Enviado y comprobante verificado | Nada |
| `ya_declarado` | El SRI indicó que ya existía; se rechazó el aviso | Nada |
| `obligacion_no_disponible` | El fideicomiso no tiene esa obligación | Revisar si corresponde |
| `simulado` | Prueba completa hasta los datos del contador; no se envió | Nada, se puede enviar |
| `parcial` | Se detuvo a propósito antes (`--hasta`); no se envió | Nada |
| `error` | Falló antes de enviar; no es final | Ver la captura de error y repetir: la cola lo reintenta primero |
| `revision_manual` | Algo ambiguo o un recargo | **Verificar en el SRI** antes de reintentar |
| `en_proceso` | Se está procesando o se interrumpió | Si queda así tras una interrupción, pasa solo a `revision_manual` |

Es seguro volver a lanzar un lote interrumpido.

## Receta mensual

1. En el Control, ponga `SI` en `DECLARA_0` y/o `RETENCION_0` de los que toca declarar, y reinicie los `DECLARADO` del mes anterior.
2. Verifique las claves en `Accesos` y la del contador.
3. **En seco**, con `DRY_RUN=true`: `--lote --hasta contador` para IVA y luego con `--impuesto 1031`. Resuelva cualquier `error` antes de enviar.
4. Pase a `DRY_RUN=false` y envíe, de uno en uno al principio (`--enviar --max 1`) y después el resto. IVA y retenciones por separado.
5. Tras cada envío compruebe: el PDF en su carpeta, `declarado` en el log, `DECLARADO` en la celda del Control y la captura `04_confirmacion`.
6. Vuelva a `DRY_RUN=true`.

## Diagnósticos

Herramientas en `diagnostics/`. Ninguna envía declaraciones.

| Herramienta | Para qué sirve |
|---|---|
| `py -m diagnostics.diag_control` | Resume el Control sin mostrar nombres ni RUC |
| `py -m diagnostics.diag_credenciales` | Describe la estructura del archivo de credenciales sin mostrar valores |
| `py -m diagnostics.diag_cruce` | Cruza Control y Credenciales por RUC y muestra solo conteos |
| `py -m diagnostics.diag_pantalla` | Describe la pantalla abierta del portal sin pulsar nada (para mapear pantallas nuevas) |
| `py -m diagnostics.mover_comprobantes` | Reubica comprobantes y capturas al árbol actual. Simula por defecto; `--aplicar` mueve y `--capturas` incluye las imágenes |

## Desarrollo

```powershell
py -m pytest -q
py -m pyflakes main.py src tests diagnostics
```

`pyflakes` solo debe avisar de los `import config.settings` de `diagnostics/diag_*.py`, que se importan por su efecto (cargar el `.env`).

Estructura:

| Carpeta | Contenido |
|---|---|
| `main.py` | Línea de comandos y orquestación |
| `config/` | Configuración y rutas |
| `src/sri/` | Pasos del portal: login, formulario, preguntas, firma, envío, verificación del comprobante |
| `src/core/` | Cola de procesamiento y clasificación de errores |
| `src/database/` | Estado en SQLite (con migración automática y copia de seguridad) |
| `src/security/` | Descifrado y lectura de credenciales |
| `src/services/` | Lectura del Control y anotación de `DECLARADO` en una celda |
| `src/utils/` | Rutas, capturas, logs con enmascarado, validaciones |
| `tests/` | Pruebas automáticas |

Reglas del proyecto:

- Ningún dato real en el repositorio: use RUC ficticios (`1790000000001`) y nunca claves ni archivos de datos.
- El clic en "Aceptar" solo existe en `src/sri/submission.py`.
- Toda regla de seguridad nueva lleva una prueba que falle si se rompe la regla.
- El portal cambia: se localizan los elementos por texto o por nombres estables, nunca por ids generados.

## Pendiente y limitaciones

- **Microsoft Graph:** leer y escribir el Control en OneDrive o SharePoint. `src/microsoft/` y `src/services/tracking_service.py` son marcadores vacíos.
- **Reinicio automático de marcas** al empezar cada mes.
- **Instalador** (PyInstaller e Inno Setup).
- Solo Windows y Edge.
- Si el portal cambia de forma que el programa no reconoce, este se detiene antes que adivinar.

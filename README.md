# HW1_PARTE1: RPA — Registro de Ingresos PeopleSync
Bot en Python + Selenium que automatiza el registro de 50 empleados desde
un dataset de Google Sheets hacia el formulario web PeopleSync HRIS,
validando los datos antes de registrarlos y generando un reporte final.

## Requisitos
- Python 3.10+
- Google Chrome instalado
- Conexión a internet (descarga el dataset y el ChromeDriver
  automáticamente la primera vez)
## Instalación
```bash
pip install -r requirements.txt
```
## Estructura del proyecto
```
rpa_peoplesync.py     # código completo (config, validación, automatización, reportes)
run_rpa.bat            # ejecutor (doble clic)
requirements.txt       # dependencias
output/                # se genera automáticamente al ejecutar
  ├── rpa_run.log
  └── reporte_registro_<fecha>.csv
```
## Configuración
Todo el proyecto se configura editando el diccionario `CONFIG` al inicio
de `rpa_peoplesync.py`:

```python
CONFIG = {
    "form_url": "...",                     # URL del formulario a automatizar
    "sheet_id": "...",                     # id de la hoja de Google Sheets
    "sheet_gid": "0",                      # id de la pestaña dentro de la hoja
    "headless": False,                     # False = ver el navegador; True = ejecución oculta
    "wait_timeout_seconds": 15,
    "post_submit_timeout_seconds": 8,
    "output_dir": "output",                # carpeta de log y reporte (relativa al .py)
    "chrome_binary_path": "",              # ruta a chrome.exe si no está en la ubicación por defecto
    "record_limit": 0,                     # 0 = procesar todos; N = solo los primeros N (pruebas)
    "visual_delay_seconds": 0.4,
    "pause_between_records_seconds": 1.0,
}
```
Para usar otra fuente de datos:

1. Compartir la hoja como "Cualquiera con el enlace puede ver".
2. Copiar el `sheet_id` desde su URL:
   `https://docs.google.com/spreadsheets/d/SHEET_ID/edit`
3. Reemplazar `sheet_id` (y `sheet_gid` si usa otra pestaña) en `CONFIG`.

## Qué modificar en el ejecutor (`run_rpa.bat`)

**No hay que modificar nada.** El `.bat` usa `%~dp0` para ubicarse
automáticamente en la carpeta donde esté guardado:

```bat
cd /d "%~dp0"
```
Solo se debe garantizar que `run_rpa.bat` y `rpa_peoplesync.py` estén
**en la misma carpeta**. Si `python` no está en el PATH del sistema,
agregar la ruta completa al ejecutable dentro del `.bat`
(`"C:\ruta\a\python.exe" rpa_peoplesync.py`).

## Directorios a modificar

- **Ninguno es obligatorio.** El único directorio configurable es
  `output_dir` en `CONFIG` (por defecto `"output"`, relativo a la
  ubicación del `.py`); cambiarlo solo si se desea guardar logs y
  reportes en otra ruta.
- `chrome_binary_path` en `CONFIG` solo debe llenarse si Chrome está
  instalado en una ubicación no estándar.

## Desde dónde ejecutarlo

1. Colocar `rpa_peoplesync.py`Y `run_rpa.bat` en
   una misma carpeta (cualquier ubicación del equipo).
2. Instalar dependencias una vez: `pip install -r requirements.txt`.
3. Ejecutar con **doble clic en `run_rpa.bat`**, o desde terminal:
   ```bash
   cd ruta\a\la\carpeta
   python rpa_peoplesync.py
   ```
4. Para ejecución automática y desatendida (Programador de Tareas de
   Windows): programar la acción "Iniciar un programa" apuntando a
   `run_rpa.bat`. Se recomienda poner `"headless": True` en `CONFIG`
   para ese caso.

## Salidas generadas

- `output/rpa_run.log` — registro cronológico de la ejecución.
- `output/reporte_registro_<fecha>.csv` — una fila por registro
  procesado: fila, DNI, nombre, estado (`OK` / `INVALID_DATA` /
  `FORM_ERROR`), motivo del fallo y tiempo de procesamiento.




# HW1_PARTE2:Bot de extracción de Tipo de Cambio — SUNAT

Extrae el tipo de cambio diario (compra/venta) publicado por SUNAT
(https://e-consulta.sunat.gob.pe/cl-at-ittipcam/tcS01Alias), navegando
la página por clics con Selenium mes a mes, y lo consolida en un único
archivo Excel/CSV.

## 1. Requisitos

- Python 3.10+
- Google Chrome instalado (el driver se gestiona solo, ver abajo)

```bash
pip install selenium webdriver-manager pandas openpyxl --break-system-packages
```
`webdriver-manager` descarga y cachea automáticamente el `chromedriver`
compatible con la versión de Chrome instalada — no requiere descargarlo
a mano.

## 2. Estructura de archivos

```
TAREA_2.py          # script principal (todo el proyecto vive en un solo archivo)
logs/                # se crea sola en la primera corrida
  sunat_tc_AAAAMMDD.log
tipo_cambio_sunat.xlsx   # archivo de salida (nombre configurable, ver §4)
```
Las rutas relativas (log y salida) se resuelven siempre contra la
**carpeta donde está `TAREA_2.py`** (`BASE_DIR = Path(__file__).resolve().parent`),
sin importar desde qué directorio de trabajo se invoque el script. No
es necesario `cd` a la carpeta del proyecto para ejecutarlo.

## 3. Ejecución básica

```bash
python TAREA_2.py
```

Sin argumentos, corre con los valores por defecto: desde enero 2024
hasta el mes actual, guarda `tipo_cambio_sunat.xlsx` en la carpeta del
script, y muestra el navegador (no headless).

## 4. Variables configurables (línea de comandos)

Nada queda hardcodeado en el código; todo se ajusta con flags:

| Flag | Tipo | Por defecto | Descripción |
|---|---|---|---|
| `--inicio` | `YYYY-MM` | `2024-01` | Mes/año de inicio del rango a extraer. |
| `--fin` | `YYYY-MM` | *(vacío → mes actual)* | Mes/año final del rango. Si se omite, llega hasta el mes en curso. |
| `--salida` | ruta | `tipo_cambio_sunat.xlsx` | Archivo de salida. `.xlsx` recomendado; `.csv` se exporta con `;` como separador (evita el problema de Excel en español, que espera `;` y no `,`). Ruta relativa → se resuelve contra `BASE_DIR`. |
| `--headless` | flag | desactivado | Corre sin ventana de Chrome visible. **Usar siempre** al programarlo en el Programador de tareas de Windows. |
| `--min-espera` | segundos (float) | `1.5` | Espera mínima aleatoria entre peticiones a SUNAT (no saturar el servidor). |
| `--max-espera` | segundos (float) | `3.5` | Espera máxima aleatoria entre peticiones. |
| `--timeout` | segundos (int) | `20` | Tiempo máximo de espera (`WebDriverWait`) por cada paso (apertura de calendario, carga de tabla, etc.). |

### Ejemplos

Traer solo el año 2025, a un archivo con otro nombre:
```bash
python TAREA_2.py --inicio 2025-01 --fin 2025-12 --salida tipo_cambio_2025.xlsx
```

Actualizar hasta el mes actual, corriendo desatendido (sin ventana):
```bash
python TAREA_2.py --inicio 2024-01 --headless --salida tipo_cambio_sunat.xlsx
```

## 5. Documento resultante

Un único archivo (`.xlsx` o `.csv`) con una fila por cada **día
calendario** del rango solicitado y tres columnas:

| Columna | Formato | Contenido |
|---|---|---|
| `Fecha` | `dd/mm/aaaa` | Fecha del día |
| `Tipo_Cambio_Compra` | numérico | Tipo de cambio de compra. `NaN` si SUNAT no publicó tarifa ese día (fin de semana, feriado). |
| `Tipo_Cambio_Venta` | numérico | Tipo de cambio de venta. `NaN` en las mismas condiciones. |

## 6. Logging

Cada corrida escribe en `logs/sunat_tc_AAAAMMDD.log` (un archivo por
día, `INFO` en consola + archivo, con timestamp). Ante cualquier falla
no controlada, el traceback completo queda registrado ahí — es el
primer lugar a revisar si el script corrió desatendido (Task
Scheduler) y no hay consola visible para ver el error.

## 7. Ejecución automática (Programador de tareas de Windows)

1. Crear un `.bat` junto a `TAREA_2.py`, por ejemplo `ejecutar_sunat.bat`:
   ```bat
   @echo off
   cd /d "C:\ruta\a\tu\proyecto"
   "C:\ruta\a\python.exe" "TAREA_2.py" --headless --salida "tipo_cambio_sunat.xlsx"
   ```
   (Para ubicar tu `python.exe`, en PowerShell: `where python`.)
2. Probar el `.bat` con doble clic manualmente antes de programarlo —
   si falla ahí, va a fallar igual en el Programador de tareas.
3. Abrir **Programador de tareas** → *Crear tarea básica* → nombre y
   frecuencia (Diario/Semanal/Mensual) → en *Acción*, "Iniciar un
   programa" → seleccionar el `.bat`.
4. En Propiedades de la tarea creada: marcar **"Ejecutar solo cuando
   el usuario haya iniciado sesión"** (evita pedir contraseña de
   cuenta; ver nota abajo si se requiere que corra con sesión
   cerrada).
5. Para demostrar que quedó configurada: clic derecho sobre la tarea →
   **Ejecutar**, y verificar en la columna *Estado*/*Resultado de la
   última ejecución* (`0x0` = éxito), además de la fecha de
   modificación del archivo de salida.


## 8. Cómo funciona (resumen técnico)

1. Carga la página y espera ~3 s a que termine el auto-init propio del
   sitio (que resetea el calendario al mes actual 2.5 s después de
   cargar) antes de tocar nada.
2. Abre el selector de mes/año (clic en el ícono de calendario),
   navega el año con las flechas del widget (`.datepicker-months`) y
   hace clic en el mes de inicio.
3. Clic en "Buscar", espera a que desaparezca el overlay de carga
   (`blockUI`) y lee la tabla de resultados (`table.calendar-table`).
4. Extrae cada día leyendo la fecha exacta codificada en el atributo
   `class` de la celda (`_2024_1_15` → año/mes/día), no por conteo
   secuencial.
5. Clic en `.js-cal-next` para avanzar de mes, espera a que el
   contenido cambie, y repite hasta el mes final (actual o `--fin`).
6. Consolida todos los meses y exporta el archivo final.


# HW1_PARTE3: API de Lichess — Análisis y Automatización de Datos

Dos archivos de códigos, el primero TAREA_3_PARTE_A y el segundo TAREA_3_PARTE_A:
- **Parte A**: extracción y análisis estadístico de partidas de un usuario (Pandas + Matplotlib).
- **Parte B**: automatización de creación de torneos vía API autenticada, con `dry-run`.
## Requisitos
- Python ≥ 3.9
- Jupyter Notebook/Lab o VS Code + extensión Jupyter
- Conexión a internet (consume `lichess.org/api`)
Dependencias (`requests`, `pandas`, `matplotlib`) se instalan automáticamente en la primera celda.
Si VS Code muestra *"requires the ipykernel package"*:
```bash
conda install -n base ipykernel --update-deps --force-reinstall
# o, sin conda:
pip install ipykernel
```
## Ejecución
1. Abrir `TAREA_3_PARTE_A` desde la carpeta donde se encuentra el archivo.
2. Ejecutar las celdas en orden, de arriba hacia abajo, una vez cada una.
3. Para volver a correr todo: `Kernel → Restart & Run All` (evita conflictos de conexión, ver Troubleshooting).
4. Sucede lo mismo con `TAREA_3_PARTE_B` abrir desde la carpeta en la que se encuentra el archivo.
## Configuración
**Parte A** — :
```python
USERNAME  = "thibault"   # usuario Lichess existente a analizar
MAX_GAMES = 100           # cantidad de partidas a descargar
API_TOKEN = ""            # opcional (endpoint de lectura es público)
```
**Parte B** :
```python
TOURNAMENT_TOKEN = ""    # obligatorio si DRY_RUN = False
DRY_RUN = True             # True = simula sin llamar al endpoint de escritura
# Para una ejecución real cambiar True por False una vez ingresado el TOKEN.

```
El calendario de torneos (`WEEKLY_SCHEDULE`) es una lista de dicts editable: día, hora, modo, variante, clock, duración y `rated`.

## Autenticación (API key)

| Parte | ¿Token requerido? | Scope |
|---|---|---|
| A (lectura) | No | — |
| B (`DRY_RUN=False`) | Sí | `tournament:write` |

Generación: `lichess.org` → **Preferences → API access tokens** → *New personal API access token* → marcar `tournament:write` → copiar (se muestra una sola vez).

Pegar el valor en `API_TOKEN` y/o `TOURNAMENT_TOKEN`. No versionar el token; para uso en repositorio público, cargarlo por variable de entorno:
```python
import os
TOURNAMENT_TOKEN = os.getenv("LICHESS_TOKEN", "")
```

## Directorios

- `lichess_stats` se crea automáticamente (ruta relativa al notebook) al ejecutar la celda de exportación de la Parte A. Contiene los 6 CSV de resultados y los archivos PNG.
- La Parte B no genera archivos; su salida es la tabla `df_resultados` dentro del notebook.

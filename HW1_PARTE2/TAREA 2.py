"""
sunat_tipo_cambio_clicks.py
============================

Bot que extrae el tipo de cambio (compra/venta) de SUNAT navegando la
página TAL COMO lo haría una persona: abre el selector de mes/año
(imagen "Seleccione Mes"), lo posiciona en enero 2024 haciendo clic
en el calendario, hace clic en "Buscar", lee la tabla-calendario de
resultados (imagen con Compra/Venta por día) y luego hace clic
repetidamente en el botón ">" para avanzar mes a mes hasta el mes
actual, extrayendo cada tabla en el camino.
"""

from __future__ import annotations

import argparse
import logging
import random
import re
import sys
import time
from calendar import monthrange
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import (
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager

# --------------------------------------------------------------------------- #
# Configuración / localizadores 
# --------------------------------------------------------------------------- #

URL = "https://e-consulta.sunat.gob.pe/cl-at-ittipcam/tcS01Alias"

MESES_ABREV = {
    1: "ene", 2: "feb", 3: "mar", 4: "abr", 5: "may", 6: "jun",
    7: "jul", 8: "ago", 9: "sep", 10: "oct", 11: "nov", 12: "dic",
}
MESES_NOMBRE = {
    1: "Enero", 2: "Febrero", 3: "Marzo", 4: "Abril", 5: "Mayo", 6: "Junio",
    7: "Julio", 8: "Agosto", 9: "Septiembre", 10: "Octubre", 11: "Noviembre",
    12: "Diciembre",
}

LOCATORS = {
    # Input "Seleccione Mes" — id 
    "input_mes": (By.ID, "fecAsistenciaBusq"),
    # El datetimepicker (Eonasdan) se abre con clic en el ÍCONO del
    # calendario 
    "icono_calendario": (By.CSS_SELECTOR, "#fecAsistenciaBusqDiv .input-group-addon"),
    # Botón "Buscar" 
    "boton_buscar": (By.ID, "btnBuscarAsistencias"),

    # --- Popup del selector de mes/año ---
    # Es un "Eonasdan bootstrap-datetimepicker" (jQuery), inicializado con
    # format:'MMM YYYY', locale:'es'. 
    "dp_widget": (By.CSS_SELECTOR, ".bootstrap-datetimepicker-widget"),
    # El widget tiene 4 vistas superpuestas en el DOM a la vez (días,
    # meses, años, décadas); solo una está visible (display:block) según
    # el "viewMode" (aquí siempre "months", por el format:'MMM YYYY').
    # Por eso TODO se busca escopado dentro de ".datepicker-months",
    # para no toparse con los th/span de las otras vistas ocultas.
    "dp_prev_anho": (By.CSS_SELECTOR, ".datepicker-months th.prev"),
    "dp_next_anho": (By.CSS_SELECTOR, ".datepicker-months th.next"),
    "dp_anho_label": (By.CSS_SELECTOR, ".datepicker-months th.picker-switch"),
    "dp_month_cells": (By.CSS_SELECTOR, ".datepicker-months span.month"),

    # --- Tabla de resultados "Tipo de Cambio Mensual" ---
    "tabla_resultados": (By.CSS_SELECTOR, "table.calendar-table"),
    "celdas_dia_mes_actual": (By.CSS_SELECTOR, "table.calendar-table td.calendar-day.current"),
    "flecha_anterior": (By.CSS_SELECTOR, ".js-cal-prev"),
    "flecha_siguiente": (By.CSS_SELECTOR, ".js-cal-next"),
    # Overlay de bloqueo mientras corre el AJAX (jQuery blockUI, visto en
    # el JS fuente: $.blockUI() / $.unblockUI()). Esperamos a que
    # desaparezca como señal de que la recarga terminó.
    "overlay_carga": (By.CSS_SELECTOR, ".blockUI, .blockOverlay"),
}

# BASE_DIR = carpeta donde está este script (NO el directorio de trabajo
# actual). 
BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
LOG_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-7s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(sys.stdout),
        # Log a archivo: imprescindible para tareas programadas, donde
        # nadie ve la consola. Un archivo por día de ejecución.
        logging.FileHandler(
            LOG_DIR / f"sunat_tc_{date.today():%Y%m%d}.log", encoding="utf-8"
        ),
    ],
)
log = logging.getLogger("sunat_tc_clicks")

#Configuración del rango de fechas:
@dataclass
class Config:
    fecha_inicio: date
    salida: Path
    fecha_fin: Optional[date] = None
    headless: bool = False
    min_espera: float = 1.5
    max_espera: float = 3.5
    timeout: int = 20


# --------------------------------------------------------------------------- #
# Driver
# --------------------------------------------------------------------------- #

def crear_driver(headless: bool) -> webdriver.Chrome:
    opciones = Options()
    if headless:
        opciones.add_argument("--headless=new")
    opciones.add_argument("--window-size=1366,900")
    opciones.add_argument("--disable-gpu")
    opciones.add_argument("--no-sandbox")
    opciones.add_argument("--disable-dev-shm-usage")

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=opciones)
    driver.set_page_load_timeout(30)
    return driver


def _pausa(cfg: Config) -> None:
    time.sleep(random.uniform(cfg.min_espera, cfg.max_espera))


# --------------------------------------------------------------------------- #
# Navegación del datepicker (mes/año) — Eonasdan bootstrap-datetimepicker
# --------------------------------------------------------------------------- #
# Al estar configurado con format:'MMM YYYY' (sin día), el widget solo
# tiene una vista: la grilla de 12 meses con el año arriba (imagen
# "2024" + "ene. feb. mar. ..."). 

def abrir_selector_mes(driver, wait: WebDriverWait) -> None:
    icono = wait.until(EC.element_to_be_clickable(LOCATORS["icono_calendario"]))
    icono.click()
    try:
        wait.until(EC.visibility_of_element_located(LOCATORS["dp_widget"]))
        return
    except TimeoutException:
        log.warning("El ícono no abrió el calendario; probando clic directo en el input...")

    campo = wait.until(EC.element_to_be_clickable(LOCATORS["input_mes"]))
    campo.click()
    wait.until(EC.visibility_of_element_located(LOCATORS["dp_widget"]))


def _texto_anho_actual(driver) -> str:
    return driver.find_element(*LOCATORS["dp_anho_label"]).text.strip()


def _navegar_a_anho(driver, wait: WebDriverWait, anho_objetivo: int) -> None:
    """Usa th.prev / th.next para llegar al año objetivo en la vista de meses."""
    wait.until(lambda d: _texto_anho_actual(d).strip() != "")
    for _ in range(200):  # límite de seguridad
        texto_actual = _texto_anho_actual(driver)
        m = re.search(r"\d{4}", texto_actual)
        if not m:
            raise RuntimeError(f"No se pudo leer el año actual del datepicker: '{texto_actual}'")
        anho_actual = int(m.group())

        if anho_actual == anho_objetivo:
            return

        boton = LOCATORS["dp_prev_anho"] if anho_actual > anho_objetivo else LOCATORS["dp_next_anho"]
        wait.until(EC.element_to_be_clickable(boton)).click()
        wait.until(lambda d: _texto_anho_actual(d) != texto_actual)

    raise RuntimeError(f"No se logró llegar al año {anho_objetivo} tras varios intentos.")


def seleccionar_mes_anho(driver, wait: WebDriverWait, mes: int, anho: int) -> None:
    """
    Abre el datepicker, navega hasta el año indicado y hace clic en el
    mes (celda <span class="month">ene.</span>, etc). Al hacer clic el
    widget se cierra y el input queda con el mes/año seleccionado.
    """
    abrir_selector_mes(driver, wait)
    _navegar_a_anho(driver, wait, anho)

    abrev = MESES_ABREV[mes]
    celdas = driver.find_elements(*LOCATORS["dp_month_cells"])
    if not celdas:
        raise RuntimeError("No se encontraron celdas de mes (dp_month_cells) en el datepicker.")

    objetivo = None
    for celda in celdas:
        texto = re.sub(r"[^a-záéíóúñ]", "", celda.text.strip().lower())
        if texto.startswith(abrev):
            objetivo = celda
            break

    if objetivo is None:
        raise RuntimeError(f"No se encontró la celda del mes '{abrev}' en el datepicker.")

    objetivo.click()
    log.info("Seleccionado %s %d en el calendario.", MESES_NOMBRE[mes], anho)


# --------------------------------------------------------------------------- #
# Búsqueda y lectura de la tabla-calendario de resultados
# --------------------------------------------------------------------------- #

def hacer_click_buscar(driver, wait: WebDriverWait) -> None:
    boton = wait.until(EC.element_to_be_clickable(LOCATORS["boton_buscar"]))
    boton.click()
    try:
        wait.until(EC.invisibility_of_element_located(LOCATORS["overlay_carga"]))
    except TimeoutException:
        pass  # puede que nunca haya llegado a aparecer; no es crítico.
    wait.until(EC.presence_of_element_located(LOCATORS["tabla_resultados"]))


def _html_tabla_resultados(driver) -> str:
    tabla = driver.find_element(*LOCATORS["tabla_resultados"])
    return tabla.get_attribute("innerHTML")


def extraer_mes_desde_calendario(driver, mes: int, anho: int) -> pd.DataFrame:
    """
    Lee la tabla-calendario y devuelve un DataFrame con
    columnas: dia, compra, venta (NaN si el día no tiene tarifa
    publicada). Cada celda del mes trae su fecha exacta en la clase
    CSS (ej. "calendar-day current _2026_8_25" -> año=2026, mes=8
    (1-indexado), día=25), así que no hace falta reconstruir la
    secuencia de días: basta con leer y parsear ese atributo.
    """
    celdas = driver.find_elements(*LOCATORS["celdas_dia_mes_actual"])
    if not celdas:
        raise RuntimeError(
            "No se encontraron celdas 'td.calendar-day.current'. "
            "Revise LOCATORS['celdas_dia_mes_actual']."
        )

    registros = {}
    patron_fecha = re.compile(r"_(\d{4})_(\d{1,2})_(\d{1,2})")

    for celda in celdas:
        clases = celda.get_attribute("class") or ""
        m_fecha = patron_fecha.search(clases)
        if not m_fecha:
            continue  # celda sin el patrón de fecha esperado; se ignora

        anho_celda, mes_celda, dia_celda = (int(x) for x in m_fecha.groups())
        # Aunque filtramos por ".current", confirmamos que el mes/año
        # coincida con lo solicitado (por si el sitio reordena celdas).
        if (anho_celda, mes_celda) != (anho, mes):
            continue

        texto = celda.text.strip()
        m_compra = re.search(r"Compra\s*([\d]+[.,]\d+)", texto, re.IGNORECASE)
        m_venta = re.search(r"Venta\s*([\d]+[.,]\d+)", texto, re.IGNORECASE)

        compra = float(m_compra.group(1).replace(",", ".")) if m_compra else float("nan")
        venta = float(m_venta.group(1).replace(",", ".")) if m_venta else float("nan")

        registros[dia_celda] = {"dia": dia_celda, "compra": compra, "venta": venta}

    # Días que no aparecieron en absoluto en la grilla también quedan NaN.
    dias_en_mes = monthrange(anho, mes)[1]
    for dia in range(1, dias_en_mes + 1):
        if dia not in registros:
            registros[dia] = {"dia": dia, "compra": float("nan"), "venta": float("nan")}

    df = pd.DataFrame(sorted(registros.values(), key=lambda r: r["dia"])).reset_index(drop=True)
    df["mes"] = mes
    df["anho"] = anho
    return df


def avanzar_al_siguiente_mes(driver, wait: WebDriverWait, timeout: int) -> None:
    """Clic en '.js-cal-next' y espera a que la tabla de resultados se actualice."""
    html_anterior = _html_tabla_resultados(driver)
    boton = wait.until(EC.element_to_be_clickable(LOCATORS["flecha_siguiente"]))
    boton.click()

    # 1) Esperar a que desaparezca el overlay de carga (blockUI), si aparece.
    try:
        WebDriverWait(driver, timeout).until(
            EC.invisibility_of_element_located(LOCATORS["overlay_carga"])
        )
    except TimeoutException:
        pass

    # 2) Confirmar que el contenido de la tabla realmente cambió.
    def _cambio(d):
        try:
            return _html_tabla_resultados(d) != html_anterior
        except (NoSuchElementException, StaleElementReferenceException):
            return False

    WebDriverWait(driver, timeout).until(_cambio)


# --------------------------------------------------------------------------- #
# Orquestación
# --------------------------------------------------------------------------- #

def ejecutar(cfg: Config) -> pd.DataFrame:
    driver = crear_driver(cfg.headless)
    wait = WebDriverWait(driver, cfg.timeout)
    resultados = []

    try:
        driver.get(URL)
        driver.maximize_window()
        driver.execute_script("document.body.style.zoom='100%'")

        # La página se auto-inicializa con el mes ACTUAL 2.5s después de
        # cargar (setTimeout(..., 2500) en su propio JS) y sobreescribe
        # cualquier selección que hagamos antes de eso. Esperamos a que
        # ese auto-reinicio ya haya ocurrido antes de tocar el calendario.
        log.info("Esperando a que la página termine su auto-carga inicial...")
        wait.until(EC.presence_of_element_located(LOCATORS["celdas_dia_mes_actual"]))
        time.sleep(1.0)  

        mes, anho = cfg.fecha_inicio.month, cfg.fecha_inicio.year
        # Límite superior del rango: el configurado en cfg.fecha_fin, o el
        # mes actual si no se especificó ninguno.
        limite = cfg.fecha_fin if cfg.fecha_fin is not None else date.today()
        mes_fin, anho_fin = limite.month, limite.year

        if (anho, mes) > (anho_fin, mes_fin):
            raise ValueError(
                f"La fecha de inicio ({mes:02d}/{anho}) es posterior a la fecha "
                f"de fin ({mes_fin:02d}/{anho_fin}). Revise --inicio y --fin."
            )

        # 1) Calendario -> fecha inicial -> Buscar
        seleccionar_mes_anho(driver, wait, mes, anho)
        hacer_click_buscar(driver, wait)
        _pausa(cfg)

        # 2) Iterar mes a mes con '>' hasta llegar al mes límite
        while True:
            log.info("Extrayendo %s %d ...", MESES_NOMBRE[mes], anho)
            df_mes = extraer_mes_desde_calendario(driver, mes, anho)
            resultados.append(df_mes)
            log.info(
                "%s %d: %d días con tarifa publicada de %d.",
                MESES_NOMBRE[mes], anho, df_mes[["compra", "venta"]].notna().all(axis=1).sum(),
                len(df_mes),
            )

            if (anho, mes) == (anho_fin, mes_fin):
                break

            avanzar_al_siguiente_mes(driver, wait, cfg.timeout)
            _pausa(cfg)

            mes += 1
            if mes > 12:
                mes = 1
                anho += 1

    finally:
        driver.quit()

    return pd.concat(resultados, ignore_index=True) if resultados else pd.DataFrame()


# --------------------------------------------------------------------------- #
# Formato final: Fecha (dd/mm/aaaa), Compra, Venta — NaN si falta
# --------------------------------------------------------------------------- #

def formatear_dataset(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return pd.DataFrame(columns=["Fecha", "Tipo_Cambio_Compra", "Tipo_Cambio_Venta"])

    df = df.copy()
    df["Fecha"] = pd.to_datetime(dict(year=df["anho"], month=df["mes"], day=df["dia"]))
    df = df.sort_values("Fecha")
    df["Fecha"] = df["Fecha"].dt.strftime("%d/%m/%Y")

    salida = df.rename(columns={"compra": "Tipo_Cambio_Compra", "venta": "Tipo_Cambio_Venta"})
    salida = salida[["Fecha", "Tipo_Cambio_Compra", "Tipo_Cambio_Venta"]]

    # Se descartan los días sin NINGÚN dato (compra Y venta ambos NaN:
    # típicamente fines de semana/feriados sin tipo de cambio publicado).
    # Si solo falta uno de los dos valores, la fila SÍ se conserva (con
    # NaN en esa columna), porque ahí sí hubo un dato parcial publicado.
    filas_antes = len(salida)
    salida = salida.dropna(subset=["Tipo_Cambio_Compra", "Tipo_Cambio_Venta"], how="all")
    descartadas = filas_antes - len(salida)
    if descartadas:
        log.info("Se descartaron %d filas sin ningún dato (compra y venta NaN).", descartadas)

    return salida.reset_index(drop=True)


def exportar(df: pd.DataFrame, ruta: Path) -> None:
    """
    Exporta el DataFrame YA separado en columnas (Fecha, Tipo_Cambio_Compra,
    Tipo_Cambio_Venta).
    """
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if ruta.suffix.lower() in (".xlsx", ".xls"):
        df.to_excel(ruta, index=False, sheet_name="Tipo_Cambio_SUNAT")
    else:
        df.to_csv(ruta, index=False, sep=";", encoding="utf-8-sig")
    log.info("Archivo exportado en: %s (%d filas)", ruta.resolve(), len(df))


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Extrae tipo de cambio SUNAT por clics, desde enero 2024 hasta el mes actual.")
    parser.add_argument("--inicio", default="2024-01", help="Mes/año inicial YYYY-MM (por defecto 2024-01).")
    parser.add_argument(
        "--fin",
        default=None,
        help="Mes/año final YYYY-MM (opcional). Si no se indica, llega hasta el mes actual.",
    )
    parser.add_argument(
        "--salida",
        default="tipo_cambio_sunat.xlsx",
        help="Ruta de salida .csv o .xlsx (por defecto .xlsx, recomendado para evitar problemas de separador en Excel).",
    )
    parser.add_argument("--headless", action="store_true", default=False, help="Ejecutar sin ventana visible.")
    parser.add_argument("--min-espera", type=float, default=1.5)
    parser.add_argument("--max-espera", type=float, default=3.5)
    parser.add_argument("--timeout", type=int, default=20)
    args = parser.parse_args(argv)

    anho_i, mes_i = args.inicio.split("-")
    fecha_fin = None
    if args.fin:
        anho_f, mes_f = args.fin.split("-")
        fecha_fin = date(int(anho_f), int(mes_f), 1)

    ruta_salida = Path(args.salida)
    if not ruta_salida.is_absolute():
        ruta_salida = BASE_DIR / ruta_salida

    cfg = Config(
        fecha_inicio=date(int(anho_i), int(mes_i), 1),
        salida=ruta_salida,
        fecha_fin=fecha_fin,
        headless=args.headless,
        min_espera=args.min_espera,
        max_espera=args.max_espera,
        timeout=args.timeout,
    )

    log.info("Iniciando bot SUNAT (modo clics)...")
    try:
        df_bruto = ejecutar(cfg)
        df_final = formatear_dataset(df_bruto)

        if df_final.empty:
            log.error("No se extrajo información. Revise los LOCATORS si la página cambió de estructura.")
            return 1

        exportar(df_final, cfg.salida)
        faltantes = df_final["Tipo_Cambio_Compra"].isna().sum()
        log.info("Proceso finalizado. %d filas, %d días sin tarifa publicada (NaN).", len(df_final), faltantes)
        return 0
    except Exception:
        # Sin este try/except, un error al correr desatendido (via Task
        # Scheduler) simplemente termina el proceso sin dejar rastro
        # legible. Con esto, el traceback completo queda en logs/.
        log.exception("El proceso terminó con un error no controlado.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
#---------------------------------------------------------------------
#OJO: Para configurar el rango de fecha se ejecuta con el siguiente
#comando configurable:
#---------------------------------------------------------------------
#python TAREA_2.py --inicio 2024-01 --fin 2025-06 --salida tipo_cambio_sunat.xlsx

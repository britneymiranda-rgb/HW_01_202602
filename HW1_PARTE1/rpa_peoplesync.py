#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
rpa_peoplesync.py
==================

Bot RPA (Python + Selenium) para automatizar el registro de nuevos
ingresos en el formulario web "PeopleSync HRIS".

Diseñado para:
  - Leer el dataset de entrada directamente desde Google Sheets (CSV export,
    no requiere credenciales de API porque la hoja es "cualquiera con el
    enlace puede ver").
  - Validar cada registro contra las reglas de negocio / opciones reales
    del formulario ANTES de tocar el navegador (evita intentos inútiles).
  - Completar y enviar el formulario para cada registro válido.
  - Verificar que el registro quedó reflejado en el formulario (contador de
    "Ingresos registrados" y tabla de sesión).
  - Continuar procesando aunque un registro individual falle (nunca aborta
    el lote completo por un error puntual).
  - Producir un resumen final + un reporte CSV con el detalle de éxitos y
    fallos (incluyendo motivo del error).
  - Ejecutarse sin intervención manual, apto para el Programador de
    Tareas de Windows (ver run_rpa.bat / README.md).

"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import logging
import re
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import (
    ElementClickInterceptedException,
    NoSuchElementException,
    StaleElementReferenceException,
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait
from webdriver_manager.chrome import ChromeDriverManager


# --------------------------------------------------------------------------
# 1. CONFIGURACIÓN 
# --------------------------------------------------------------------------

SCRIPT_DIR = Path(__file__).resolve().parent

CONFIG = {
    "form_url": "https://the-paul2002.github.io/Proyecto-IA-/Homework1/",
    "sheet_id": "1EjaoSJKdzdUBNF3XJZuTlxA21D-0vy0wkGaMR8wHVgs",
    "sheet_gid": "0",
    "headless": False,                     # False = ver el navegador registrando uno a uno
    "wait_timeout_seconds": 15,
    "post_submit_timeout_seconds": 8,
    "output_dir": "output",                # carpeta (relativa a este archivo) para log y reporte
    "chrome_binary_path": "",              # solo si Chrome no está en la ruta por defecto
    "record_limit": 0,                     # 0 = procesar los 50; N = solo los primeros N
    "visual_delay_seconds": 0.4,           # pausa tras cada campo (solo con headless=False)
    "pause_between_records_seconds": 1.0,  # pausa entre un registro y el siguiente
}


# --------------------------------------------------------------------------
# 2. OPCIONES VÁLIDAS DEL FORMULARIO 
#    Se usan para validar el dataset ANTES de intentar registrar.
# --------------------------------------------------------------------------

VALID_GENEROS = {"Masculino", "Femenino"}

VALID_AREAS = {
    "Recursos Humanos",
    "Finanzas y Contabilidad",
    "Tecnología e Innovación",
    "Operaciones",
    "Comercial y Ventas",
    "Marketing",
    "Legal y Cumplimiento",
    "Logística y Supply Chain",
    "Servicio al Cliente",
    "Gerencia General",
}

VALID_PUESTOS = {
    "Analista Jr.", "Analista", "Analista Sr.", "Analista de Datos",
    "Analista de RRHH", "Analista Financiero",
    "Especialista en TI", "Especialista Legal", "Especialista en Marketing",
    "Especialista en Logística",
    "Coordinador de Área", "Coordinador Comercial", "Coordinador de Proyectos",
    "Jefe de Área", "Gerente de Área", "Sub Gerente",
    "Asistente Administrativo", "Practicante Profesional",
    "Practicante Preprofesional",
}

VALID_CONTRATOS = {
    "Planilla Fija", "Contrato por Servicios", "Practicante Profesional",
    "Practicante Preprofesional", "Contrato a Plazo Fijo", "Part-time",
}

VALID_SEDES = {
    "Lima - San Isidro (Sede Central)", "Lima - Miraflores",
    "Lima - La Molina", "Lima - Callao",
    "Arequipa", "Trujillo", "Cusco", "Piura", "Chiclayo",
}

VALID_MODALIDADES = {"Presencial", "Remoto", "Híbrido"}

DNI_RE = re.compile(r"^\d{8}$")
PHONE_RE = re.compile(r"^9\d{8}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")

# Etiquetas visibles en el formulario, usadas para ubicar los campos sin
# depender de ids internos (ver find_field_by_label).
LABELS = {
    "apellidos_nombres": "Apellidos y Nombres",
    "dni": "N° Documento (DNI)",
    "fecha_nacimiento": "Fecha de Nacimiento",
    "genero": "Género",
    "telefono": "Teléfono",
    "correo": "Correo Electrónico Corporativo",
    "area": "Área / Departamento",
    "puesto": "Puesto / Cargo",
    "contrato": "Tipo de Contrato",
    "sede": "Sede / Oficina",
    "fecha_ingreso": "Fecha de Ingreso",
    "modalidad": "Modalidad de Trabajo",
}


# --------------------------------------------------------------------------
# 3. MODELOS DE DATOS
# --------------------------------------------------------------------------

@dataclass
class RecordResult:
    row_id: str          # identificador del registro (fila / DNI)
    dni: str
    nombre: str
    status: str           # "OK" | "INVALID_DATA" | "FORM_ERROR"
    reason: str = ""
    elapsed_seconds: float = 0.0


# --------------------------------------------------------------------------
# 4. CARGA Y VALIDACIÓN DE DATOS
# --------------------------------------------------------------------------

def build_csv_export_url(sheet_id: str, gid: str) -> str:
    return f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv&gid={gid}"


def load_dataset(sheet_id: str, gid: str) -> pd.DataFrame:
    url = build_csv_export_url(sheet_id, gid)
    logging.info("Descargando dataset desde Google Sheets: %s", url)
    df = pd.read_csv(url, dtype=str, keep_default_na=False)
    df.columns = [c.strip().lower() for c in df.columns]
    # Elimina filas completamente vacías (por si la hoja tiene filas extra)
    df = df[df["dni"].str.strip() != ""].reset_index(drop=True)
    return df


def parse_ddmmyyyy_to_iso(value: str) -> Optional[str]:
    """Convierte 'D/M/AAAA' o 'DD/MM/AAAA' a 'AAAA-MM-DD'. None si inválida."""
    value = (value or "").strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return dt.datetime.strptime(value, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def validate_record(raw: dict) -> tuple[bool, dict, list[str]]:
    """
    Valida un registro crudo del dataset contra las reglas de negocio y las
    opciones reales del formulario.

    Retorna (es_valido, registro_normalizado, lista_de_errores)
    """
    errors: list[str] = []

    nombre = (raw.get("apellidos_nombres") or "").strip()
    if not nombre:
        errors.append("Apellidos y Nombres vacío")

    dni = (raw.get("dni") or "").strip()
    if not DNI_RE.match(dni):
        errors.append(f"DNI inválido ('{dni}'): debe tener 8 dígitos numéricos")

    fecha_nac_iso = parse_ddmmyyyy_to_iso(raw.get("fecha_nacimiento", ""))
    if not fecha_nac_iso:
        errors.append(f"Fecha de nacimiento inválida ('{raw.get('fecha_nacimiento')}')")

    genero = (raw.get("genero") or "").strip()
    if genero not in VALID_GENEROS:
        errors.append(
            f"Género '{genero}' no soportado por el formulario "
            f"(opciones válidas: {', '.join(sorted(VALID_GENEROS))})"
        )

    telefono = (raw.get("telefono") or "").strip()
    if not PHONE_RE.match(telefono):
        errors.append(f"Teléfono inválido ('{telefono}')")

    correo = (raw.get("correo") or "").strip()
    if not EMAIL_RE.match(correo):
        errors.append(f"Correo inválido ('{correo}')")

    area = (raw.get("area") or "").strip()
    if area not in VALID_AREAS:
        errors.append(f"Área '{area}' no existe en el formulario")

    puesto = (raw.get("puesto") or "").strip()
    if puesto not in VALID_PUESTOS:
        errors.append(f"Puesto '{puesto}' no existe en el formulario")

    contrato = (raw.get("contrato") or "").strip()
    if contrato not in VALID_CONTRATOS:
        errors.append(f"Tipo de contrato '{contrato}' no existe en el formulario")

    sede = (raw.get("sede") or "").strip()
    if sede not in VALID_SEDES:
        errors.append(f"Sede '{sede}' no existe en el formulario")

    fecha_ing_iso = parse_ddmmyyyy_to_iso(raw.get("fecha_ingreso", ""))
    if not fecha_ing_iso:
        errors.append(f"Fecha de ingreso inválida ('{raw.get('fecha_ingreso')}')")

    modalidad = (raw.get("modalidad") or "").strip()
    if modalidad not in VALID_MODALIDADES:
        errors.append(f"Modalidad '{modalidad}' no existe en el formulario")

    if errors:
        return False, {}, errors

    normalized = {
        "apellidos_nombres": nombre,
        "dni": dni,
        "fecha_nacimiento": fecha_nac_iso,
        "genero": genero,
        "telefono": telefono,
        "correo": correo,
        "area": area,
        "puesto": puesto,
        "contrato": contrato,
        "sede": sede,
        "fecha_ingreso": fecha_ing_iso,
        "modalidad": modalidad,
    }
    return True, normalized, []


# --------------------------------------------------------------------------
# 5. SELENIUM
# --------------------------------------------------------------------------
#
# El formulario no expone una API pública con ids documentados, así que en
# vez de depender de ids frágiles, ubicamos cada campo por su ETIQUETA
# visible (texto que un humano vería), que es mucho más estable frente a
# cambios internos de implementación. Si el sitio cambiara sus etiquetas,
# basta con editar el diccionario LABELS de arriba.

def _label_xpath(label_text: str) -> str:
    # normalize-space + contains para tolerar el asterisco "*" de obligatorio
    return f'//label[contains(normalize-space(.), "{label_text}")]'


def find_control_for_label(driver, wait: WebDriverWait, label_text: str):
    """Ubica el input/select/textarea asociado a una etiqueta visible."""
    label = wait.until(EC.presence_of_element_located((By.XPATH, _label_xpath(label_text))))

    for_attr = label.get_attribute("for")
    if for_attr:
        try:
            return driver.find_element(By.ID, for_attr)
        except NoSuchElementException:
            pass

    # Fallback 1: el control está dentro del mismo contenedor (padre) que la etiqueta
    for ancestor_level in range(1, 4):
        try:
            container = label.find_element(By.XPATH, "./" + "/".join([".."] * ancestor_level))
            for tag in ("input", "select", "textarea"):
                elems = container.find_elements(By.XPATH, f".//{tag}")
                if elems:
                    return elems[0]
        except (NoSuchElementException, StaleElementReferenceException):
            continue

    # Fallback 2: el control es el siguiente elemento del DOM tras la etiqueta
    for tag in ("input", "select", "textarea"):
        elems = label.find_elements(By.XPATH, f"./following::{tag}[1]")
        if elems:
            return elems[0]

    raise NoSuchElementException(f"No se pudo ubicar el control para la etiqueta '{label_text}'")


def set_text_value(driver, wait: WebDriverWait, label_text: str, value: str):
    field = find_control_for_label(driver, wait, label_text)
    field.click()
    # Selecciona todo el contenido existente y lo borra (más confiable que
    # .clear() en inputs controlados por frameworks JS) y luego escribe.
    field.send_keys(Keys.CONTROL, "a")
    field.send_keys(Keys.DELETE)
    field.clear()
    field.send_keys(value)
    # Dispara eventos 'input' y 'change' por si el framework de UI (React/Vue)
    # necesita el evento explícito para validar el campo.
    driver.execute_script(
        "arguments[0].dispatchEvent(new Event('input', {bubbles: true}));"
        "arguments[0].dispatchEvent(new Event('change', {bubbles: true}));"
        "arguments[0].dispatchEvent(new Event('blur', {bubbles: true}));",
        field,
    )


def select_dropdown_value(driver, wait: WebDriverWait, label_text: str, visible_text: str):
    field = find_control_for_label(driver, wait, label_text)
    select = Select(field)
    try:
        select.select_by_visible_text(visible_text)
    except NoSuchElementException:
        # Reintento tolerante a espacios/mayúsculas
        target = visible_text.strip().lower()
        matched = None
        for opt in select.options:
            if opt.text.strip().lower() == target:
                matched = opt
                break
        if matched is None:
            raise NoSuchElementException(
                f"La opción '{visible_text}' no existe en el combo '{label_text}'"
            )
        matched.click()
    driver.execute_script(
        "arguments[0].dispatchEvent(new Event('change', {bubbles: true}));", field
    )


def click_choice(driver, wait: WebDriverWait, group_label: str, choice_text: str):
    """
    Para controles tipo 'botones/tarjetas' (p.ej. Modalidad de Trabajo:
    Presencial / Remoto / Híbrido) que no son <select> nativos.
    Busca, dentro del bloque de la etiqueta de grupo, cualquier elemento
    clickeable cuyo texto contenga la opción deseada.
    """
    group_label_el = wait.until(
        EC.presence_of_element_located((By.XPATH, _label_xpath(group_label)))
    )
    # Contenedor amplio: sube hasta 3 niveles buscando el que contenga el texto de la opción
    container = group_label_el
    for _ in range(4):
        try:
            container = container.find_element(By.XPATH, "..")
        except NoSuchElementException:
            break
        candidates = container.find_elements(
            By.XPATH,
            f'.//*[self::button or self::div or self::label or self::input]'
            f'[contains(normalize-space(.), "{choice_text}")]',
        )
        if candidates:
            # Preferir el elemento clickeable más pequeño (hoja del árbol)
            target = min(candidates, key=lambda e: len(e.text or ""))
            try:
                target.click()
            except (ElementClickInterceptedException, WebDriverException):
                driver.execute_script("arguments[0].click();", target)
            return
    raise NoSuchElementException(f"No se pudo ubicar la opción '{choice_text}' para '{group_label}'")


def find_submit_button(driver, wait: WebDriverWait):
    xpath = (
        '//button[contains(normalize-space(.), "Registrar Ingreso")]'
        ' | //input[@type="submit" and contains(@value, "Registrar")]'
    )
    return wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))


def get_session_count(driver) -> Optional[int]:
    """Lee el contador 'Ingresos registrados hoy: N' o 'N registros'."""
    try:
        text = driver.find_element(By.XPATH, "//*[contains(text(), 'registros')]").text
    except NoSuchElementException:
        return None
    match = re.search(r"(\d+)\s*registros?", text)
    if match:
        return int(match.group(1))
    return None


def has_visible_validation_errors(driver) -> list[str]:
    """Busca mensajes de error visibles tipo 'Ingrese un DNI válido...'."""
    error_markers = [
        "válido", "válida", "obligatorio", "Seleccione", "Ingrese",
    ]
    found = []
    for marker in error_markers:
        xpath = (
            f'//*[contains(@class, "error") or contains(@class, "invalid")]'
            f'[contains(., "{marker}")]'
        )
        for el in driver.find_elements(By.XPATH, xpath):
            if el.is_displayed() and el.text.strip():
                found.append(el.text.strip())
    return list(dict.fromkeys(found))  # dedupe conservando orden


# --------------------------------------------------------------------------
# 6. LLENADO Y ENVÍO DE UN REGISTRO
# --------------------------------------------------------------------------

def fill_and_submit(
    driver, wait: WebDriverWait, record: dict, post_submit_timeout: int,
    visual_delay: float = 0.0,
) -> tuple[bool, str]:
    """Completa el formulario con `record` y lo envía. Retorna (ok, motivo).

    `visual_delay` inserta una pequeña pausa tras cada campo para que, en
    modo visible (headless=False), se pueda seguir con la vista cómo el bot
    va llenando el formulario campo por campo. En headless no tiene efecto
    práctico visual pero igual respeta el valor configurado (déjalo en 0
    para ejecuciones desatendidas/rápidas).
    """

    def pause():
        if visual_delay:
            time.sleep(visual_delay)

    set_text_value(driver, wait, LABELS["apellidos_nombres"], record["apellidos_nombres"]); pause()
    set_text_value(driver, wait, LABELS["dni"], record["dni"]); pause()
    set_text_value(driver, wait, LABELS["fecha_nacimiento"], record["fecha_nacimiento"]); pause()
    select_dropdown_value(driver, wait, LABELS["genero"], record["genero"]); pause()
    set_text_value(driver, wait, LABELS["telefono"], record["telefono"]); pause()
    set_text_value(driver, wait, LABELS["correo"], record["correo"]); pause()

    select_dropdown_value(driver, wait, LABELS["area"], record["area"]); pause()
    select_dropdown_value(driver, wait, LABELS["puesto"], record["puesto"]); pause()
    select_dropdown_value(driver, wait, LABELS["contrato"], record["contrato"]); pause()
    select_dropdown_value(driver, wait, LABELS["sede"], record["sede"]); pause()
    set_text_value(driver, wait, LABELS["fecha_ingreso"], record["fecha_ingreso"]); pause()
    click_choice(driver, wait, LABELS["modalidad"], record["modalidad"]); pause()

    count_before = get_session_count(driver)

    submit_btn = find_submit_button(driver, wait)
    try:
        submit_btn.click()
    except (ElementClickInterceptedException, WebDriverException):
        driver.execute_script("arguments[0].click();", submit_btn)

    # Verificación: o bien el contador de sesión sube, o bien aparece el DNI
    # en la tabla de "Ingresos Registrados en esta Sesión".
    end_time = time.time() + post_submit_timeout
    while time.time() < end_time:
        errors_visible = has_visible_validation_errors(driver)
        if errors_visible:
            return False, "El formulario reportó errores de validación: " + " | ".join(errors_visible)

        count_after = get_session_count(driver)
        if count_before is not None and count_after is not None and count_after > count_before:
            return True, "OK"

        # Verificación alternativa: DNI presente en la tabla de la sesión
        dni_rows = driver.find_elements(By.XPATH, f'//td[contains(text(), "{record["dni"]}")]')
        if dni_rows:
            return True, "OK"

        time.sleep(0.3)

    return False, "No se pudo confirmar el registro: el contador/tabla de la sesión no se actualizó a tiempo"


# --------------------------------------------------------------------------
# 7. DRIVER
# --------------------------------------------------------------------------

def build_driver(headless: bool, chrome_binary_path: str) -> webdriver.Chrome:
    options = Options()
    if headless:
        options.add_argument("--headless=new")
    options.add_argument("--window-size=1400,1000")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--lang=es-PE")
    if chrome_binary_path:
        options.binary_location = chrome_binary_path

    service = Service(ChromeDriverManager().install())
    driver = webdriver.Chrome(service=service, options=options)
    if not headless:
        driver.maximize_window()
    return driver


# --------------------------------------------------------------------------
# 8. REPORTE
# --------------------------------------------------------------------------

def write_report(results: list[RecordResult], output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = output_dir / f"reporte_registro_{timestamp}.csv"
    with open(report_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f, delimiter=";")
        writer.writerow(["fila", "dni", "nombre", "estado", "motivo", "segundos"])
        for r in results:
            writer.writerow([r.row_id, r.dni, r.nombre, r.status, r.reason, f"{r.elapsed_seconds:.2f}"])
    return report_path


def print_summary(results: list[RecordResult]):
    total = len(results)
    ok = sum(1 for r in results if r.status == "OK")
    failed = total - ok

    print("\n" + "=" * 70)
    print("RESUMEN DE EJECUCIÓN — PeopleSync RPA")
    print("=" * 70)
    print(f"Total de registros procesados : {total}")
    print(f"Registros cargados exitosamente: {ok}")
    print(f"Registros no cargados          : {failed}")

    if failed:
        print("\nDetalle de registros fallidos:")
        print("-" * 70)
        for r in results:
            if r.status != "OK":
                print(f"  Fila {r.row_id} | DNI {r.dni} | {r.nombre}")
                print(f"      Motivo: {r.reason}")
    print("=" * 70 + "\n")


# --------------------------------------------------------------------------
# 9. MAIN
# --------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="RPA de registro de ingresos PeopleSync")
    parser.add_argument("--limit", type=int, default=None, help="Procesar solo los primeros N registros (0 = todos)")
    parser.add_argument("--headed", action="store_true", help="Mostrar el navegador (modo visible)")
    parser.add_argument("--headless", action="store_true", help="Ocultar el navegador (ejecución desatendida)")
    return parser.parse_args()


def main():
    args = parse_args()

    cfg = dict(CONFIG)
    if args.limit is not None:
        cfg["record_limit"] = args.limit
    if args.headless:
        cfg["headless"] = True
    elif args.headed:
        cfg["headless"] = False

    output_dir = SCRIPT_DIR / cfg["output_dir"]
    output_dir.mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
        handlers=[
            logging.FileHandler(output_dir / "rpa_run.log", encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )

    logging.info("Configuración efectiva: %s", {k: v for k, v in cfg.items()})

    # --- 1. Cargar dataset ---
    try:
        df = load_dataset(cfg["sheet_id"], cfg["sheet_gid"])
    except Exception as exc:
        logging.error("No se pudo descargar el dataset: %s", exc)
        sys.exit(1)

    if cfg["record_limit"]:
        df = df.head(int(cfg["record_limit"]))

    logging.info("Registros leídos del dataset: %d", len(df))

    # --- 2. Validar todos los registros primero ---
    valid_records: list[tuple[str, dict]] = []
    results: list[RecordResult] = []

    for idx, row in df.iterrows():
        row_id = str(idx + 2)  # fila real en la hoja (1 = encabezado)
        raw = row.to_dict()
        is_valid, normalized, errors = validate_record(raw)
        if is_valid:
            valid_records.append((row_id, normalized))
        else:
            results.append(
                RecordResult(
                    row_id=row_id,
                    dni=raw.get("dni", ""),
                    nombre=raw.get("apellidos_nombres", ""),
                    status="INVALID_DATA",
                    reason="; ".join(errors),
                )
            )

    logging.info(
        "Validación de datos: %d válidos, %d con datos inconsistentes",
        len(valid_records), len(results),
    )

    # --- 3. Levantar navegador y procesar cada registro válido ---
    driver = None
    try:
        driver = build_driver(cfg["headless"], cfg["chrome_binary_path"])
        wait = WebDriverWait(driver, cfg["wait_timeout_seconds"])

        for row_id, record in valid_records:
            t0 = time.time()
            try:
                driver.get(cfg["form_url"])
                wait.until(EC.presence_of_element_located((By.XPATH, _label_xpath(LABELS["apellidos_nombres"]))))

                logging.info("Procesando fila %s — %s (DNI %s)", row_id, record["apellidos_nombres"], record["dni"])
                ok, reason = fill_and_submit(
                    driver, wait, record, cfg["post_submit_timeout_seconds"],
                    visual_delay=cfg.get("visual_delay_seconds", 0.0),
                )
                status = "OK" if ok else "FORM_ERROR"
                if not ok:
                    logging.warning("Fila %s (DNI %s) falló: %s", row_id, record["dni"], reason)
                else:
                    logging.info("Fila %s (DNI %s) registrada correctamente", row_id, record["dni"])

                if not cfg["headless"] and cfg.get("pause_between_records_seconds"):
                    time.sleep(cfg["pause_between_records_seconds"])

            except TimeoutException as exc:
                ok, status, reason = False, "FORM_ERROR", f"Timeout esperando un elemento del formulario: {exc.msg}"
                logging.error("Fila %s (DNI %s): %s", row_id, record["dni"], reason)
            except WebDriverException as exc:
                ok, status, reason = False, "FORM_ERROR", f"Error de Selenium/WebDriver: {str(exc)[:300]}"
                logging.error("Fila %s (DNI %s): %s", row_id, record["dni"], reason)
            except Exception as exc:  # nunca detener el lote por un registro
                ok, status, reason = False, "FORM_ERROR", f"Error inesperado: {exc}"
                logging.error(
                    "Fila %s (DNI %s): error inesperado\n%s",
                    row_id, record["dni"], traceback.format_exc(),
                )

            results.append(
                RecordResult(
                    row_id=row_id,
                    dni=record["dni"],
                    nombre=record["apellidos_nombres"],
                    status=status,
                    reason=reason,
                    elapsed_seconds=time.time() - t0,
                )
            )

    finally:
        if driver is not None:
            driver.quit()

    # --- 4. Reporte final ---
    # Reordenar resultados por número de fila para que el reporte sea legible
    results.sort(key=lambda r: int(r.row_id))
    report_path = write_report(results, output_dir)
    print_summary(results)
    logging.info("Reporte CSV generado en: %s", report_path)


if __name__ == "__main__":
    main()

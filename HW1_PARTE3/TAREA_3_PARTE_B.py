import requests
from datetime import datetime, timedelta
import os
import time

# =============================================================
# CONFIGURACIÓN
# =============================================================
BASE_URL = "https://lichess.org/api"

API_TOKEN = os.environ.get("LICHESS_TOKEN", "")

# Modo simulación: si es True, NO se crea ningún torneo real, solo se
# muestra en pantalla qué se habría enviado a la API. Déjalo en True
# hasta que confirmes que el calendario está bien armado.
DRY_RUN = False

# =============================================================
# CALENDARIO SEMANAL DE TORNEOS
# =============================================================
# dia_semana sigue la convención de Python: 0=lunes, 1=martes, ..., 6=domingo
# clock_time: minutos iniciales del reloj | clock_increment: incremento en segundos
# duracion_minutos: cuánto dura el torneo completo | variante: "standard", "chess960", etc.
CALENDARIO_SEMANAL = [
    {
        "nombre":            "Blitz de los Lunes",
        "dia_semana":        0,          # lunes
        "hora":              "18:00",
        "clock_time":        3,
        "clock_increment":   2,
        "duracion_minutos":  60,
        "variante":          "standard",
        "rated":             True,
        "descripcion":       "Torneo blitz semanal abierto a todos los niveles.",
    },
    {
        "nombre":            "Rapid de Miércoles",
        "dia_semana":        2,          # miércoles
        "hora":              "19:30",
        "clock_time":        10,
        "clock_increment":   0,
        "duracion_minutos":  90,
        "variante":          "standard",
        "rated":             True,
        "descripcion":       "Torneo rapid semanal, formato clásico.",
    },
    {
        "nombre":            "Bullet Relámpago Viernes",
        "dia_semana":        4,          # viernes
        "hora":              "20:00",
        "clock_time":        1,
        "clock_increment":   0,
        "duracion_minutos":  30,
        "variante":          "standard",
        "rated":             False,
        "descripcion":       "Torneo bullet casual para cerrar la semana.",
    },
]

#VERIFICACIÓN DE USO DE API KEY:
class LichessAuthClient:
    def __init__(self, token):
        if not token:
            raise ValueError(
                "Falta el token de Lichess. Configura la variable de entorno "
                "LICHESS_TOKEN antes de correr este script."
            )
        self.headers = {
            "User-Agent": "UP-DataScience-TorneosAutomaticos/1.0",
            "Authorization": f"Bearer {token}",
        }
        self.request_count = 0

    def post(self, url, data=None):
        self.request_count += 1
        try:
            return requests.post(url, data=data, headers=self.headers, timeout=15)
        except requests.exceptions.RequestException as e:
            print(f"  [error de conexión] {e}")
            return None


# =============================================================
# CALCULAR LA PRÓXIMA FECHA/HORA DE CADA TORNEO
# =============================================================
def generar_proxima_fecha(dia_semana, hora_str, ahora=None):
    """Dado un día de la semana (0=lunes) y una hora ('HH:MM'), calcula el
    próximo datetime en que ocurre, tomando como referencia 'ahora'."""
    ahora = ahora or datetime.now()
    hora, minuto = map(int, hora_str.split(":"))
    dias_diferencia = (dia_semana - ahora.weekday()) % 7
    fecha_candidata = (ahora + timedelta(days=dias_diferencia)).replace(
        hour=hora, minute=minuto, second=0, microsecond=0
    )
    return fecha_candidata


def construir_torneos_programados(calendario, ahora=None):
    """Convierte el calendario semanal (plantillas) en una lista de torneos
    concretos con su fecha/hora calculada, marcando cuáles ya pasaron."""

    ahora = ahora or datetime.now()
    torneos = []

    for entrada in calendario:
        fecha_inicio = generar_proxima_fecha(entrada["dia_semana"], entrada["hora"], ahora=ahora)
        ya_paso = fecha_inicio <= ahora

        torneos.append({
            **entrada,
            "fecha_inicio": fecha_inicio,
            "ya_paso": ya_paso,
        })

    return torneos


# =============================================================
# PASO 2 — CREAR UN TORNEO EN LA API
# =============================================================
def crear_torneo(client, torneo, dry_run=True):
    """Crea un torneo Arena en Lichess a partir de una entrada del calendario."""
    payload = {
        "name":            torneo["nombre"],
        "clockTime":       torneo["clock_time"],
        "clockIncrement":  torneo["clock_increment"],
        "minutes":         torneo["duracion_minutos"],
        "startDate":       int(torneo["fecha_inicio"].timestamp() * 1000),  # epoch en ms
        "variant":         torneo["variante"],
        "rated":           str(torneo["rated"]).lower(),
        "description":     torneo.get("descripcion", ""),
    }

    print(f"\n--- {torneo['nombre']} ---")
    print(f"  Programado para: {torneo['fecha_inicio'].strftime('%A %d/%m/%Y %H:%M')}")
    print(f"  Modo: {torneo['clock_time']}+{torneo['clock_increment']} | "
          f"Duración: {torneo['duracion_minutos']} min | Variante: {torneo['variante']}")

    if dry_run:
        print("  [DRY-RUN] No se creó ningún torneo real. Payload que se enviaría:")
        for k, v in payload.items():
            print(f"    {k}: {v}")
        return {"nombre": torneo["nombre"], "estado": "simulado", "detalle": payload}

    try:
        response = client.post(f"{BASE_URL}/tournament", data=payload)

        if response is None:
            return {"nombre": torneo["nombre"], "estado": "error", "detalle": "sin conexión"}

        if response.status_code == 200:
            data = response.json()
            url_torneo = f"https://lichess.org/tournament/{data.get('id', '')}"
            print(f" Torneo creado: {url_torneo}")
            return {"nombre": torneo["nombre"], "estado": "creado", "detalle": url_torneo}

        elif response.status_code == 401 or response.status_code == 403:
            print(f" Error de autenticación ({response.status_code}). "
                  f"Revisa que tu token tenga el permiso 'tournament:write'.")
            return {"nombre": torneo["nombre"], "estado": "error",
                     "detalle": f"auth {response.status_code}"}

        elif response.status_code == 429:
            print("  Límite de solicitudes alcanzado (429). Se omite este torneo por ahora.")
            return {"nombre": torneo["nombre"], "estado": "error", "detalle": "rate limit"}

        else:
            print(f"  Error {response.status_code} al crear el torneo: {response.text[:200]}")
            return {"nombre": torneo["nombre"], "estado": "error",
                     "detalle": f"{response.status_code}: {response.text[:200]}"}

    except Exception as e:
        # Cualquier error inesperado se registra pero NO detiene el resto del script
        print(f"  Error inesperado al crear el torneo: {e}")
        return {"nombre": torneo["nombre"], "estado": "error", "detalle": str(e)}


# =============================================================
# EJECUCIÓN PRINCIPAL
# =============================================================
if __name__ == "__main__":
    print(f"Modo: {'DRY-RUN (simulación, no se crea nada real)' if DRY_RUN else 'REAL (se crearán torneos en Lichess)'}")
    print(f"Hora actual de referencia: {datetime.now().strftime('%A %d/%m/%Y %H:%M')}\n")

    torneos_programados = construir_torneos_programados(CALENDARIO_SEMANAL)

    # Filtrar los que ya pasaron
    omitidos = [t for t in torneos_programados if t["ya_paso"]]
    pendientes = [t for t in torneos_programados if not t["ya_paso"]]

    if omitidos:
        print("Torneos OMITIDOS (su hora de inicio ya pasó):")
        for t in omitidos:
            print(f"  - {t['nombre']} (programado para {t['fecha_inicio'].strftime('%A %d/%m %H:%M')})")

    if not pendientes:
        print("\nNo hay torneos pendientes por crear en este ciclo.")
    else:
        client = None
        if not DRY_RUN:
            try:
                client = LichessAuthClient(API_TOKEN)
            except ValueError as e:
                print(f"\n❌ {e}")
                print("No se puede continuar en modo real sin un token válido. "
                      "Cambia DRY_RUN = True para seguir probando sin conexión.")
                raise SystemExit(1)

        resultados = []
        for torneo in pendientes:
            try:
                resultado = crear_torneo(client, torneo, dry_run=DRY_RUN)
                resultados.append(resultado)
            except Exception as e:
                # Red de seguridad extra: aunque crear_torneo ya maneja sus propios
                # errores, esto asegura que un torneo problemático nunca detenga el loop.
                print(f"  ❌ Fallo no controlado con '{torneo['nombre']}': {e}")
                resultados.append({"nombre": torneo["nombre"], "estado": "error", "detalle": str(e)})

            # Pequeña pausa entre solicitudes reales para no saturar la API
            if not DRY_RUN:
                time.sleep(1)

        # --- Resumen final ---
        print("\n" + "=" * 50)
        print("RESUMEN")
        print("=" * 50)
        exitosos = [r for r in resultados if r["estado"] in ("creado", "simulado")]
        fallidos = [r for r in resultados if r["estado"] == "error"]
        print(f"Total procesados: {len(resultados)} | Exitosos: {len(exitosos)} | Fallidos: {len(fallidos)}")
        if fallidos:
            print("Torneos con error:")
            for r in fallidos:
                print(f"  - {r['nombre']}: {r['detalle']}")

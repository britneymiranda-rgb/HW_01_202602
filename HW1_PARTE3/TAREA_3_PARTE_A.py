import requests
import pandas as pd
import matplotlib.pyplot as plt
from datetime import datetime
import json
import os
import time

# =============================================================
# PARTE A — CONFIGURACIÓN Y CONEXIÓN A LA API
# =============================================================
USERNAME   = "thibault"        
MAX_GAMES  = 100               # número configurable de partidas a recuperar
API_TOKEN = os.environ.get("LICHESS_TOKEN", "")   

BASE_URL = "https://lichess.org/api"

# Carpeta donde se guardan todas las salidas (CSV y gráficos)
OUTPUT_DIR = "lichess_stats"
os.makedirs(OUTPUT_DIR, exist_ok=True)


class LichessClient:
    """Wrapper sobre requests que cuenta las solicitudes """

    def __init__(self, token=None):
        self.request_count = 0
        self.headers = {"User-Agent": "UP-DataScience-LichessNotebook/1.0"}
        if token:
            self.headers["Authorization"] = f"Bearer {token}"

    def get(self, url, params=None, extra_headers=None):
        self.request_count += 1
        headers = {**self.headers, **(extra_headers or {})}
        try:
            return requests.get(url, params=params, headers=headers, timeout=15)
        except requests.exceptions.RequestException as e:
            print(f"Error de conexión: {e}")
            return None

    def resumen_requests(self):
        return self.request_count

#VALIDACIÓN DE EXISTENCIA DE USUARIO:
def usuario_existe(client, username):
    url = f"{BASE_URL}/user/{username}"
    response = client.get(url)
    print(f"[debug] URL llamada: {url}")

    if response is None:
        print("No hay conexión con lichess.org desde este entorno (revisa tu red/proxy).")
        return False

    print(f"[debug] Status code: {response.status_code}")

    if response.status_code == 200:
        print("Conectividad OK con la API de Lichess.")
        return True
    if response.status_code == 404:
        print(f"El usuario '{username}' no existe en Lichess "
              f"(revisa que esté bien escrito, en https://lichess.org/@/{username}).")
        return False

    print(f"No se pudo validar el usuario '{username}' (status {response.status_code}): "
          f"{response.text[:200]}")
    return False

# DESCARGA HASTA 'max_games' PARTIDAS COMO LISTA DE DICCIONARIOS:
def fetch_games(client, username, max_games=100):

    if not usuario_existe(client, username):
        return []

    time.sleep(1)  

    url = f"{BASE_URL}/games/user/{username}"
    params = {"max": max_games, "opening": "true", "moves": "false"}
    extra_headers = {"Accept": "application/x-ndjson"}

    intentos, espera_base = 5, 5

    if not API_TOKEN:
        print("[aviso] Estás en modo anónimo. Si sigues viendo 429 por concurrencia, "
              "configura API_TOKEN (variable de entorno LICHESS_TOKEN).")

    for intento in range(1, intentos + 1):
        response = client.get(url, params=params, extra_headers=extra_headers)

        if response is None:
            print("No se pudo conectar con la API de Lichess.")
            return []
        if response.status_code == 200:
            break
        if response.status_code == 429 and intento < intentos:
            retry_after = response.headers.get("Retry-After")
            espera = int(retry_after) + 1 if retry_after else espera_base * (2 ** (intento - 1))
            print(f"[429] Límite de Lichess (intento {intento}/{intentos}). Esperando {espera}s...")
            time.sleep(espera)
            continue
        print(f"Error {response.status_code} al obtener partidas: {response.text[:200]}")
        return []
    else:
        print("Se agotaron los reintentos por límite de concurrencia (429).")
        return []

    partidas = [json.loads(linea) for linea in response.text.strip().split("\n") if linea]
    return partidas


# =============================================================
# PARTE B — TRANSFORMACIÓN A DATAFRAME
# =============================================================
def construir_dataframe(juegos_raw, username):
    """Convierte la lista de partidas (JSON crudo de Lichess) en un DataFrame
    de Pandas con una fila por partida y columnas relevantes para el análisis."""

    filas = []
    username_lower = username.lower()

    for g in juegos_raw:
        players = g.get("players", {})
        white = players.get("white", {})
        black = players.get("black", {})

        white_name = (white.get("user") or {}).get("name", "")
        black_name = (black.get("user") or {}).get("name", "")

        if white_name.lower() == username_lower:
            color = "blancas"
            rating_usuario, rating_rival = white.get("rating"), black.get("rating")
            rival = black_name or "Anónimo/IA"
            rating_diff = white.get("ratingDiff")
        elif black_name.lower() == username_lower:
            color = "negras"
            rating_usuario, rating_rival = black.get("rating"), white.get("rating")
            rival = white_name or "Anónimo/IA"
            rating_diff = black.get("ratingDiff")
        else:
            # el usuario no aparece como jugador (partida corrupta o rara) — se descarta
            continue

        winner = g.get("winner")  # "white", "black", o ausente si fue tablas
        if winner is None:
            resultado = "tablas"
        elif (winner == "white" and color == "blancas") or (winner == "black" and color == "negras"):
            resultado = "victoria"
        else:
            resultado = "derrota"

        fecha = datetime.fromtimestamp(g["createdAt"] / 1000) if g.get("createdAt") else None

        filas.append({
            "id_partida":        g.get("id"),
            "fecha":             fecha,
            "modo_juego":        g.get("speed", g.get("perf", "desconocido")),
            "variante":          g.get("variant", "standard"),
            "clasificada":       g.get("rated", False),
            "color":             color,
            "rival":             rival,
            "rating_usuario":    rating_usuario,
            "rating_rival":      rating_rival,
            "diferencia_rating": rating_diff,
            "resultado":         resultado,
            "estado_final":      g.get("status"),
            "apertura":          (g.get("opening") or {}).get("name", "Desconocida"),
        })

    df = pd.DataFrame(filas)
    if not df.empty:
        df = df.sort_values("fecha").reset_index(drop=True)
    return df


# =============================================================
# PARTE C — ESTADÍSTICAS
# =============================================================
def calcular_estadisticas(df):
    """Calcula tablas de estadísticas sobre resultados, clasificación (rating),
    color y modo de juego. Devuelve un diccionario de DataFrames."""

    stats = {}
    total = len(df)
    conteo_resultados = df["resultado"].value_counts()

    # --- Resultados ---
    stats["resultados"] = conteo_resultados.rename_axis("resultado").reset_index(name="cantidad")
    victorias = conteo_resultados.get("victoria", 0)
    stats["resumen_resultados"] = pd.DataFrame([{
        "total_partidas": total,
        "victorias":      victorias,
        "derrotas":       conteo_resultados.get("derrota", 0),
        "tablas":         conteo_resultados.get("tablas", 0),
        "win_rate_%":     round(100 * victorias / total, 2) if total else 0,
    }])

    # --- Clasificación (rating) ---
    stats["clasificacion"] = (
        df["rating_usuario"].describe()
        .reset_index()
        .rename(columns={"index": "estadistico", "rating_usuario": "valor"})
    )

    # --- Color ---
    stats["por_color"] = (
        df.groupby("color")["resultado"]
        .value_counts(normalize=True)
        .mul(100).round(2)
        .rename("porcentaje")
        .reset_index()
    )

    # --- Modo de juego ---
    stats["por_modo"] = (
        df.groupby("modo_juego")["resultado"]
        .value_counts()
        .rename("cantidad")
        .reset_index()
    )

    return stats


# =============================================================
# PARTE D — VISUALIZACIONES
# =============================================================
def generar_visualizaciones(df, stats, output_dir):

    # 1) Resultados totales (barra)
    fig, ax = plt.subplots(figsize=(6, 4))
    stats["resultados"].plot(kind="bar", x="resultado", y="cantidad", ax=ax, legend=False,
                              color=["#4CAF50", "#F44336", "#9E9E9E"])
    ax.set_title("Resultados totales")
    ax.set_xlabel("")
    ax.set_ylabel("Cantidad de partidas")
    plt.xticks(rotation=0)
    plt.tight_layout()
    fig.savefig(os.path.join(output_dir, "grafico_resultados.png"), dpi=150)
    plt.close(fig)

    # 2) Rating a lo largo del tiempo (línea)
    fig, ax = plt.subplots(figsize=(7, 4))
    df_ordenado = df.dropna(subset=["fecha", "rating_usuario"]).sort_values("fecha")
    ax.plot(df_ordenado["fecha"], df_ordenado["rating_usuario"], marker="o", markersize=3)
    ax.set_title("Evolución del rating")
    ax.set_xlabel("Fecha")
    ax.set_ylabel("Rating")
    plt.xticks(rotation=30, ha="right")
    plt.tight_layout()
    fig.savefig(os.path.join(output_dir, "grafico_rating.png"), dpi=150)
    plt.close(fig)

    # 3) Resultados por color (barras agrupadas)
    tabla_color = stats["por_color"].pivot(index="color", columns="resultado", values="porcentaje").fillna(0)
    fig, ax = plt.subplots(figsize=(6, 4))
    tabla_color.plot(kind="bar", ax=ax)
    ax.set_title("Resultados por color (%)")
    ax.set_xlabel("")
    ax.set_ylabel("Porcentaje")
    plt.xticks(rotation=0)
    plt.tight_layout()
    fig.savefig(os.path.join(output_dir, "grafico_por_color.png"), dpi=150)
    plt.close(fig)

    # 4) Partidas por modo de juego (barras agrupadas)
    tabla_modo = stats["por_modo"].pivot(index="modo_juego", columns="resultado", values="cantidad").fillna(0)
    fig, ax = plt.subplots(figsize=(7, 4))
    tabla_modo.plot(kind="bar", ax=ax)
    ax.set_title("Resultados por modo de juego")
    ax.set_xlabel("")
    ax.set_ylabel("Cantidad de partidas")
    plt.xticks(rotation=0)
    plt.tight_layout()
    fig.savefig(os.path.join(output_dir, "grafico_por_modo.png"), dpi=150)
    plt.close(fig)

    print(f"Gráficos guardados en la carpeta '{output_dir}/'.")


# =============================================================
# PARTE E — EXPORTACIÓN A CSV
# =============================================================
def exportar_csv(df, stats, output_dir):
    """Exporta el DataFrame completo y cada tabla de estadísticas a archivos CSV.
    OJO: Se usó ';' como separador (en vez de ',') porque Excel configurado en español
    espera ese separador."""

    df_export = df.copy()
    df_export.columns = [c.upper() for c in df_export.columns]
    df_export.to_csv(os.path.join(output_dir, "partidas.csv"), index=False,
                      sep=";", encoding="utf-8-sig")

    for nombre, tabla in stats.items():
        tabla_export = tabla.copy()
        tabla_export.columns = [c.upper() for c in tabla_export.columns]
        tabla_export.to_csv(os.path.join(output_dir, f"estadisticas_{nombre}.csv"),
                             index=False, sep=";", encoding="utf-8-sig")

    print(f"CSV exportados en la carpeta '{output_dir}/':")
    print(f"  - partidas.csv")
    for nombre in stats:
        print(f"  - estadisticas_{nombre}.csv")


# =============================================================
# EJECUCIÓN PRINCIPAL
# =============================================================
if __name__ == "__main__":
    client = LichessClient(token=API_TOKEN if API_TOKEN else None)
    print("Token configurado:", "sí" if API_TOKEN else "no (modo anónimo)")

    juegos_raw = fetch_games(client, USERNAME, MAX_GAMES)
    print(f"Partidas descargadas: {len(juegos_raw)}")
    print(f"Total de solicitudes hechas a la API: {client.resumen_requests()}")

    if not juegos_raw:
        print("No hay partidas para analizar — revisa USERNAME antes de continuar.")
    else:
        df = construir_dataframe(juegos_raw, USERNAME)
        print(f"\nDataFrame construido: {df.shape[0]} filas x {df.shape[1]} columnas")
        print(df.head())

        stats = calcular_estadisticas(df)
        print("\n--- Resumen de resultados ---")
        print(stats["resumen_resultados"])

        generar_visualizaciones(df, stats, OUTPUT_DIR)
        exportar_csv(df, stats, OUTPUT_DIR)

        print("\n¡Listo! Revisa la carpeta 'lichess_stats' para los CSV y gráficos generados.")
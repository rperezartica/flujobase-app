"""
Motor de valuación de terreno - Caso Integrador UCEMA
Versión 3 (final): backtest completo.

SERIE DE PRECIO: ZonaProp ESTRENAR (2016-hoy), sin empalme con Remax.
  Remax mide el mercado general/usado — no el segmento a estrenar.
  Se mantiene en Combinadas como referencia adicional pero no entra al rebase.

PROYECCIÓN HACIA ADELANTE: tasas compuestas mensuales configurables
  (equivalentes a Escenarios!J60/J55 en FlujoBase).

VALORES BASE DEL REBASE: dos modos de operación
  - Modo caso (default): PRECIO_VENTA_BASE y COSTO_UNIT_BASE del enunciado
    UCEMA (5.2 y 1.6 miles u$s/m2). El rebase proyecta cómo habrían variado
    esos valores en el tiempo según los índices, sin importar el nivel absoluto
    del índice — solo el ratio índice_mes / índice_ancla importa.
  - Modo mercado: los valores base se derivan de los últimos datos disponibles
    (precio = último ZonaProp ESTRENAR; costo = último Apymeco/CCL).
    Usar get_valores_mercado_actual(df) para obtenerlos y pasarlos a backtest().

VENTANA DE BACKTEST: configurable via fecha_desde / fecha_hasta.
"""

import sys
import numpy as np
import pandas as pd
from pathlib import Path

# Resuelve rutas relativas al directorio del script, no al CWD de quien lo llama
HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from motor_v1_estatico import (
    resolver_terreno_max,
    COSTO_UNIT_BASE,
    PRECIO_VENTA_BASE,
    N_MESES,
    PLAZO_OBRA,
    AVANCE_OBRA,
    PCT_VENDIDO,
)

# ============================================================
# COLUMNAS DE DATOS
# ============================================================
CAC_COL    = "indice_cac_reshape_mensual.Indice_CostoConstruccion"
REMAX_COL  = "Índice Remax.Valor M2 (USD)"
ZP_COL     = "ZonaProp.ESTRENAR"
CCL_COL    = "CCL_Yahoo_Sintetico"

# ============================================================
# PARÁMETROS DE PROYECCIÓN (editables)
# Equivalen a Escenarios!J60 (precio) y J54 (CAC) en FlujoBase
# ============================================================
PARAMS_PROYECCION = {
    "tasa_precio_anual":   0.15,  # +15% anual en USD (precio de venta)
    "tasa_cac_usd_anual":  0.05,  # +5% anual en USD (costo construcción)
}


def cargar_y_preparar_series(path_csv=None):
    """
    Carga Combinadas y prepara las series para el motor.

    Serie de precio: ZonaProp ESTRENAR puro (2016-hoy), sin empalme con Remax.
    Remax mide el mercado general/usado y no es comparable con ESTRENAR.
    Se carga igualmente como columna de referencia adicional en los gráficos.

    CAC_USD: CAC en pesos nominales dolarizado via CCL (solo para calcular
    ratios de rebase — no es un precio interpretable en u$s/m2).
    """
    if path_csv is None:
        path_csv = HERE / "combinadas.csv"
    df = pd.read_csv(path_csv, parse_dates=["Fecha"])
    APY_COL_GLOBAL = "indice_cac_reshape_mensual.Apymeco Proyectado"
    USADO_COL  = "ZonaProp.USADO"
    POZO_COL   = "ZonaProp.POZO"
    df = df[[
        "Fecha", CAC_COL, REMAX_COL, ZP_COL, CCL_COL, APY_COL_GLOBAL, USADO_COL, POZO_COL
    ]].set_index("Fecha").sort_index()
    df = df.rename(columns={APY_COL_GLOBAL: "Apymeco_ARS", USADO_COL: "precio_usado",
                             POZO_COL: "precio_pozo"})

    # Dolarizar CAC (ratio de rebase, no precio real en u$s/m2)
    df["CAC_USD"] = df[CAC_COL] / df[CCL_COL]

    # Serie de precio para el rebase: ZonaProp ESTRENAR puro
    df["precio_usd"] = df[ZP_COL].copy()

    return df


def get_valores_mercado_actual(df):
    """
    Deriva los valores base de precio y costo desde los últimos datos
    disponibles en Combinadas (modo mercado, en contraposición al modo
    caso que usa las premisas fijas del enunciado UCEMA).

    Devuelve un dict con:
      precio_base_miles: último ZonaProp ESTRENAR en miles u$s/m2
      costo_base_miles:  último Apymeco/CCL en miles u$s/m2
      ccl_actual:        último CCL disponible
      fecha_precio:      fecha del último dato de precio
      fecha_costo:       fecha del último dato de costo
    """
    precio_actual = df["precio_usd"].dropna().iloc[-1]          # u$s/m2
    costo_actual  = (df["Apymeco_ARS"] / df["CCL_USD"] if "CCL_USD" in df.columns
                     else df["Apymeco_ARS"] / df[CCL_COL]).dropna().iloc[-1]   # u$s/m2
    ccl_actual    = df[CCL_COL].dropna().iloc[-1]
    return {
        "precio_base_miles": precio_actual / 1000,
        "costo_base_miles":  costo_actual  / 1000,
        "ccl_actual":        ccl_actual,
        "fecha_precio":      df["precio_usd"].dropna().index[-1],
        "fecha_costo":       (df["Apymeco_ARS"] / df[CCL_COL]).dropna().index[-1],
    }


def construir_anclas(df):
    """
    Ancla de cada serie = último valor histórico disponible.
    Para la proyección forward, estas son las semillas de partida.
    """
    cac_usd_anchor   = df["CAC_USD"].dropna().iloc[-1]
    precio_anchor    = df["precio_usd"].dropna().iloc[-1]
    fecha_ultimo_cac = df["CAC_USD"].dropna().index[-1]
    fecha_ultimo_px  = df["precio_usd"].dropna().index[-1]
    return cac_usd_anchor, precio_anchor, fecha_ultimo_cac, fecha_ultimo_px


def extender_con_proyeccion(df, cac_usd_anchor, precio_anchor,
                             fecha_ultimo_cac, fecha_ultimo_px,
                             params=PARAMS_PROYECCION,
                             horizonte_meses=60):
    """
    Extiende las series hacia adelante aplicando tasas compuestas mensuales,
    igual que lo hace la hoja Proyecciones de FlujoBase (fórmulas B3, C3...).
    """
    tasa_px_mensual  = (1 + params["tasa_precio_anual"]) ** (1 / 12) - 1
    tasa_cac_mensual = (1 + params["tasa_cac_usd_anual"]) ** (1 / 12) - 1

    ultima_fecha = df.index.max()
    fechas_futuras = pd.date_range(
        ultima_fecha + pd.DateOffset(months=1),
        periods=horizonte_meses,
        freq="MS"
    )

    filas = []
    cac_prev = cac_usd_anchor
    px_prev  = precio_anchor

    for i, fecha in enumerate(fechas_futuras):
        meses_desde_cac = (fecha.year - fecha_ultimo_cac.year) * 12 + (fecha.month - fecha_ultimo_cac.month)
        meses_desde_px  = (fecha.year - fecha_ultimo_px.year)  * 12 + (fecha.month - fecha_ultimo_px.month)
        filas.append({
            "CAC_USD":    cac_usd_anchor  * (1 + tasa_cac_mensual) ** meses_desde_cac,
            "precio_usd": precio_anchor   * (1 + tasa_px_mensual)  ** meses_desde_px,
        })

    df_futuro = pd.DataFrame(filas, index=fechas_futuras)
    df_extendido = pd.concat([df, df_futuro])
    # Rellenar NaN del historico (ej: jun-2026 donde Remax no publicó aún)
    # con forward-fill para cerrar el hueco entre historico y proyeccion.
    df_extendido["precio_usd"] = df_extendido["precio_usd"].ffill()
    df_extendido["CAC_USD"]    = df_extendido["CAC_USD"].ffill()
    return df_extendido


def trayectoria_mensual(df_ext, start_date, cac_usd_anchor, precio_anchor,
                        precio_base=None, costo_base=None):
    """
    Devuelve (costo_unit_mensual, precio_unit_mensual): arrays de 37 valores
    (mes 0 a 36 del proyecto) con los valores rebasados para ese mes de inicio.

    precio_base / costo_base (miles u$s/m2): valores de referencia del proyecto.
      - Si no se pasan, se usan las premisas del caso UCEMA (5.2 y 1.6).
      - Para modo mercado, pasar get_valores_mercado_actual(df) y extraer
        precio_base_miles y costo_base_miles.
    El rebase aplica el ratio índice_mes / índice_ancla sobre estos valores base,
    de modo que solo la dinámica relativa importa, no el nivel absoluto del índice.
    """
    if precio_base is None:
        precio_base = PRECIO_VENTA_BASE
    if costo_base is None:
        costo_base = COSTO_UNIT_BASE

    fechas_proyecto = pd.date_range(start_date, periods=N_MESES + 1, freq="MS")

    cac_vals    = df_ext.reindex(fechas_proyecto)["CAC_USD"]
    precio_vals = df_ext.reindex(fechas_proyecto)["precio_usd"]

    if cac_vals.isna().any() or precio_vals.isna().any():
        return None  # hueco de datos

    costo_unit_mensual  = costo_base  * (cac_vals.values    / cac_usd_anchor)
    precio_unit_mensual = precio_base * (precio_vals.values / precio_anchor)

    return costo_unit_mensual, precio_unit_mensual


def backtest(
    path_csv=None,
    fecha_desde=None,
    fecha_hasta=None,
    params=None,
    horizonte_proyeccion=60,
    precio_base=None,
    costo_base=None,
    verbose=True,
):
    """
    Corre el backtest para todos los meses de inicio dentro de la ventana.

    Parámetros clave:
    -----------------
    fecha_desde / fecha_hasta: str o Timestamp. Default: toda la cobertura.
    params: dict con tasa_precio_anual y tasa_cac_usd_anual.
            Default: PARAMS_PROYECCION (15% precio, 5% CAC en USD).
    horizonte_proyeccion: meses de proyección forward (default 60).
    precio_base / costo_base (miles u$s/m2): valores de referencia del proyecto.
      - None (default) = premisas fijas del caso UCEMA (5.2 y 1.6).
      - Para modo mercado: pasar get_valores_mercado_actual(df) y extraer
        precio_base_miles y costo_base_miles antes de llamar a backtest().
    """
    if params is None:
        params = PARAMS_PROYECCION

    # --- Cargar y preparar ---
    df = cargar_y_preparar_series(path_csv)
    cac_anchor, precio_anchor, fecha_ult_cac, fecha_ult_px = construir_anclas(df)

    if verbose:
        print(f"Ancla CAC_USD (hoy): {cac_anchor:.4f} miles u$s/m2 equiv.")
        print(f"Ancla precio (hoy):  {precio_anchor:.2f} u$s/m2 (ZonaProp ESTRENAR)")
        print(f"Tasas proyeccion: precio {params['tasa_precio_anual']*100:.1f}%/anno, "
              f"CAC_USD {params['tasa_cac_usd_anual']*100:.1f}%/anno")

    # --- Extender con proyecciones ---
    df_ext = extender_con_proyeccion(
        df, cac_anchor, precio_anchor, fecha_ult_cac, fecha_ult_px,
        params=params, horizonte_meses=horizonte_proyeccion
    )

    # --- Ventana de meses de inicio ---
    fecha_min = df["precio_usd"].dropna().index.min()  # ene-2016 (ZonaProp)
    # El último mes de inicio válido es el que puede terminar su proyecto
    # (36 meses) dentro de la serie extendida menos un margen de seguridad
    fecha_max_inicio = df_ext.index.max() - pd.DateOffset(months=N_MESES)

    fecha_desde = pd.Timestamp(fecha_desde) if fecha_desde else fecha_min
    fecha_hasta = pd.Timestamp(fecha_hasta) if fecha_hasta else df["precio_usd"].dropna().index.max()
    # No extendemos fecha_hasta más allá del último dato histórico por default;
    # si el usuario explícitamente quiere escenarios futuros, puede pasarlos.

    meses_inicio = pd.date_range(fecha_desde, fecha_hasta, freq="MS")

    resultados = []
    for start in meses_inicio:
        trayectorias = trayectoria_mensual(df_ext, start, cac_anchor, precio_anchor,
                                               precio_base=precio_base, costo_base=costo_base)
        if trayectorias is None:
            continue
        costo_unit_mensual, precio_unit_mensual = trayectorias
        try:
            r = resolver_terreno_max(costo_unit_mensual, precio_unit_mensual)
        except RuntimeError:
            continue

        # Clasificar qué porción del proyecto usa datos históricos vs proyectados
        fechas_proy = pd.date_range(start, periods=N_MESES + 1, freq="MS")
        meses_historicos = sum(f <= fecha_ult_px for f in fechas_proy)
        meses_proyectados = N_MESES + 1 - meses_historicos

        resultados.append({
            "mes_inicio": start,
            "terreno_max_usd":           r["terreno"] * 1000,
            "tir_anual":                 r["tir_anual"],
            "rentabilidad_cap":          r["rentabilidad"],
            "margen_bruto_usd":          r["margen_bruto"] * 1000,
            "max_exposicion_cap_usd":    r["max_exposicion"] * 1000,
            # Promedios ponderados: costo por avance de obra, precio por ritmo de ventas
            "costo_unit_promedio_obra":  float((costo_unit_mensual[1:PLAZO_OBRA+1] * AVANCE_OBRA[1:PLAZO_OBRA+1]).sum() / AVANCE_OBRA[1:PLAZO_OBRA+1].sum()),
            "precio_unit_promedio":      float((precio_unit_mensual * PCT_VENDIDO).sum() / PCT_VENDIDO.sum()),
            "meses_historicos":          meses_historicos,
            "meses_proyectados":         meses_proyectados,
            "pct_historico":             meses_historicos / (N_MESES + 1),
        })

    return pd.DataFrame(resultados)


def analisis_sensibilidad(
    path_csv=None,
    escenarios=None,
    fecha_desde=None,
    fecha_hasta=None,
):
    """
    Corre el backtest para múltiples combinaciones de parámetros y devuelve
    todos los resultados concatenados (útil para gráficos de sensibilidad).
    """
    if escenarios is None:
        escenarios = [
            {"nombre": "Base (15% precio, 5% costo)",  "tasa_precio_anual": 0.15, "tasa_cac_usd_anual": 0.05},
            {"nombre": "Optimista (20% precio, 2% costo)", "tasa_precio_anual": 0.20, "tasa_cac_usd_anual": 0.02},
            {"nombre": "Pesimista (5% precio, 10% costo)", "tasa_precio_anual": 0.05, "tasa_cac_usd_anual": 0.10},
        ]

    resultados_todos = []
    for esc in escenarios:
        nombre = esc.pop("nombre", str(esc))
        df_res = backtest(
            path_csv=path_csv,
            fecha_desde=fecha_desde,
            fecha_hasta=fecha_hasta,
            params=esc,
            verbose=False,
        )
        df_res["escenario"] = nombre
        resultados_todos.append(df_res)
        esc["nombre"] = nombre  # restaurar para no mutar el original

    return pd.concat(resultados_todos, ignore_index=True)


# ============================================================
# EJECUCIÓN DIRECTA
# ============================================================

def backtest_naive(path_csv=None, fecha_desde=None, fecha_hasta=None):
    """
    Backtest 'naive': para cada mes de inicio, resuelve la oferta maxima de
    terreno CONGELANDO precio y costo al valor vigente en ese mes de inicio
    durante TODOS los 37 meses del proyecto.

    Esto replica el supuesto implicito del modelo estandar (el que usan los
    profesores): precio y costo se mantienen constantes a lo largo de toda
    la ejecucion del proyecto, pero el nivel de partida cambia segun cuando
    se inicia la obra.

    La diferencia entre esta curva y el backtest dinamico (que usa la
    trayectoria real mes a mes) muestra cuanto distorsiona el supuesto naive
    la valuacion del terreno en cada momento historico.
    """
    df = cargar_y_preparar_series(path_csv)
    cac_anchor, precio_anchor, fecha_ult_cac, fecha_ult_px = construir_anclas(df)
    df_ext = extender_con_proyeccion(
        df, cac_anchor, precio_anchor, fecha_ult_cac, fecha_ult_px,
        params={"tasa_precio_anual": 0.0, "tasa_cac_usd_anual": 0.0},
        horizonte_meses=60,
    )

    fecha_min = df["precio_usd"].dropna().index.min()
    fecha_desde = pd.Timestamp(fecha_desde) if fecha_desde else fecha_min
    fecha_hasta = pd.Timestamp(fecha_hasta) if fecha_hasta else df["precio_usd"].dropna().index.max()
    meses_inicio = pd.date_range(fecha_desde, fecha_hasta, freq="MS")

    resultados = []
    for start in meses_inicio:
        tray = trayectoria_mensual(df_ext, start, cac_anchor, precio_anchor)
        if tray is None:
            continue
        costo_start, precio_start = tray

        # Congelar al valor del mes 0 durante todo el proyecto
        costo_congelado = np.full(N_MESES + 1, costo_start[0])
        precio_congelado = np.full(N_MESES + 1, precio_start[0])

        try:
            r = resolver_terreno_max(costo_congelado, precio_congelado)
        except RuntimeError:
            continue

        resultados.append({
            "mes_inicio":       start,
            "terreno_max_usd":  r["terreno"] * 1000,
            "tir_anual":        r["tir_anual"],
            "rentabilidad_cap": r["rentabilidad"],
            "costo_unit_mes0":  costo_start[0],
            "precio_unit_mes0": precio_start[0],
        })

    return pd.DataFrame(resultados)


def grafico_kde(path_csv=None, output_png=None):
    """
    Gráfico de KDE (kernel density estimation) para las tres variables
    de mercado observadas directamente: precio de venta (u$s/m2 snapshot),
    costo de construccion en dolares (CAC_USD, miles u$s/m2 snapshot) y
    ratio precio/costo. Marca la posicion actual (ultimo dato disponible)
    dentro de cada distribucion historica.
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.ticker as mticker
    import numpy as np
    from scipy.stats import gaussian_kde

    if output_png is None:
        output_png = HERE / "backtest_v3_kde.png"

    df = cargar_y_preparar_series(path_csv)
    cac_anchor, precio_anchor, _, _ = construir_anclas(df)

    # Para DISPLAY usamos Apymeco/CCL como costo real en USD/m2
    # (CAC_USD = index/CCL es correcto para rebase pero no es un precio interpretable)
    df["costo_usd_display"] = df["Apymeco_ARS"] / df[CCL_COL]

    df_hist = df[["precio_usd", "costo_usd_display", "precio_usado"]].dropna().copy()
    df_hist["ratio"]  = df_hist["precio_usd"] / df_hist["costo_usd_display"]
    df_hist["spread"] = (df_hist["precio_usd"] - df_hist["precio_usado"]) / df_hist["precio_usado"] * 100

    precio_hoy  = precio_anchor
    cac_hoy     = float(df["costo_usd_display"].dropna().iloc[-1])
    ratio_hoy   = precio_hoy / cac_hoy
    usado_hoy   = float(df["precio_usado"].dropna().iloc[-1])
    spread_hoy  = (precio_hoy - usado_hoy) / usado_hoy * 100

    AZUL_OSCURO = "#1A2A4A"
    ROJO        = "#C0392B"
    VERDE       = "#27AE60"
    NARANJA     = "#E67E22"
    AZUL_MED    = "#2E86AB"
    GRIS_LINEA  = "#DDDDDD"
    BLANCO      = "#FAFBFD"

    paneles = [
        {
            "serie":      df_hist["precio_usd"].values,
            "hoy":        precio_hoy,
            "xlabel":     "Precio de venta a estrenar (u$s / m2)  -  ZonaProp ESTRENAR / Remax",
            "titulo":     "Precio de venta a estrenar  |  Distribucion historica y posicion actual",
            "color_kde":  AZUL_MED,
            "color_hoy":  ROJO,
            "fmt_x":      lambda x, _: f"u$s {x:,.0f}",
        },
        {
            "serie":      df_hist["precio_usado"].values,
            "hoy":        usado_hoy,
            "xlabel":     "Precio de venta usado (u$s / m2)  -  ZonaProp USADO",
            "titulo":     "Precio de venta usado  |  Distribucion historica y posicion actual",
            "color_kde":  "#5D6D7E",
            "color_hoy":  ROJO,
            "fmt_x":      lambda x, _: f"u$s {x:,.0f}",
        },
        {
            "serie":      df_hist["costo_usd_display"].values,
            "hoy":        cac_hoy,
            "xlabel":     "Costo de construccion (u$s / m2)  -  Apymeco / CCL",
            "titulo":     "Costo de construccion en dolares  |  Distribucion historica y posicion actual",
            "color_kde":  NARANJA,
            "color_hoy":  ROJO,
            "fmt_x":      lambda x, _: f"u$s {x:,.0f}",
        },
        {
            "serie":      df_hist["ratio"].values,
            "hoy":        ratio_hoy,
            "xlabel":     "Ratio precio estrenar / costo construccion",
            "titulo":     "Ratio precio / costo  |  Un ratio alto = mas margen disponible para el terreno",
            "color_kde":  VERDE,
            "color_hoy":  ROJO,
            "fmt_x":      lambda x, _: f"{x:.1f}x",
        },
        {
            "serie":      df_hist["spread"].values,
            "hoy":        spread_hoy,
            "xlabel":     "Spread estrenar vs. usado (%)  =  (Estrenar - Usado) / Usado",
            "titulo":     "Spread a estrenar vs. usado  |  Prima de los desarrollos nuevos sobre el mercado secundario",
            "color_kde":  "#8E44AD",
            "color_hoy":  ROJO,
            "fmt_x":      lambda x, _: f"{x:.0f}%",
        },
    ]

    fig, axes = plt.subplots(5, 1, figsize=(12, 20))
    fig.patch.set_facecolor("#F5F6FA")
    fig.suptitle(
        "Posicion actual en la distribucion historica de variables de mercado\n"
        "Base historica: " + df_hist.index.min().strftime("%b-%Y") +
        " — " + df_hist.index.max().strftime("%b-%Y") +
        f"  ({len(df_hist)} meses)",
        fontsize=11, fontweight="bold", color=AZUL_OSCURO, y=1.01,
    )

    for ax, panel in zip(axes, paneles):
        ax.set_facecolor(BLANCO)

        serie = panel["serie"]
        hoy   = panel["hoy"]
        kde   = gaussian_kde(serie, bw_method="scott")
        x_min = serie.min() - 0.15 * (serie.max() - serie.min())
        x_max = serie.max() + 0.15 * (serie.max() - serie.min())
        x_grid = np.linspace(x_min, x_max, 500)
        y_kde  = kde(x_grid)

        # Curva KDE
        ax.plot(x_grid, y_kde, color=panel["color_kde"], linewidth=2.2, zorder=4)
        ax.fill_between(x_grid, y_kde, alpha=0.15, color=panel["color_kde"], zorder=3)

        # Percentiles 25/50/75 como líneas verticales grises
        for pct, ls in [(25, ":"), (50, "--"), (75, ":")]:
            val = float(np.percentile(serie, pct))
            ax.axvline(val, color="#888888", linewidth=0.9, linestyle=ls, zorder=2)
            ax.text(val, y_kde.max() * 0.05, f" p{pct}", fontsize=7,
                    color="#888888", va="bottom", ha="left")

        # Marcador "hoy"
        y_hoy = float(kde(np.array([hoy]))[0])
        pct_hoy = float((serie < hoy).mean() * 100)
        ax.axvline(hoy, color=panel["color_hoy"], linewidth=2.0, zorder=5,
                   label=f"Hoy  ({pct_hoy:.0f}° percentil)")
        ax.scatter([hoy], [y_hoy], color=panel["color_hoy"], s=70, zorder=6)

        # Sombrear area a la izquierda del valor actual (= percentil acumulado)
        mask = x_grid <= hoy
        ax.fill_between(x_grid[mask], y_kde[mask],
                        alpha=0.25, color=panel["color_hoy"], zorder=3)

        # Etiqueta del valor actual
        ha = "right" if pct_hoy > 60 else "left"
        offset = -8 if pct_hoy > 60 else 8
        ax.annotate(
            f"Hoy: {panel['fmt_x'](hoy, None)}\nPercentil {pct_hoy:.0f}",
            xy=(hoy, y_hoy),
            xytext=(offset, 18), textcoords="offset points",
            ha=ha, fontsize=8.5, color=panel["color_hoy"], fontweight="bold",
            arrowprops=dict(arrowstyle="->", color=panel["color_hoy"], lw=1),
        )

        ax.set_xlabel(panel["xlabel"], fontsize=9, color=AZUL_OSCURO)
        ax.set_ylabel("Densidad", fontsize=9, color=AZUL_OSCURO)
        ax.set_title(panel["titulo"], fontsize=9.5, fontweight="bold",
                     color=AZUL_OSCURO, loc="left")
        ax.legend(fontsize=8.5, loc="upper left", framealpha=0.9,
                  facecolor=BLANCO, edgecolor=GRIS_LINEA)
        ax.grid(alpha=0.3, color=GRIS_LINEA)
        ax.xaxis.set_major_formatter(mticker.FuncFormatter(panel["fmt_x"]))
        ax.yaxis.set_visible(False)

    plt.tight_layout()
    plt.savefig(output_png, dpi=140, bbox_inches="tight")
    plt.close()
    print(f"Grafico KDE guardado: {Path(output_png).name}")



def grafico_trayectorias(path_csv=None, output_png=None):
    """
    Tercer grafico: trayectorias historicas mensuales de precio de venta
    (ZonaProp ESTRENAR y ZonaProp USADO) y costo de construccion en
    dolares (Apymeco / CCL, con meses sin dato proyectados via CAC), desde ene-2016 hasta hoy.
    Panel superior: ambas series en u$s/m2.
    Panel inferior: ratio precio/costo (precio / costo).
    """
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import numpy as np

    if output_png is None:
        output_png = HERE / "backtest_v3_trayectorias.png"

    df = cargar_y_preparar_series(path_csv)
    cac_anchor, precio_anchor, _, _ = construir_anclas(df)

    df["costo_usd"] = df["Apymeco_ARS"] / df[CCL_COL]
    df["ratio"]     = df["precio_usd"] / df["costo_usd"]
    df["spread_pct"] = (df["precio_usd"] - df["precio_usado"]) / df["precio_usado"] * 100

    # Series completas (historico)
    precio = df["precio_usd"].dropna()       # ZonaProp ESTRENAR
    usado  = df["precio_usado"].dropna()     # ZonaProp USADO
    pozo   = df["precio_pozo"].dropna()      # ZonaProp POZO
    costo  = df["costo_usd"].dropna()
    ratio  = df["ratio"].dropna()
    spread = df["spread_pct"].dropna()

    # Spread POZO vs USADO
    df["spread_pozo_usado"] = (df["precio_pozo"] - df["precio_usado"]) / df["precio_usado"] * 100
    spread_poz = df["spread_pozo_usado"].dropna()

    # Remax ajustado por IPC-USA (opcional: se activa cuando CPI_USA este en Combinadas)
    # Para activar: correr ipc_usa_downloader.py y cargar CPI_USA en Combinadas via PowerQuery
    remax_real = None
    if REMAX_COL in df.columns and "CPI_USA" in df.columns:
        df_r = df[[REMAX_COL, "CPI_USA"]].dropna()
        if len(df_r) > 0:
            cpi_ref = df_r["CPI_USA"].iloc[-1]
            df_r["remax_real"] = df_r[REMAX_COL] * (cpi_ref / df_r["CPI_USA"])
            remax_real = df_r["remax_real"]

    # Valores actuales
    precio_hoy = precio_anchor
    usado_hoy  = float(df["precio_usado"].dropna().iloc[-1])
    costo_hoy  = float(df["costo_usd"].dropna().iloc[-1])
    ratio_hoy  = precio_hoy / costo_hoy
    spread_hoy = (precio_hoy - usado_hoy) / usado_hoy * 100
    fecha_hoy  = df.index.max()

    AZUL_OSCURO = "#1A2A4A"
    ROJO        = "#C0392B"
    VERDE       = "#27AE60"
    NARANJA     = "#E67E22"
    AZUL_MED    = "#2E86AB"
    GRIS_LINEA  = "#DDDDDD"
    BLANCO      = "#FAFBFD"

    fig, (ax1, ax2, ax3, ax4) = plt.subplots(4, 1, figsize=(13, 17), sharex=True)
    fig.patch.set_facecolor("#F5F6FA")

    # ---- Panel 1: Precio y costo en u$s/m2 ----
    ax1.set_facecolor(BLANCO)

    ax1.plot(precio.index, precio.values,
             color=AZUL_MED, linewidth=2.2, label="Precio estrenar - ZonaProp ESTRENAR (u$s/m2)")
    ax1.plot(pozo.index, pozo.values,
             color=AZUL_MED, linewidth=1.6, linestyle=(0, (5, 2)),
             label="Precio en pozo - ZonaProp POZO (u$s/m2)")
    ax1.plot(usado.index, usado.values,
             color="#5D6D7E", linewidth=1.8, linestyle="--", label="Precio usado - ZonaProp USADO (u$s/m2)")
    if remax_real is not None:
        ax1.plot(remax_real.index, remax_real.values,
                 color=ROJO, linewidth=1.5, linestyle=(0, (3, 2)), alpha=0.75,
                 label="Remax / UCEMA ajustado por IPC-USA (u$s constantes del ultimo mes)")
    ax1.plot(costo.index, costo.values,
             color=NARANJA, linewidth=2.2, label="Costo construccion - Apymeco / CCL (u$s/m2)")

    ax1.scatter([fecha_hoy], [precio_hoy], color=AZUL_MED, s=55, zorder=5)
    ax1.scatter([df["costo_usd"].dropna().index[-1]], [costo_hoy], color=NARANJA, s=55, zorder=5)

    ax1.annotate(f"Estrenar: u$s {precio_hoy:,.0f}",
                 xy=(fecha_hoy, precio_hoy), xytext=(-90, 14), textcoords="offset points",
                 fontsize=7.5, color=AZUL_MED, fontweight="bold",
                 arrowprops=dict(arrowstyle="->", color=AZUL_MED, lw=0.9))
    ax1.annotate(f"Usado: u$s {usado_hoy:,.0f}",
                 xy=(df["precio_usado"].dropna().index[-1], usado_hoy),
                 xytext=(-90, -18), textcoords="offset points",
                 fontsize=7.5, color="#5D6D7E", fontweight="bold",
                 arrowprops=dict(arrowstyle="->", color="#5D6D7E", lw=0.9))
    ax1.annotate(f"Costo: u$s {costo_hoy:,.0f}",
                 xy=(df["costo_usd"].dropna().index[-1], costo_hoy),
                 xytext=(-90, -32), textcoords="offset points",
                 fontsize=7.5, color=NARANJA, fontweight="bold",
                 arrowprops=dict(arrowstyle="->", color=NARANJA, lw=0.9))

    ax1.set_ylabel("u$s / m2", fontsize=9, color=AZUL_OSCURO)
    ax1.set_title(
        "Precio de venta y costo de construccion en dolares  |  Trayectoria historica\n"
        "ZonaProp ESTRENAR · POZO · USADO  ·  Costo: Apymeco / CCL  ·  Remax-UCEMA ajustado IPC-USA (si disponible)",
        fontsize=10.5, fontweight="bold", color=AZUL_OSCURO, loc="left",
    )
    ax1.legend(fontsize=7.5, loc="upper left", framealpha=0.95, facecolor=BLANCO,
               edgecolor=GRIS_LINEA, ncol=2)
    ax1.grid(alpha=0.3, color=GRIS_LINEA)
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"u$s {y:,.0f}"))

    # ---- Panel 2: Ratio precio estrenar / costo ----
    ax2.set_facecolor(BLANCO)
    ax2.plot(ratio.index, ratio.values, color=VERDE, linewidth=2.2, label="Ratio estrenar / costo")
    ax2.axhline(ratio.mean(), color="#888888", linewidth=1.0, linestyle="--",
                label=f"Promedio historico: {ratio.mean():.1f}x")
    ax2.axhline(ratio_hoy, color=ROJO, linewidth=1.2, linestyle=":",
                label=f"Hoy: {ratio_hoy:.1f}x  (percentil {(ratio.values < ratio_hoy).mean()*100:.0f})")
    ax2.fill_between(ratio.index, ratio.values, ratio.mean(),
                     where=(ratio.values > ratio.mean()), alpha=0.12, color=VERDE,
                     label="Por encima del promedio historico")
    ax2.fill_between(ratio.index, ratio.values, ratio.mean(),
                     where=(ratio.values < ratio.mean()), alpha=0.12, color=NARANJA,
                     label="Por debajo del promedio historico")
    ax2.set_ylabel("Precio estrenar / Costo (veces)", fontsize=9, color=AZUL_OSCURO)
    ax2.set_title("Ratio precio estrenar / costo de construccion  |  Un ratio alto = mayor margen para el terreno",
                  fontsize=9.5, fontweight="bold", color=AZUL_OSCURO, loc="left")
    ax2.legend(fontsize=8, loc="upper right", framealpha=0.95, facecolor=BLANCO, edgecolor=GRIS_LINEA)
    ax2.grid(alpha=0.3, color=GRIS_LINEA)
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.1f}x"))

    # ---- Panel 3: Spread ESTRENAR vs USADO ----
    ax3.set_facecolor(BLANCO)
    ax3.plot(spread.index, spread.values, color="#8E44AD", linewidth=2.2,
             label="Spread ESTRENAR vs. USADO (%)")
    ax3.axhline(spread.mean(), color="#888888", linewidth=1.0, linestyle="--",
                label=f"Promedio historico: {spread.mean():.1f}%")
    ax3.axhline(spread_hoy, color=ROJO, linewidth=1.2, linestyle=":",
                label=f"Hoy: {spread_hoy:.1f}%  (percentil {(spread.values < spread_hoy).mean()*100:.0f})")
    ax3.fill_between(spread.index, spread.values, spread.mean(),
                     where=(spread.values > spread.mean()), alpha=0.12, color="#8E44AD",
                     label="Por encima del promedio historico")
    ax3.fill_between(spread.index, spread.values, spread.mean(),
                     where=(spread.values < spread.mean()), alpha=0.12, color=NARANJA,
                     label="Por debajo del promedio historico")
    ax3.set_ylabel("Spread ESTRENAR - USADO (%)", fontsize=9, color=AZUL_OSCURO)
    ax3.set_title("Prima de ESTRENAR sobre USADO  |  Prima de desarrollos nuevos sobre el mercado secundario",
                  fontsize=9.5, fontweight="bold", color=AZUL_OSCURO, loc="left")
    ax3.legend(fontsize=8, loc="upper left", framealpha=0.95, facecolor=BLANCO, edgecolor=GRIS_LINEA)
    ax3.grid(alpha=0.3, color=GRIS_LINEA)
    ax3.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0f}%"))

    # ---- Panel 4: Spread POZO vs USADO ----
    ax4.set_facecolor(BLANCO)
    spread_poz_hoy = float(spread_poz.iloc[-1]) if len(spread_poz) > 0 else float("nan")
    ax4.plot(spread_poz.index, spread_poz.values, color="#1A7A4A", linewidth=2.2,
             label="Spread POZO vs. USADO (%)")
    ax4.axhline(spread_poz.mean(), color="#888888", linewidth=1.0, linestyle="--",
                label=f"Promedio historico: {spread_poz.mean():.1f}%")
    ax4.axhline(spread_poz_hoy, color=ROJO, linewidth=1.2, linestyle=":",
                label=f"Hoy: {spread_poz_hoy:.1f}%  (percentil {(spread_poz.values < spread_poz_hoy).mean()*100:.0f})")
    ax4.fill_between(spread_poz.index, spread_poz.values, spread_poz.mean(),
                     where=(spread_poz.values > spread_poz.mean()), alpha=0.12, color="#1A7A4A",
                     label="Por encima del promedio historico")
    ax4.fill_between(spread_poz.index, spread_poz.values, spread_poz.mean(),
                     where=(spread_poz.values < spread_poz.mean()), alpha=0.12, color=NARANJA,
                     label="Por debajo del promedio historico")
    ax4.set_ylabel("Spread POZO - USADO (%)", fontsize=9, color=AZUL_OSCURO)
    ax4.set_xlabel("Fecha", fontsize=9, color=AZUL_OSCURO)
    ax4.set_title("Prima de POZO sobre USADO  |  Competitividad de unidades en construccion vs. mercado secundario",
                  fontsize=9.5, fontweight="bold", color=AZUL_OSCURO, loc="left")
    ax4.legend(fontsize=8, loc="upper left", framealpha=0.95, facecolor=BLANCO, edgecolor=GRIS_LINEA)
    ax4.grid(alpha=0.3, color=GRIS_LINEA)
    ax4.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: f"{y:.0f}%"))

    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax1.xaxis.set_major_locator(mdates.YearLocator())
    fig.autofmt_xdate(rotation=0)
    plt.tight_layout()

    plt.savefig(output_png, dpi=140, bbox_inches="tight")
    plt.close()
    print(f"Grafico trayectorias guardado: {Path(output_png).name}")


if __name__ == "__main__":
    print("=" * 60)
    print("BACKTEST V3 — caso UCEMA con empalme ZonaProp + proyección")
    print("=" * 60)

    # --- Backtest base ---
    df_res = backtest(path_csv=None)
    print(f"\nResultados: {len(df_res)} meses evaluados")
    print(f"Ventana: {df_res['mes_inicio'].min().date()} → {df_res['mes_inicio'].max().date()}")
    print(f"\nOferta máxima de terreno (u$s):")
    print(df_res["terreno_max_usd"].describe())
    print(f"\nCaso base hoy (jun-2026): u$s 7,254,454")

    # Meses con proyección parcial (inicio 2022+ tienen 36 meses que se extienden a 2025-2026)
    con_proyeccion = df_res[df_res["meses_proyectados"] > 0]
    print(f"\nMeses con algún mes proyectado en la trayectoria: {len(con_proyeccion)} "
          f"({con_proyeccion['mes_inicio'].min().date()} en adelante)")

    df_res.to_csv(HERE / "backtest_v3_base.csv", index=False)
    print("\nGuardado: backtest_v3_base.csv")

    # --- Backtest naive (precio y costo congelados al mes de inicio) ---
    print("\nCorriendo backtest naive...")
    df_naive = backtest_naive(path_csv=None)
    df_naive.to_csv(HERE / "backtest_v3_naive.csv", index=False)
    print(f"Naive: {len(df_naive)} meses evaluados. Guardado: backtest_v3_naive.csv")

    # --- Análisis de sensibilidad ---
    print("\n" + "=" * 60)
    print("SENSIBILIDAD DE PARÁMETROS")
    print("=" * 60)
    df_sens = analisis_sensibilidad(path_csv=None)
    print(df_sens.groupby("escenario")["terreno_max_usd"].describe())
    df_sens.to_csv(HERE / "backtest_v3_sensibilidad.csv", index=False)
    print("\nGuardado: backtest_v3_sensibilidad.csv")


    # ============================================================
    # DATOS PROYECTADOS (may-2023 → jun-2026) por escenario
    # ============================================================
    ESCENARIOS_GRAF = [
        {"nombre": "Optimista (+20% precio, +2% costo)",  "tasa_precio_anual": 0.20, "tasa_cac_usd_anual": 0.02},
        {"nombre": "Base (+15% precio, +5% costo)",       "tasa_precio_anual": 0.15, "tasa_cac_usd_anual": 0.05},
        {"nombre": "Pesimista (+5% precio, +10% costo)",  "tasa_precio_anual": 0.05, "tasa_cac_usd_anual": 0.10},
        {"nombre": "Estatico (0% precio, 0% costo)",      "tasa_precio_anual": 0.00, "tasa_cac_usd_anual": 0.00},
    ]
    COLORES_ESC = ["#27AE60", "#2E86AB", "#E67E22", "#8E44AD"]

    # Jun-2023 es el primer mes de inicio donde algún mes del proyecto
    # no tiene dato histórico confirmado (el proyecto llegaría a jun-2026,
    # y Remax no publicó ese mes). Desde ahí en adelante se muestran bandas.
    FECHA_EMPALME = pd.Timestamp("2023-06-01")
    FECHA_HOY     = pd.Timestamp("2026-06-01")        # horizonte de proyección

    proyecciones = []
    for esc in ESCENARIOS_GRAF:
        params_esc = {k: v for k, v in esc.items() if k != "nombre"}
        df_proy = backtest(
            path_csv=None,
            fecha_desde=FECHA_EMPALME,   # arranca en el empalme → curva continua
            fecha_hasta=FECHA_HOY,
            params=params_esc,
            verbose=False,
        )
        df_proy["escenario"] = esc["nombre"]
        proyecciones.append(df_proy)

    # ============================================================
    # GRÁFICOS
    # ============================================================
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    import matplotlib.dates as mdates
    import matplotlib.patches as mpatches

    AZUL_OSCURO = "#1A2A4A"
    ROJO        = "#C0392B"
    VERDE       = "#27AE60"
    AZUL_MED    = "#2E86AB"
    NARANJA     = "#E67E22"
    GRIS_LINEA  = "#DDDDDD"
    BLANCO      = "#FAFBFD"
    CASO_HOY_USD = 7_254_454

    periodos = [
        {"label": "Cepo 2016-2019\n(baja devaluacion)",     "ini": "2016-02-01", "fin": "2019-01-01", "color": "#8E44AD"},
        {"label": "Crisis 2018-2019\n(devaluacion fuerte)",  "ini": "2019-01-01", "fin": "2020-03-01", "color": NARANJA},
        {"label": "COVID + ASPO",                            "ini": "2020-03-01", "fin": "2021-01-01", "color": ROJO},
        {"label": "Compresion\ncosto/precio USD",            "ini": "2021-01-01", "fin": "2023-05-01", "color": VERDE},
    ]



    fig, (ax1, ax2, ax3) = plt.subplots(3, 1, figsize=(14, 16), sharex=True)
    fig.patch.set_facecolor("#F5F6FA")
    FONDO = "#F5F6FA"   # un solo tono neutro — la periodizacion queda en suspenso
                        # hasta que implementemos la deteccion de regimen (paso 3-4)

    # ---- Panel 1: Oferta maxima historico + proyeccion ----
    ax1.set_facecolor(BLANCO)
    ax1.axvspan(FECHA_EMPALME, FECHA_HOY + pd.DateOffset(months=1), alpha=0.06, color="#444444", zorder=0)
    ax1.axvline(FECHA_EMPALME, color="#999999", linewidth=0.9, linestyle=":", zorder=3)

    ax1.plot(df_res["mes_inicio"], df_res["terreno_max_usd"] / 1e6,
             color=ROJO, linewidth=2.6, zorder=5, label="Dinamico (precios historicos mes a mes)")

    for df_proy, color, esc in zip(proyecciones, COLORES_ESC, ESCENARIOS_GRAF):
        df_proy = df_proy.sort_values("mes_inicio")
        es_estatico = esc["tasa_precio_anual"] == 0.0
        lw        = 2.3 if es_estatico else 1.7
        linestyle = (0, (6, 2)) if es_estatico else "--"
        zorder    = 6 if es_estatico else 4
        ax1.plot(df_proy["mes_inicio"], df_proy["terreno_max_usd"] / 1e6,
                 color=color, linewidth=lw, linestyle=linestyle, zorder=zorder,
                 label=esc["nombre"])

    for df_proy, esc in zip(proyecciones, ESCENARIOS_GRAF):
        if esc["tasa_precio_anual"] == 0.0:
            row_est = df_proy.sort_values("mes_inicio").iloc[-1]
            val_str = "u$s " + f"{row_est['terreno_max_usd']/1e6:.2f}M"
            ax1.annotate(
                "Caso estatico (0%/0%)\n" + val_str,
                xy=(row_est["mes_inicio"], row_est["terreno_max_usd"] / 1e6),
                xytext=(-100, -30), textcoords="offset points",
                fontsize=7.5, color="#8E44AD",
                arrowprops=dict(arrowstyle="->", color="#8E44AD", lw=1),
            )

    idx_max = df_res["terreno_max_usd"].idxmax()
    idx_min = df_res["terreno_max_usd"].idxmin()
    for idx, ha, ann_color, prefix in [
        (idx_max, "left",  ROJO,        "Max"),
        (idx_min, "right", AZUL_OSCURO, "Min"),
    ]:
        row = df_res.iloc[idx]
        label_txt = (
            prefix + "\n"
            + row["mes_inicio"].strftime("%b-%y") + "\n"
            + "u$s " + f"{row['terreno_max_usd']/1e6:.1f}M"
        )
        ax1.annotate(
            label_txt,
            xy=(row["mes_inicio"], row["terreno_max_usd"] / 1e6),
            xytext=(20 if ha == "left" else -20, 12),
            textcoords="offset points",
            ha=ha, fontsize=7.5, color=ann_color,
            arrowprops=dict(arrowstyle="->", color=ann_color, lw=1),
        )

    ax1.text(FECHA_EMPALME + pd.DateOffset(days=20), ax1.get_ylim()[0],
             "  historico  |  proyeccion", fontsize=7.5, color="#666666", style="italic", va="bottom")
    ax1.set_ylabel("Oferta maxima terreno (mill. u$s)", fontsize=9, color=AZUL_OSCURO)
    ax1.set_title(
        "Oferta maxima de terreno segun mes de inicio  |  Historico y proyeccion\n"
        "Caso UCEMA  -  23.600 m2  -  18 meses obra  -  36 meses ventas  -  TIR min 25% anual",
        fontsize=10.5, fontweight="bold", color=AZUL_OSCURO, loc="left",
    )
    ax1.legend(fontsize=8, loc="upper right", framealpha=0.95,
               facecolor=BLANCO, edgecolor=GRIS_LINEA, ncol=2)
    ax1.grid(alpha=0.3, color=GRIS_LINEA)
    ax1.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: "u$s " + f"{y:.1f}M"))

    # ---- Panel 2: Dinamico vs Naive ----
    # NOTA CONCEPTUAL:
    # - "Dinamico" usa la trayectoria real de precios mes a mes dentro de cada proyecto.
    # - "Naive" congela precio y costo al valor del MES DE INICIO de ese proyecto (ancla movil).
    # - "Estatico 0%/0%" del panel 1 congela en el ancla de JUN-2026 y proyecta a 0%
    #   (ancla fija). Son tres supuestos distintos — por eso las curvas no coinciden.
    ax2.set_facecolor(BLANCO)
    ax2.axvspan(FECHA_EMPALME, FECHA_HOY + pd.DateOffset(months=1), alpha=0.06, color="#444444", zorder=0)
    ax2.axvline(FECHA_EMPALME, color="#999999", linewidth=0.9, linestyle=":", zorder=3)

    ax2.plot(df_res["mes_inicio"], df_res["terreno_max_usd"] / 1e6,
             color=ROJO, linewidth=2.2, zorder=5,
             label="Dinamico (trayectoria historica real)")
    ax2.plot(df_naive["mes_inicio"], df_naive["terreno_max_usd"] / 1e6,
             color=AZUL_OSCURO, linewidth=2.0, linestyle="--", zorder=4,
             label="Naive (precio y costo congelados al mes de inicio - supuesto estandar)")

    df_merged = pd.merge(
        df_res[["mes_inicio","terreno_max_usd"]].rename(columns={"terreno_max_usd":"din"}),
        df_naive[["mes_inicio","terreno_max_usd"]].rename(columns={"terreno_max_usd":"naive"}),
        on="mes_inicio"
    ).sort_values("mes_inicio")

    ax2.fill_between(df_merged["mes_inicio"],
                     df_merged["din"] / 1e6, df_merged["naive"] / 1e6,
                     where=(df_merged["din"] > df_merged["naive"]),
                     alpha=0.13, color=ROJO,
                     label="Dinamico > Naive (naive subvalua el terreno)")
    ax2.fill_between(df_merged["mes_inicio"],
                     df_merged["din"] / 1e6, df_merged["naive"] / 1e6,
                     where=(df_merged["din"] < df_merged["naive"]),
                     alpha=0.13, color=AZUL_OSCURO,
                     label="Naive > Dinamico (naive sobrevalua el terreno)")

    ax2.set_ylabel("Oferta maxima terreno (mill. u$s)", fontsize=9, color=AZUL_OSCURO)
    ax2.set_title(
        "Distorsion del supuesto naive vs. trayectoria historica real\n"
        "Brecha = cuanto sobre/subvalua el modelo estandar el terreno respecto al dinamico",
        fontsize=9.5, fontweight="bold", color=AZUL_OSCURO, loc="left",
    )
    ax2.legend(fontsize=8, loc="upper right", framealpha=0.95, facecolor=BLANCO,
               edgecolor=GRIS_LINEA, ncol=1)
    ax2.grid(alpha=0.3, color=GRIS_LINEA)
    ax2.yaxis.set_major_formatter(plt.FuncFormatter(lambda y, _: "u$s " + f"{y:.1f}M"))

    # ---- Panel 3: Costo y precio ponderados — historico + todos los escenarios ----
    ax3.set_facecolor(BLANCO)
    ax3.axvspan(FECHA_EMPALME, FECHA_HOY + pd.DateOffset(months=1), alpha=0.06, color="#444444", zorder=0)
    ax3.axvline(FECHA_EMPALME, color="#999999", linewidth=0.9, linestyle=":", zorder=3)

    # Historico
    ax3.plot(df_res["mes_inicio"], df_res["costo_unit_promedio_obra"],
             color=ROJO, linewidth=2.2, zorder=5,
             label="Costo ponderado por avance de obra (miles u$s/m2) - historico")
    ax3.plot(df_res["mes_inicio"], df_res["precio_unit_promedio"] / 1000,
             color=VERDE, linewidth=2.2, linestyle="--", zorder=5,
             label="Precio ponderado por ritmo de ventas (miles u$s/m2) - historico")

    # Proyecciones: optimista, base, pesimista (excluir estatico para no saturar)
    estilos_proy = ["--", ":", "-."]
    alphas_proy  = [0.85, 0.75, 0.65]
    for df_proy, color, esc, ls, alpha in zip(proyecciones, COLORES_ESC, ESCENARIOS_GRAF,
                                               estilos_proy, alphas_proy):
        if esc["tasa_precio_anual"] == 0.0:
            continue   # omitir estatico en este panel
        df_p = df_proy.sort_values("mes_inicio")
        nombre_corto = esc["nombre"].split("(")[0].strip()
        ax3.plot(df_p["mes_inicio"], df_p["costo_unit_promedio_obra"],
                 color=ROJO, linewidth=1.5, linestyle=ls, alpha=alpha,
                 label=f"Costo - proy. {nombre_corto}")
        ax3.plot(df_p["mes_inicio"], df_p["precio_unit_promedio"] / 1000,
                 color=VERDE, linewidth=1.5, linestyle=ls, alpha=alpha,
                 label=f"Precio - proy. {nombre_corto}")

    ax3.set_ylabel("miles u$s/m2", fontsize=9, color=AZUL_OSCURO)
    ax3.set_xlabel("Mes de inicio de obra", fontsize=9, color=AZUL_OSCURO)
    ax3.set_title(
        "Costo y precio ponderados por ritmo de ejecucion y ventas  |  Historico y proyecciones",
        fontsize=9.5, fontweight="bold", color=AZUL_OSCURO, loc="left",
    )
    ax3.legend(fontsize=7.5, loc="upper left", framealpha=0.95, facecolor=BLANCO,
               edgecolor=GRIS_LINEA, ncol=2)
    ax3.grid(alpha=0.3, color=GRIS_LINEA)

    ax1.xaxis.set_major_formatter(mdates.DateFormatter("%Y"))
    ax1.xaxis.set_major_locator(mdates.YearLocator())
    fig.autofmt_xdate(rotation=0)
    plt.tight_layout()

    output_png = HERE / "backtest_v3_oferta_terreno.png"
    plt.savefig(output_png, dpi=140, bbox_inches="tight")
    plt.close()
    print(f"\nGrafico guardado: {output_png.name}")

    # --- Grafico KDE ---
    grafico_kde(path_csv=None)

    # --- Grafico trayectorias historicas ---
    grafico_trayectorias(path_csv=None)



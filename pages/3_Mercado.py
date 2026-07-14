"""
Página 3 — Trayectorias históricas de mercado, ratios y distribuciones (KDE).
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from scipy.stats import gaussian_kde
from pathlib import Path
import sys

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils import render_sidebar, ROJO, VERDE, NARANJA, AZUL_MED, VIOLETA, AZUL_OSCURO, GRIS_LINEA
from motor_v3_backtest import cargar_y_preparar_series, construir_anclas, CCL_COL
from backtest_core import compute_backtest

st.set_page_config(page_title="Mercado | FlujoBase", layout="wide")
params = render_sidebar()

st.title("📈 Mercado — Trayectorias Históricas")
st.caption("Datos mensuales desde ene-2016 hasta jun-2026. Sin proyección — solo datos históricos observados.")


# ============================================================
# CARGA DE DATOS
# ============================================================

@st.cache_data(show_spinner="Cargando datos de mercado...")
def load_market_data(
    tc_col="CCL_Yahoo_Sintetico",
    precio_col="ZonaProp.ESTRENAR",
    costo_serie="cac_camarco",
):
    df = cargar_y_preparar_series(
        tc_col=tc_col, precio_col=precio_col, costo_serie=costo_serie
    )
    _, precio_anchor, _, _ = construir_anclas(df)

    # Costo en u$s/m2 (nivel real, no índice). Apymeco es la única serie de costo
    # que viene en $/m2; el ICC INDEC es un índice base nov-2015=100 y no tiene
    # nivel propio. Por eso, con ICC se ancla el nivel al último Apymeco dolarizado
    # y se reconstruye la historia hacia atrás con la dinámica del ICC en dólares
    # (df["CAC_USD"] ya es la serie de costo elegida, dolarizada y con los huecos
    # cubiertos por el motor). Con CAC/Apymeco, el costo es Apymeco/TC directo.
    apymeco_usd = df["Apymeco_ARS"] / df[tc_col]
    if costo_serie == "icc_indec":
        validos = apymeco_usd.notna() & df["CAC_USD"].notna()
        ancla = apymeco_usd[validos].index[-1]
        df["costo_usd"] = apymeco_usd.loc[ancla] * (df["CAC_USD"] / df["CAC_USD"].loc[ancla])
    else:
        df["costo_usd"] = apymeco_usd

    df["ratio"] = df["precio_usd"] / df["costo_usd"]
    # Los spreads comparan segmentos del mercado entre sí, así que se anclan a
    # ESTRENAR y POZO explícitamente y NO a la serie elegida en el sidebar: con
    # precio_col = ZonaProp.USADO, un spread contra "la serie elegida" sería USADO
    # contra sí mismo, idénticamente cero.
    df["spread_est_usado"] = (
        (df["ZonaProp.ESTRENAR"] - df["precio_usado"]) / df["precio_usado"] * 100
    )
    df["spread_pozo_usado"] = (
        (df["precio_pozo"] - df["precio_usado"]) / df["precio_usado"] * 100
    )
    df["margen_unitario"] = df["precio_usd"] - df["costo_usd"]
    df["brecha_ccl_oficial"] = (df[CCL_COL] / df["Oficial_BNA"] - 1) * 100
    return df, precio_anchor


df, precio_anchor = load_market_data(
    tc_col=params["tc_col"],
    precio_col=params["precio_col"],
    costo_serie=params["costo_serie"],
)

# Nombres de las series activas, para rotular los gráficos con lo que realmente
# se está graficando (el sidebar puede cambiar precio, costo y TC).
PRECIO_NOM = params["precio_label"]
COSTO_NOM  = params["costo_label"]
TC_NOM     = params["tc_label"]
COSTO_DESC = f"{COSTO_NOM}, dolarizado a {TC_NOM}"

# Series limpias (histórico, sin NaN)
precio_ser = df["precio_usd"].dropna()
usado_ser = df["precio_usado"].dropna()
pozo_ser = df["precio_pozo"].dropna()
costo_ser = df["costo_usd"].dropna()
ratio_ser = df["ratio"].dropna()
spread_ser = df["spread_est_usado"].dropna()
spread_pz_ser = df["spread_pozo_usado"].dropna()

precio_hoy = float(precio_ser.iloc[-1])
usado_hoy = float(usado_ser.iloc[-1])
pozo_hoy = float(pozo_ser.iloc[-1]) if len(pozo_ser) > 0 else float("nan")
costo_hoy = float(costo_ser.iloc[-1])
ratio_hoy = float(ratio_ser.iloc[-1])
spread_hoy = float(spread_ser.iloc[-1])
spread_pz_hoy = float(spread_pz_ser.iloc[-1]) if len(spread_pz_ser) > 0 else float("nan")


# ============================================================
# HELPER: KDE trace
# ============================================================

def kde_traces(serie, hoy, color_kde, color_hoy, fmt=",.0f", prefix="u$s ", suffix=""):
    """
    Genera las trazas Plotly de un panel KDE.

    Devuelve (traces, pct_hoy, df_curva, marcadores). df_curva es la curva
    evaluada (x, densidad) lista para reconstruir el gráfico fuera de la app —
    Datawrapper no estima densidades, necesita el par x/densidad ya computado.
    """
    arr = serie.dropna().values
    kde = gaussian_kde(arr, bw_method="scott")
    x_min = arr.min() - 0.12 * (arr.max() - arr.min())
    x_max = arr.max() + 0.12 * (arr.max() - arr.min())
    x_grid = np.linspace(x_min, x_max, 400)
    y_kde = kde(x_grid)

    pct_hoy = float((arr < hoy).mean() * 100)
    p25, p50, p75 = np.percentile(arr, [25, 50, 75])
    y_hoy = float(kde(np.array([hoy]))[0])
    hoy_fmt = f"{prefix}{hoy:{fmt}}{suffix}"

    traces = []

    # Curva KDE completa (relleno debajo)
    traces.append(go.Scatter(
        x=x_grid, y=y_kde,
        mode="lines",
        fill="tozeroy",
        fillcolor=f"rgba({int(color_kde[1:3], 16)},{int(color_kde[3:5], 16)},{int(color_kde[5:7], 16)},0.12)",
        line=dict(color=color_kde, width=2.2),
        name="Distribución histórica",
        showlegend=False,
        hoverinfo="skip",
    ))

    # Área acumulada hasta "hoy"
    mask = x_grid <= hoy
    traces.append(go.Scatter(
        x=np.concatenate([x_grid[mask], [x_grid[mask][-1]] if mask.any() else []]),
        y=np.concatenate([y_kde[mask], [0] if mask.any() else []]),
        mode="none",
        fill="tozeroy",
        fillcolor=f"rgba({int(color_hoy[1:3], 16)},{int(color_hoy[3:5], 16)},{int(color_hoy[5:7], 16)},0.20)",
        showlegend=False,
        hoverinfo="skip",
    ))

    # Percentiles
    for pct_val, label, ls in [(p25, "p25", "dot"), (p50, "p50", "dash"), (p75, "p75", "dot")]:
        traces.append(go.Scatter(
            x=[pct_val, pct_val], y=[0, kde(np.array([pct_val]))[0]],
            mode="lines",
            line=dict(color="#999999", width=1, dash=ls),
            name=label,
            showlegend=False,
            hovertemplate=f"{label}: {prefix}{pct_val:{fmt}}{suffix}<extra></extra>",
        ))

    # Marcador "hoy"
    traces.append(go.Scatter(
        x=[hoy], y=[y_hoy],
        mode="markers",
        marker=dict(color=color_hoy, size=10, symbol="circle",
                    line=dict(color="white", width=2)),
        name=f"Hoy: {hoy_fmt} (p{pct_hoy:.0f})",
        showlegend=True,
        hovertemplate=f"Hoy: {hoy_fmt}<br>Percentil {pct_hoy:.0f}<extra></extra>",
    ))

    # Línea vertical "hoy"
    traces.append(go.Scatter(
        x=[hoy, hoy], y=[0, y_hoy],
        mode="lines",
        line=dict(color=color_hoy, width=2, dash="solid"),
        showlegend=False,
        hoverinfo="skip",
    ))

    # Curva exportable. "densidad_hasta_hoy" repite la densidad solo a la
    # izquierda del valor actual: en Datawrapper se grafica como una segunda
    # serie de área y reproduce el sombreado acumulado del panel.
    df_curva = pd.DataFrame({
        "x": x_grid,
        "densidad": y_kde,
        "densidad_hasta_hoy": np.where(x_grid <= hoy, y_kde, np.nan),
    })

    marcadores = {
        "hoy": hoy,
        "percentil_hoy": pct_hoy,
        "p25": p25,
        "p50": p50,
        "p75": p75,
        "n_obs": len(arr),
        "min": float(arr.min()),
        "max": float(arr.max()),
    }

    return traces, pct_hoy, df_curva, marcadores


# ============================================================
# HELPER: KDE de la oferta máxima de terreno (dos muestras)
# ============================================================

# Etiqueta de la variable especial: no sale de una columna de combinadas.csv sino
# del backtest, y se grafica con dos densidades superpuestas en vez de una.
TERRENO_LABEL = "Oferta máxima por el terreno"


def kde_terreno_traces(serie_hist, serie_full, hoy, label_hist, label_full):
    """
    Dos densidades de la oferta máxima de terreno sobre una grilla común:

    - serie_hist: meses de inicio cuyo flujo de 36 meses es 100% observado
      (feb-2016 → may-2023). Distribución puramente empírica.
    - serie_full: todos los meses de inicio hasta hoy (feb-2016 → jun-2026). Los
      últimos completan su flujo con la proyección del escenario base, así que su
      cola derecha depende de las tasas del sidebar, no solo del dato.

    Se excluyen los meses de inicio futuros: no son "lo que se pudo haber hecho".

    Devuelve (traces, df_curva, marcadores) — marcadores es una lista de dos
    filas, una por muestra, para el CSV de anotaciones.
    """
    arr_h = serie_hist.dropna().values
    arr_f = serie_full.dropna().values

    kde_h = gaussian_kde(arr_h, bw_method="scott")
    kde_f = gaussian_kde(arr_f, bw_method="scott")

    lo = min(arr_h.min(), arr_f.min())
    hi = max(arr_h.max(), arr_f.max())
    x_grid = np.linspace(lo - 0.12 * (hi - lo), hi + 0.12 * (hi - lo), 400)
    y_h, y_f = kde_h(x_grid), kde_f(x_grid)

    pct_h = float((arr_h < hoy).mean() * 100)
    pct_f = float((arr_f < hoy).mean() * 100)

    traces = []
    for y, color, nombre in [
        (y_h, AZUL_MED, f"{label_hist} (n={len(arr_h)})"),
        (y_f, NARANJA, f"{label_full} (n={len(arr_f)})"),
    ]:
        traces.append(go.Scatter(
            x=x_grid, y=y,
            mode="lines",
            fill="tozeroy",
            fillcolor=f"rgba({int(color[1:3], 16)},{int(color[3:5], 16)},{int(color[5:7], 16)},0.10)",
            line=dict(color=color, width=2.2),
            name=nombre,
            hovertemplate="u$s %{x:,.0f}<extra></extra>",
        ))

    y_hoy = max(float(kde_h(np.array([hoy]))[0]), float(kde_f(np.array([hoy]))[0]))
    traces.append(go.Scatter(
        x=[hoy, hoy], y=[0, y_hoy],
        mode="lines",
        line=dict(color=ROJO, width=2),
        name=f"Hoy: u$s {hoy:,.0f} (p{pct_h:.0f} hist. / p{pct_f:.0f} hasta hoy)",
        hovertemplate=(
            f"Hoy: u$s {hoy:,.0f}<br>Percentil {pct_h:.0f} ({label_hist})"
            f"<br>Percentil {pct_f:.0f} ({label_full})<extra></extra>"
        ),
    ))

    df_curva = pd.DataFrame({
        "x": x_grid,
        "densidad_historica": y_h,
        "densidad_historica_hasta_hoy": np.where(x_grid <= hoy, y_h, np.nan),
        "densidad_hasta_hoy_incl_proyeccion": y_f,
        "densidad_hasta_hoy_incl_proyeccion_hasta_hoy": np.where(x_grid <= hoy, y_f, np.nan),
    })

    marcadores = [
        {
            "panel": f"{TERRENO_LABEL} — {label_hist}", "unidad": "u$s",
            "hoy": hoy, "percentil_hoy": pct_h,
            "p25": float(np.percentile(arr_h, 25)),
            "p50": float(np.percentile(arr_h, 50)),
            "p75": float(np.percentile(arr_h, 75)),
            "n_obs": len(arr_h), "min": float(arr_h.min()), "max": float(arr_h.max()),
        },
        {
            "panel": f"{TERRENO_LABEL} — {label_full}", "unidad": "u$s",
            "hoy": hoy, "percentil_hoy": pct_f,
            "p25": float(np.percentile(arr_f, 25)),
            "p50": float(np.percentile(arr_f, 50)),
            "p75": float(np.percentile(arr_f, 75)),
            "n_obs": len(arr_f), "min": float(arr_f.min()), "max": float(arr_f.max()),
        },
    ]

    return traces, df_curva, marcadores


# ============================================================
# PANEL 1 — TRAYECTORIAS DE PRECIO Y COSTO
# ============================================================
st.subheader("Trayectorias históricas")

fig_tray = make_subplots(
    rows=4, cols=1,
    shared_xaxes=True,
    vertical_spacing=0.06,
    row_heights=[0.30, 0.23, 0.23, 0.24],
    subplot_titles=[
        f"Precio de venta ({PRECIO_NOM}) y costo de construcción ({COSTO_DESC}) (u$s/m²)",
        f"Ratio {PRECIO_NOM} / costo construcción",
        "Spread ESTRENAR vs. USADO (%)",
        "Spread POZO vs. USADO (%)",
    ],
)

# -- Panel 1: precio y costo --
fig_tray.add_trace(go.Scatter(
    x=precio_ser.index, y=precio_ser.values,
    mode="lines", name=PRECIO_NOM,
    line=dict(color=AZUL_MED, width=2.2),
    hovertemplate="<b>%{x|%b %Y}</b><br>Precio: u$s %{y:,.0f}/m²<extra></extra>",
), row=1, col=1)

fig_tray.add_trace(go.Scatter(
    x=pozo_ser.index, y=pozo_ser.values,
    mode="lines", name="POZO (ZonaProp)",
    line=dict(color=AZUL_MED, width=1.6, dash="dash"),
    hovertemplate="<b>%{x|%b %Y}</b><br>Pozo: u$s %{y:,.0f}/m²<extra></extra>",
), row=1, col=1)

fig_tray.add_trace(go.Scatter(
    x=usado_ser.index, y=usado_ser.values,
    mode="lines", name="USADO (ZonaProp)",
    line=dict(color="#5D6D7E", width=1.8, dash="dot"),
    hovertemplate="<b>%{x|%b %Y}</b><br>Usado: u$s %{y:,.0f}/m²<extra></extra>",
), row=1, col=1)

fig_tray.add_trace(go.Scatter(
    x=costo_ser.index, y=costo_ser.values,
    mode="lines", name=f"Costo ({COSTO_DESC})",
    line=dict(color=NARANJA, width=2.2),
    hovertemplate="<b>%{x|%b %Y}</b><br>Costo: u$s %{y:,.0f}/m²<extra></extra>",
), row=1, col=1)

# Marcadores "hoy"
fig_tray.add_trace(go.Scatter(
    x=[precio_ser.index[-1]], y=[precio_hoy],
    mode="markers+text",
    marker=dict(color=AZUL_MED, size=8),
    text=[f"u$s {precio_hoy:,.0f}"],
    textposition="top right",
    showlegend=False,
), row=1, col=1)
fig_tray.add_trace(go.Scatter(
    x=[costo_ser.index[-1]], y=[costo_hoy],
    mode="markers+text",
    marker=dict(color=NARANJA, size=8),
    text=[f"u$s {costo_hoy:,.0f}"],
    textposition="bottom right",
    showlegend=False,
), row=1, col=1)

# -- Panel 2: ratio --
ratio_mean = float(ratio_ser.mean())

fig_tray.add_trace(go.Scatter(
    x=ratio_ser.index, y=ratio_ser.values,
    mode="lines", name=f"Ratio {PRECIO_NOM}/costo",
    line=dict(color=VERDE, width=2.2),
    fill="tonexty" if False else None,
    hovertemplate="<b>%{x|%b %Y}</b><br>Ratio: %{y:.2f}x<extra></extra>",
), row=2, col=1)

fig_tray.add_hline(y=ratio_mean, line_dash="dash", line_color="#888888", line_width=1,
                   annotation_text=f"Prom: {ratio_mean:.1f}x", annotation_position="right",
                   row=2, col=1)
fig_tray.add_hline(y=ratio_hoy, line_dash="dot", line_color=ROJO, line_width=1.2,
                   annotation_text=f"Hoy: {ratio_hoy:.1f}x (p{(ratio_ser.values < ratio_hoy).mean()*100:.0f})",
                   annotation_position="right", annotation_font_color=ROJO,
                   row=2, col=1)

# Fill above/below mean
mask_above = ratio_ser.values > ratio_mean
mask_below = ratio_ser.values <= ratio_mean
for mask, color_fill in [(mask_above, VERDE), (mask_below, NARANJA)]:
    if mask.any():
        indices = np.where(mask)[0]
        # Simple fill using separate traces
        pass

fig_tray.add_trace(go.Scatter(
    x=ratio_ser.index, y=np.where(ratio_ser.values > ratio_mean, ratio_ser.values, ratio_mean),
    fill="tonexty", fillcolor="rgba(39, 174, 96, 0.12)",
    mode="none", showlegend=False, hoverinfo="skip",
), row=2, col=1)
fig_tray.add_trace(go.Scatter(
    x=ratio_ser.index, y=[ratio_mean] * len(ratio_ser),
    mode="none", showlegend=False, hoverinfo="skip",
), row=2, col=1)
fig_tray.add_trace(go.Scatter(
    x=ratio_ser.index, y=np.where(ratio_ser.values < ratio_mean, ratio_ser.values, ratio_mean),
    fill="tonexty", fillcolor="rgba(230, 126, 34, 0.12)",
    mode="none", showlegend=False, hoverinfo="skip",
), row=2, col=1)
fig_tray.add_trace(go.Scatter(
    x=ratio_ser.index, y=[ratio_mean] * len(ratio_ser),
    mode="none", showlegend=False, hoverinfo="skip",
), row=2, col=1)

# -- Panel 3: spread ESTRENAR vs USADO --
spread_mean = float(spread_ser.mean())

fig_tray.add_trace(go.Scatter(
    x=spread_ser.index, y=spread_ser.values,
    mode="lines", name="Spread ESTRENAR - USADO",
    line=dict(color=VIOLETA, width=2.2),
    hovertemplate="<b>%{x|%b %Y}</b><br>Spread: %{y:.1f}%<extra></extra>",
), row=3, col=1)
fig_tray.add_hline(y=spread_mean, line_dash="dash", line_color="#888888", line_width=1,
                   annotation_text=f"Prom: {spread_mean:.1f}%", annotation_position="right",
                   row=3, col=1)
fig_tray.add_hline(y=spread_hoy, line_dash="dot", line_color=ROJO, line_width=1.2,
                   annotation_text=f"Hoy: {spread_hoy:.1f}% (p{(spread_ser.values < spread_hoy).mean()*100:.0f})",
                   annotation_position="right", annotation_font_color=ROJO,
                   row=3, col=1)

# -- Panel 4: spread POZO vs USADO --
if len(spread_pz_ser) > 0:
    spread_pz_mean = float(spread_pz_ser.mean())
    fig_tray.add_trace(go.Scatter(
        x=spread_pz_ser.index, y=spread_pz_ser.values,
        mode="lines", name="Spread POZO - USADO",
        line=dict(color="#1A7A4A", width=2.2),
        hovertemplate="<b>%{x|%b %Y}</b><br>Spread POZO: %{y:.1f}%<extra></extra>",
    ), row=4, col=1)
    fig_tray.add_hline(y=spread_pz_mean, line_dash="dash", line_color="#888888", line_width=1,
                       annotation_text=f"Prom: {spread_pz_mean:.1f}%", annotation_position="right",
                       row=4, col=1)
    if not np.isnan(spread_pz_hoy):
        fig_tray.add_hline(
            y=spread_pz_hoy, line_dash="dot", line_color=ROJO, line_width=1.2,
            annotation_text=f"Hoy: {spread_pz_hoy:.1f}%",
            annotation_position="right", annotation_font_color=ROJO,
            row=4, col=1,
        )

fig_tray.update_layout(
    plot_bgcolor="white",
    paper_bgcolor="white",
    height=900,
    hovermode="x unified",
    legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="right", x=1),
    margin=dict(t=60, b=40),
)
fig_tray.update_yaxes(tickprefix="u$s ", row=1, col=1)
fig_tray.update_yaxes(ticksuffix="x", row=2, col=1)
fig_tray.update_yaxes(ticksuffix="%", row=3, col=1)
fig_tray.update_yaxes(ticksuffix="%", row=4, col=1)

st.plotly_chart(fig_tray, use_container_width=True)

# ============================================================
# PANEL 2 — KDE (distribuciones históricas)
# ============================================================
st.divider()
st.subheader("Distribuciones históricas (KDE)")

# Catálogo de variables graficables. Cada entrada define de qué columna de df
# sale la serie y cómo se formatea su unidad. "col" puede no existir en df si
# combinadas.csv no trae esa serie: esas opciones se filtran al construir el menú.
CATALOGO_KDE = {
    f"Precio de venta ({PRECIO_NOM})": {
        "col": "precio_usd", "xlabel": "u$s / m²",
        "fmt": ",.0f", "prefix": "u$s ", "suffix": "",
    },
    f"Costo de construcción ({COSTO_DESC})": {
        "col": "costo_usd", "xlabel": "u$s / m²",
        "fmt": ",.0f", "prefix": "u$s ", "suffix": "",
    },
    f"Ratio {PRECIO_NOM} / costo": {
        "col": "ratio", "xlabel": "veces",
        "fmt": ".2f", "prefix": "", "suffix": "x",
    },
    "Spread ESTRENAR vs. USADO": {
        "col": "spread_est_usado", "xlabel": "%",
        "fmt": ".1f", "prefix": "", "suffix": "%",
    },
    "Spread POZO vs. USADO": {
        "col": "spread_pozo_usado", "xlabel": "%",
        "fmt": ".1f", "prefix": "", "suffix": "%",
    },
    f"Margen unitario ({PRECIO_NOM} − costo)": {
        "col": "margen_unitario", "xlabel": "u$s / m²",
        "fmt": ",.0f", "prefix": "u$s ", "suffix": "",
    },
    "ZP ESTRENAR": {
        "col": "ZonaProp.ESTRENAR", "xlabel": "u$s / m²",
        "fmt": ",.0f", "prefix": "u$s ", "suffix": "",
    },
    "ZP POZO": {
        "col": "ZonaProp.POZO", "xlabel": "u$s / m²",
        "fmt": ",.0f", "prefix": "u$s ", "suffix": "",
    },
    "ZP USADO": {
        "col": "ZonaProp.USADO", "xlabel": "u$s / m²",
        "fmt": ",.0f", "prefix": "u$s ", "suffix": "",
    },
    "ZP INDEX CABA": {
        "col": "ZonaProp.INDEX CABA", "xlabel": "u$s / m²",
        "fmt": ",.0f", "prefix": "u$s ", "suffix": "",
    },
    "Remax-UCEMA": {
        "col": "Índice Remax.Valor M2 (USD)", "xlabel": "u$s / m²",
        "fmt": ",.0f", "prefix": "u$s ", "suffix": "",
    },
    f"Tipo de cambio ({TC_NOM})": {
        "col": params["tc_col"], "xlabel": "$ / u$s",
        "fmt": ",.0f", "prefix": "$ ", "suffix": "",
    },
    "Brecha CCL vs. oficial": {
        "col": "brecha_ccl_oficial", "xlabel": "%",
        "fmt": ".1f", "prefix": "", "suffix": "%",
    },
}

DEFAULT_KDE = [
    f"Precio de venta ({PRECIO_NOM})",
    f"Costo de construcción ({COSTO_DESC})",
    f"Ratio {PRECIO_NOM} / costo",
    "Spread ESTRENAR vs. USADO",
]

opciones_kde = [k for k, v in CATALOGO_KDE.items() if v["col"] in df.columns]
opciones_kde.append(TERRENO_LABEL)  # variable especial: sale del backtest, no de una columna

vars_kde = st.multiselect(
    "Variables a graficar (hasta 5)",
    options=opciones_kde,
    default=[v for v in DEFAULT_KDE if v in opciones_kde],
    max_selections=5,
    help="Cada variable elegida se grafica en su propio panel, con su densidad "
         "histórica, el valor de hoy y su percentil. La curva de cada panel se "
         "puede descargar en CSV.",
)

if not vars_kde:
    st.info("Elegí al menos una variable para ver su distribución.")
    st.stop()

# La paleta se cicla entre los paneles; el rojo queda reservado para "hoy".
PALETA_KDE = [AZUL_MED, NARANJA, VERDE, VIOLETA, AZUL_OSCURO]

paneles_kde = []
for i, nombre in enumerate(v for v in vars_kde if v != TERRENO_LABEL):
    meta = CATALOGO_KDE[nombre]
    paneles_kde.append({
        "key": meta["col"], "titulo": nombre, "xlabel": meta["xlabel"],
        "color_kde": PALETA_KDE[i % len(PALETA_KDE)], "color_hoy": ROJO,
        "fmt": meta["fmt"], "prefix": meta["prefix"], "suffix": meta["suffix"],
    })

# Cada serie se limpia por separado (no con un dropna conjunto): las series
# tienen coberturas distintas — Remax arranca en 2020, MEP tiene huecos — y un
# dropna conjunto recortaría todas al tramo común, achicando cada distribución
# a la peor cobertura del grupo.
df_kde = df[[p["key"] for p in paneles_kde]]

filas_marcadores = []
slugs = {}
fmt_por_panel = {}  # título → (prefix, fmt, suffix), para rotular las métricas

for panel in paneles_kde:
    fmt_por_panel[panel["titulo"]] = (panel["prefix"], panel["fmt"], panel["suffix"])
    st.markdown(f"**{panel['titulo']}**")
    serie_k = df_kde[panel["key"]].dropna()
    if len(serie_k) < 5:
        st.warning("Datos insuficientes para estimar la densidad de esta variable.")
        continue

    panel["hoy"] = float(serie_k.iloc[-1])
    # Nombre de archivo estable y sin acentos/espacios para el CSV de cada panel.
    slug = "".join(c if c.isalnum() else "_" for c in panel["titulo"].lower())[:40]
    slugs[panel["key"]] = slug

    traces_k, pct_k, df_curva_k, marc_k = kde_traces(
        serie_k, panel["hoy"],
        panel["color_kde"], panel["color_hoy"],
        fmt=panel["fmt"], prefix=panel["prefix"], suffix=panel["suffix"],
    )
    filas_marcadores.append({"panel": panel["titulo"], "unidad": panel["xlabel"], **marc_k})

    fig_k = go.Figure(data=traces_k)
    fig_k.update_layout(
        xaxis=dict(title=panel["xlabel"]),
        yaxis=dict(title="Densidad", showticklabels=False),
        plot_bgcolor="white",
        paper_bgcolor="white",
        height=220,
        margin=dict(t=20, b=40, l=40, r=20),
        showlegend=True,
        legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="right", x=1),
    )
    st.plotly_chart(fig_k, use_container_width=True)

    st.download_button(
        "⬇️ Descargar curva (CSV)",
        data=df_curva_k.to_csv(index=False, float_format="%.8g").encode("utf-8"),
        file_name=f"kde_{slug}.csv",
        mime="text/csv",
        key=f"dl_kde_{slug}",
        help="Curva de densidad evaluada (x, densidad) para graficar en Datawrapper "
             "como área o línea. La columna densidad_hasta_hoy reproduce el sombreado "
             "a la izquierda del valor actual.",
    )

# ------------------------------------------------------------
# Panel especial: oferta máxima por el terreno (dos muestras)
# ------------------------------------------------------------
if TERRENO_LABEL in vars_kde:
    st.markdown(f"**{TERRENO_LABEL}**")

    df_bt = compute_backtest(
        params["tasa_precio"], params["tasa_costo"],
        params["precio_base"], params["costo_base"], params["tir_objetivo"],
        params["tc_col"], params["costo_serie"], params["precio_col"],
    )

    # "Hoy" = último mes de inicio con dato, es decir el fin del histórico de
    # combinadas. Los meses de inicio posteriores son escenarios futuros y quedan
    # fuera de ambas muestras: no representan decisiones que se pudieron tomar.
    hoy_mes = df.index.max()
    hasta_hoy = df_bt[df_bt["mes_inicio"] <= hoy_mes]
    serie_hist = hasta_hoy.loc[hasta_hoy["pct_historico"] == 1.0, "terreno_max_usd"]
    serie_full = hasta_hoy["terreno_max_usd"]
    fila_hoy = hasta_hoy[hasta_hoy["mes_inicio"] == hoy_mes]

    if len(serie_hist) < 5 or fila_hoy.empty:
        st.warning(
            "No se puede estimar la distribución de la oferta de terreno con los "
            "parámetros actuales (demasiados meses inviables a esta TIR objetivo)."
        )
    else:
        label_hist = "Flujo 100% histórico"
        label_full = "Todos los inicios hasta hoy"
        traces_t, df_curva_t, marc_t = kde_terreno_traces(
            serie_hist, serie_full,
            float(fila_hoy["terreno_max_usd"].iloc[0]),
            label_hist, label_full,
        )
        filas_marcadores.extend(marc_t)
        for m in marc_t:
            fmt_por_panel[m["panel"]] = ("u$s ", ",.0f", "")

        fig_t = go.Figure(data=traces_t)
        fig_t.update_layout(
            xaxis=dict(title="u$s (oferta máxima por el terreno)", tickprefix="u$s "),
            yaxis=dict(title="Densidad", showticklabels=False),
            plot_bgcolor="white",
            paper_bgcolor="white",
            height=260,
            margin=dict(t=20, b=40, l=40, r=20),
            showlegend=True,
            legend=dict(orientation="h", yanchor="top", y=-0.2, xanchor="right", x=1),
        )
        st.plotly_chart(fig_t, use_container_width=True)
        mes_hist_max = hasta_hoy.loc[hasta_hoy["pct_historico"] == 1.0, "mes_inicio"].max()
        st.caption(
            f"**{label_hist}** (n={len(serie_hist)}): meses de inicio cuyo flujo de 36 meses "
            f"cae entero dentro de datos observados, es decir hasta {mes_hist_max:%b-%Y}. "
            f"Distribución puramente empírica. — **{label_full}** (n={len(serie_full)}): todos "
            f"los meses de inicio hasta {hoy_mes:%b-%Y}; los más recientes completan su flujo "
            "con la proyección del escenario base, así que esa curva depende de las tasas del "
            "sidebar y no solo del dato observado. Los meses de inicio futuros quedan excluidos "
            "de ambas muestras."
        )

        st.download_button(
            "⬇️ Descargar curva (CSV)",
            data=df_curva_t.to_csv(index=False, float_format="%.8g").encode("utf-8"),
            file_name="kde_oferta_maxima_terreno.csv",
            mime="text/csv",
            key="dl_kde_terreno",
            help="Las dos densidades sobre una grilla común, cada una con su versión "
                 "acumulada hasta el valor de hoy.",
        )

# ============================================================
# EXPORTACIÓN DE LAS DISTRIBUCIONES
# ============================================================
st.divider()
st.subheader("Exportar distribuciones")
st.caption(
    "Las curvas se calculan con la serie de precio y el tipo de cambio elegidos en el "
    "sidebar, así que los CSV corresponden exactamente a lo que se ve arriba."
)

col_dl1, col_dl2 = st.columns(2)

col_dl1.download_button(
    f"⬇️ Marcadores de los {len(filas_marcadores)} paneles (CSV)",
    data=pd.DataFrame(filas_marcadores).to_csv(index=False, float_format="%.6g").encode("utf-8"),
    file_name="kde_marcadores.csv",
    mime="text/csv",
    help="Valor de hoy, su percentil, cuartiles, mínimo, máximo y número de "
         "observaciones de cada distribución. Sirve para anotar los gráficos.",
)

col_dl2.download_button(
    "⬇️ Observaciones históricas (CSV)",
    data=df_kde.to_csv(float_format="%.6g").encode("utf-8"),
    file_name="series_historicas_mercado.csv",
    mime="text/csv",
    help="Las observaciones mensuales que alimentan las distribuciones elegidas, "
         "con su fecha.",
)

# ============================================================
# MÉTRICAS ACTUALES
# ============================================================
st.divider()
st.subheader("Posición actual en la distribución histórica")

if not filas_marcadores:
    st.stop()

for fila, col in zip(filas_marcadores, st.columns(len(filas_marcadores))):
    prefix, fmt, suffix = fmt_por_panel[fila["panel"]]
    col.metric(
        fila["panel"],
        f"{prefix}{fila['hoy']:{fmt}}{suffix}",
        delta=f"Percentil {fila['percentil_hoy']:.0f}°",
        delta_color="off",
    )

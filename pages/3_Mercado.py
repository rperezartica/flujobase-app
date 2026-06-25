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

st.set_page_config(page_title="Mercado | FlujoBase", layout="wide")
render_sidebar()

st.title("📈 Mercado — Trayectorias Históricas")
st.caption("Datos mensuales desde ene-2016 hasta jun-2026. Sin proyección — solo datos históricos observados.")


# ============================================================
# CARGA DE DATOS
# ============================================================

@st.cache_data(show_spinner="Cargando datos de mercado...")
def load_market_data():
    df = cargar_y_preparar_series()
    _, precio_anchor, _, _ = construir_anclas(df)

    df["costo_usd"] = df["Apymeco_ARS"] / df[CCL_COL]
    df["ratio"] = df["precio_usd"] / df["costo_usd"]
    df["spread_est_usado"] = (
        (df["precio_usd"] - df["precio_usado"]) / df["precio_usado"] * 100
    )
    df["spread_pozo_usado"] = (
        (df["precio_pozo"] - df["precio_usado"]) / df["precio_usado"] * 100
    )
    return df, precio_anchor


df, precio_anchor = load_market_data()

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
    """Genera lista de trazas Plotly para un panel KDE."""
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

    return traces, pct_hoy


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
        "Precio de venta y costo de construcción (u$s/m²)",
        "Ratio precio estrenar / costo construcción",
        "Spread ESTRENAR vs. USADO (%)",
        "Spread POZO vs. USADO (%)",
    ],
)

# -- Panel 1: precio y costo --
fig_tray.add_trace(go.Scatter(
    x=precio_ser.index, y=precio_ser.values,
    mode="lines", name="ESTRENAR (ZonaProp)",
    line=dict(color=AZUL_MED, width=2.2),
    hovertemplate="<b>%{x|%b %Y}</b><br>Estrenar: u$s %{y:,.0f}/m²<extra></extra>",
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
    mode="lines", name="Costo (Apymeco/CCL)",
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
    mode="lines", name="Ratio estrenar/costo",
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

df_kde = pd.DataFrame({
    "precio_usd": df["precio_usd"],
    "costo_usd": df["costo_usd"],
    "ratio": df["ratio"],
    "spread_est_usado": df["spread_est_usado"],
}).dropna()

paneles_kde = [
    {
        "key": "precio_usd", "hoy": precio_hoy,
        "titulo": "Precio de venta a estrenar",
        "xlabel": "u$s / m²",
        "color_kde": AZUL_MED, "color_hoy": ROJO,
        "fmt": ",.0f", "prefix": "u$s ", "suffix": "",
    },
    {
        "key": "costo_usd", "hoy": costo_hoy,
        "titulo": "Costo de construcción (Apymeco / CCL)",
        "xlabel": "u$s / m²",
        "color_kde": NARANJA, "color_hoy": ROJO,
        "fmt": ",.0f", "prefix": "u$s ", "suffix": "",
    },
    {
        "key": "ratio", "hoy": ratio_hoy,
        "titulo": "Ratio precio estrenar / costo",
        "xlabel": "veces",
        "color_kde": VERDE, "color_hoy": ROJO,
        "fmt": ".2f", "prefix": "", "suffix": "x",
    },
    {
        "key": "spread_est_usado", "hoy": spread_hoy,
        "titulo": "Spread ESTRENAR vs. USADO",
        "xlabel": "%",
        "color_kde": VIOLETA, "color_hoy": ROJO,
        "fmt": ".1f", "prefix": "", "suffix": "%",
    },
]

for panel in paneles_kde:
    st.markdown(f"**{panel['titulo']}**")
    serie_k = df_kde[panel["key"]].dropna()
    if len(serie_k) < 5:
        st.warning("Datos insuficientes para KDE.")
        continue

    traces_k, pct_k = kde_traces(
        serie_k, panel["hoy"],
        panel["color_kde"], panel["color_hoy"],
        fmt=panel["fmt"], prefix=panel["prefix"], suffix=panel["suffix"],
    )

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

# ============================================================
# MÉTRICAS ACTUALES
# ============================================================
st.divider()
st.subheader("Posición actual en la distribución histórica")

col1, col2, col3, col4 = st.columns(4)

def pct_label(serie, val):
    arr = serie.dropna().values
    return f"{(arr < val).mean()*100:.0f}°"

col1.metric(
    "Precio estrenar",
    f"u$s {precio_hoy:,.0f}/m²",
    delta=f"Percentil {pct_label(precio_ser, precio_hoy)}",
    delta_color="off",
)
col2.metric(
    "Costo construcción",
    f"u$s {costo_hoy:,.0f}/m²",
    delta=f"Percentil {pct_label(costo_ser, costo_hoy)}",
    delta_color="off",
)
col3.metric(
    "Ratio precio/costo",
    f"{ratio_hoy:.2f}x",
    delta=f"Percentil {pct_label(ratio_ser, ratio_hoy)}",
    delta_color="off",
)
col4.metric(
    "Spread estrenar/usado",
    f"{spread_hoy:.1f}%",
    delta=f"Percentil {pct_label(spread_ser, spread_hoy)}",
    delta_color="off",
)

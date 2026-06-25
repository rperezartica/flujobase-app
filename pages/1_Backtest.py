"""
Página 1 — Backtest histórico + proyección de oferta máxima de terreno.
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from pathlib import Path
import sys

ROOT = Path(__file__).parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from utils import render_sidebar, ROJO, VERDE, NARANJA, AZUL_MED, VIOLETA, AZUL_OSCURO
from motor_v3_backtest import (
    cargar_y_preparar_series,
    construir_anclas,
    extender_con_proyeccion,
    trayectoria_mensual,
)
from motor_v1_estatico import (
    resolver_terreno_max,
    N_MESES,
    PLAZO_OBRA,
    AVANCE_OBRA,
    PCT_VENDIDO,
)

st.set_page_config(page_title="Backtest | FlujoBase", layout="wide")
params = render_sidebar()

st.title("📊 Backtest — Oferta Máxima de Terreno")
st.caption(
    "Motor dinámico: precio y costo se rebotan mes a mes con datos reales. "
    "La zona sombreada usa proyección con las tasas del sidebar."
)


# ============================================================
# CÓMPUTO CACHEADO
# ============================================================

@st.cache_data(show_spinner="Calculando backtest (puede tomar 15-30 seg la primera vez)...")
def compute_backtest(tasa_precio, tasa_costo, precio_base, costo_base, tir_objetivo):
    """Backtest completo 2016 → 2029, con proyección hacia adelante."""
    df_raw = cargar_y_preparar_series()
    cac_anchor, precio_anchor, fecha_ult_cac, fecha_ult_px = construir_anclas(df_raw)

    params_motor = {"tasa_precio_anual": tasa_precio, "tasa_cac_usd_anual": tasa_costo}
    df_ext = extender_con_proyeccion(
        df_raw, cac_anchor, precio_anchor, fecha_ult_cac, fecha_ult_px,
        params=params_motor, horizonte_meses=60,
    )

    fecha_min = df_raw["precio_usd"].dropna().index.min()
    fecha_hasta = pd.Timestamp("2029-06-01")
    meses_inicio = pd.date_range(fecha_min, fecha_hasta, freq="MS")

    rows = []
    for start in meses_inicio:
        tray = trayectoria_mensual(
            df_ext, start, cac_anchor, precio_anchor,
            precio_base=precio_base, costo_base=costo_base,
        )
        if tray is None:
            continue
        costo_m, precio_m = tray
        try:
            r = resolver_terreno_max(costo_m, precio_m, tir_objetivo=tir_objetivo)
        except RuntimeError:
            continue

        fechas_proy = pd.date_range(start, periods=N_MESES + 1, freq="MS")
        meses_hist = sum(f <= fecha_ult_px for f in fechas_proy)
        rows.append({
            "mes_inicio": start,
            "terreno_max_usd": r["terreno"] * 1000,
            "tir_anual": r["tir_anual"],
            "rentabilidad_cap": r["rentabilidad"],
            "margen_bruto_usd": r["margen_bruto"] * 1000,
            "max_exposicion_cap_usd": r["max_exposicion"] * 1000,
            "costo_unit_avg": float(
                (costo_m[1:PLAZO_OBRA + 1] * AVANCE_OBRA[1:PLAZO_OBRA + 1]).sum()
                / AVANCE_OBRA[1:PLAZO_OBRA + 1].sum()
            ),
            "precio_unit_avg": float(
                (precio_m * PCT_VENDIDO).sum() / PCT_VENDIDO.sum()
            ),
            "meses_historicos": meses_hist,
            "meses_proyectados": N_MESES + 1 - meses_hist,
            "pct_historico": meses_hist / (N_MESES + 1),
        })

    return pd.DataFrame(rows)


@st.cache_data(show_spinner=False)
def compute_escenario_fijo(tasa_precio, tasa_costo, precio_base, costo_base, tir_objetivo):
    """Backtest de un escenario fijo — solo la porción proyectada."""
    return compute_backtest(tasa_precio, tasa_costo, precio_base, costo_base, tir_objetivo)


# Escenario del usuario
df_res = compute_backtest(
    params["tasa_precio"], params["tasa_costo"],
    params["precio_base"], params["costo_base"],
    params["tir_objetivo"],
)

if df_res.empty:
    st.error("No hay resultados. Revisá los parámetros del modelo.")
    st.stop()

# Separar histórico vs proyectado
df_hist = df_res[df_res["pct_historico"] == 1.0].copy()
df_proj = df_res[df_res["meses_proyectados"] > 0].copy()
fecha_empalme = df_proj["mes_inicio"].min() if len(df_proj) > 0 else None

# ============================================================
# SELECTOR DE MES
# ============================================================
mes_options = df_res["mes_inicio"].dt.strftime("%b %Y").tolist()
default_val = df_hist["mes_inicio"].iloc[-1].strftime("%b %Y") if len(df_hist) > 0 else mes_options[0]

mes_seleccionado_str = st.select_slider(
    "Mes de inicio seleccionado (para tabla de resumen)",
    options=mes_options,
    value=default_val,
)
mes_sel = pd.Timestamp(mes_seleccionado_str)

# ============================================================
# GRÁFICO PRINCIPAL
# ============================================================
fig = go.Figure()

# Zona de proyección (fondo sombreado)
if fecha_empalme is not None:
    fig.add_vrect(
        x0=fecha_empalme,
        x1=df_res["mes_inicio"].max() + pd.DateOffset(months=1),
        fillcolor="#EEEEEE", opacity=0.5, layer="below", line_width=0,
    )
    fig.add_vline(
        x=fecha_empalme.timestamp() * 1000,
        line_dash="dot", line_color="#AAAAAA", line_width=1.5,
        annotation_text="histórico | proyección",
        annotation_position="top left",
        annotation_font_size=11,
        annotation_font_color="#666666",
    )

# Línea histórica (sólida)
fig.add_trace(go.Scatter(
    x=df_hist["mes_inicio"],
    y=df_hist["terreno_max_usd"] / 1e6,
    mode="lines",
    name="Dinámico histórico",
    line=dict(color=ROJO, width=2.8),
    hovertemplate="<b>%{x|%b %Y}</b><br>Terreno máx: u$s %{y:.2f}M<extra></extra>",
))

# Proyección del escenario del usuario (punteado desde el empalme)
if len(df_proj) > 0:
    anchor = df_hist.iloc[[-1]] if len(df_hist) > 0 else pd.DataFrame()
    df_dashed = (
        pd.concat([anchor, df_proj])
        .drop_duplicates("mes_inicio")
        .sort_values("mes_inicio")
    )
    tp = int(params["tasa_precio"] * 100)
    tc = int(params["tasa_costo"] * 100)
    fig.add_trace(go.Scatter(
        x=df_dashed["mes_inicio"],
        y=df_dashed["terreno_max_usd"] / 1e6,
        mode="lines",
        name=f"Escenario usuario (+{tp}%p / +{tc}%c)",
        line=dict(color=AZUL_MED, width=2.2, dash="dash"),
        hovertemplate="<b>%{x|%b %Y}</b><br>Terreno (proyec.): u$s %{y:.2f}M<extra></extra>",
    ))

# Escenarios de comparación (expandible)
with st.expander("Mostrar escenarios de comparación"):
    show_opt = st.checkbox("Optimista (+20%p / +2%c)", value=True)
    show_pes = st.checkbox("Pesimista (+5%p / +10%c)", value=True)

for show, tp2, tc2, color, name in [
    (show_opt if "show_opt" in dir() else True, 0.20, 0.02, VERDE, "Optimista (+20%p / +2%c)"),
    (show_pes if "show_pes" in dir() else True, 0.05, 0.10, NARANJA, "Pesimista (+5%p / +10%c)"),
]:
    if show:
        df_esc = compute_escenario_fijo(
            tp2, tc2, params["precio_base"], params["costo_base"], params["tir_objetivo"]
        )
        df_esc_proj = df_esc[df_esc["meses_proyectados"] > 0].copy()
        if len(df_esc_proj) > 0:
            anchor2 = df_hist.iloc[[-1]] if len(df_hist) > 0 else pd.DataFrame()
            df_esc_plot = (
                pd.concat([anchor2[["mes_inicio", "terreno_max_usd"]], df_esc_proj[["mes_inicio", "terreno_max_usd"]]])
                .drop_duplicates("mes_inicio")
                .sort_values("mes_inicio")
            )
            fig.add_trace(go.Scatter(
                x=df_esc_plot["mes_inicio"],
                y=df_esc_plot["terreno_max_usd"] / 1e6,
                mode="lines",
                name=name,
                line=dict(color=color, width=1.8, dash="dot"),
                hovertemplate="<b>%{x|%b %Y}</b><br>" + name + ": u$s %{y:.2f}M<extra></extra>",
            ))

# Línea de referencia: caso UCEMA
fig.add_hline(
    y=7.254454,
    line_dash="longdash", line_color="#888888", line_width=1.2,
    annotation_text="Caso UCEMA base: u$s 7.25M",
    annotation_position="bottom right",
    annotation_font_size=10,
    annotation_font_color="#888888",
)

# Marcador del mes seleccionado
row_sel = df_res[df_res["mes_inicio"] == mes_sel]
if len(row_sel) > 0:
    y_sel = row_sel.iloc[0]["terreno_max_usd"] / 1e6
    fig.add_trace(go.Scatter(
        x=[mes_sel],
        y=[y_sel],
        mode="markers",
        name="Mes seleccionado",
        marker=dict(color=AZUL_OSCURO, size=12, symbol="circle",
                    line=dict(color="white", width=2)),
        showlegend=False,
        hovertemplate=f"<b>{mes_seleccionado_str}</b><br>Terreno: u$s {y_sel:.2f}M<extra></extra>",
    ))

fig.update_layout(
    title=dict(
        text="Oferta máxima de terreno por mes de inicio de obra",
        font=dict(size=17, color=AZUL_OSCURO),
    ),
    xaxis=dict(title="Mes de inicio", tickformat="%Y", dtick="M12"),
    yaxis=dict(
        title="Oferta máxima de terreno (mill. u$s)",
        tickprefix="u$s ", ticksuffix="M",
    ),
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    hovermode="x unified",
    plot_bgcolor="white",
    paper_bgcolor="white",
    height=520,
    margin=dict(t=80, b=60),
)

st.plotly_chart(fig, use_container_width=True)

# ============================================================
# TABLA RESUMEN DEL MES SELECCIONADO
# ============================================================
st.subheader(f"Resumen · {mes_seleccionado_str}")

if len(row_sel) > 0:
    r = row_sel.iloc[0]

    col1, col2, col3, col4, col5 = st.columns(5)
    col1.metric("Terreno máximo", f"u$s {r['terreno_max_usd'] / 1e6:.2f}M")
    col2.metric("TIR anual", f"{r['tir_anual'] * 100:.1f}%")
    col3.metric("Rentabilidad s/cap.", f"{r['rentabilidad_cap'] * 100:.1f}%")
    col4.metric("Margen bruto", f"u$s {r['margen_bruto_usd'] / 1e6:.2f}M")
    col5.metric("Máx. exposición cap.", f"u$s {r['max_exposicion_cap_usd'] / 1e6:.2f}M")

    col6, col7 = st.columns(2)
    col6.metric(
        "Precio prom. ponderado (ventas)",
        f"u$s {r['precio_unit_avg'] * 1000:,.0f}/m²",
    )
    col7.metric(
        "Costo prom. ponderado (obra)",
        f"u$s {r['costo_unit_avg'] * 1000:,.0f}/m²",
    )

    # Percentil dentro de la distribución histórica
    hist_valores = df_hist["terreno_max_usd"].values
    if len(hist_valores) > 0 and r["pct_historico"] == 1.0:
        pct_rank = float((hist_valores < r["terreno_max_usd"]).mean() * 100)
        st.info(
            f"📍 **Posición en la distribución histórica:** percentil **{pct_rank:.0f}** "
            f"({int(pct_rank / 100 * len(hist_valores))} de {len(hist_valores)} meses con terreno máximo menor)"
        )
    elif r["pct_historico"] < 1.0:
        pct_hist_disp = r["pct_historico"] * 100
        st.warning(
            f"⚠️ Mes proyectado: **{r['meses_proyectados']} de {N_MESES + 1} meses** del proyecto "
            f"usan datos proyectados ({100 - pct_hist_disp:.0f}% fuera del período histórico)."
        )
else:
    st.info("Seleccioná un mes en el slider para ver el resumen.")

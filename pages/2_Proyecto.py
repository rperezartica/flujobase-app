"""
Página 2 — Flujo de caja mensual del proyecto para un mes de inicio específico.
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
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
    simular_flujo,
    N_MESES,
    PLAZO_OBRA,
    AVANCE_OBRA,
    PCT_VENDIDO,
    SUPERFICIE_TOTAL,
    SUPERFICIE_PROPIA,
    IVA,
    PCT_CREDITO,
    TNM,
    HONOR_PCT,
    GASTOS_VARIOS_PCT,
    GASTOS_COMERC_PCT,
    GASTOS_COMERC_LANZ_PCT,
    GASTOS_NOTARIALES_PCT,
    calcular_boletos,
    calcular_cuotas,
    calcular_entrega,
)

st.set_page_config(page_title="Proyecto | FlujoBase", layout="wide")
params = render_sidebar()

st.title("🏢 Proyecto — Flujo de Caja Mensual")
st.caption("Seleccioná un mes de inicio para ver el flujo de caja completo del proyecto.")


# ============================================================
# SELECTOR DE MES
# ============================================================
@st.cache_data(show_spinner=False)
def get_available_months():
    df_raw = cargar_y_preparar_series()
    fecha_min = df_raw["precio_usd"].dropna().index.min()
    fecha_max = pd.Timestamp("2029-06-01")
    return pd.date_range(fecha_min, fecha_max, freq="MS")


all_months = get_available_months()
month_labels = [d.strftime("%b %Y") for d in all_months]

col_sel, _ = st.columns([1, 2])
with col_sel:
    mes_label = st.selectbox(
        "Mes de inicio de obra",
        options=month_labels,
        index=month_labels.index("Jun 2026") if "Jun 2026" in month_labels else len(month_labels) - 1,
    )
mes_inicio = pd.Timestamp(mes_label)


# ============================================================
# CÓMPUTO CACHEADO
# ============================================================

@st.cache_data(show_spinner="Calculando flujo de caja...")
def compute_flujo(mes_inicio_str, tasa_precio, tasa_costo, precio_base, costo_base, tir_objetivo):
    mes_inicio = pd.Timestamp(mes_inicio_str)
    df_raw = cargar_y_preparar_series()
    cac_anchor, precio_anchor, fecha_ult_cac, fecha_ult_px = construir_anclas(df_raw)

    params_motor = {"tasa_precio_anual": tasa_precio, "tasa_cac_usd_anual": tasa_costo}
    df_ext = extender_con_proyeccion(
        df_raw, cac_anchor, precio_anchor, fecha_ult_cac, fecha_ult_px,
        params=params_motor, horizonte_meses=60,
    )

    tray = trayectoria_mensual(
        df_ext, mes_inicio, cac_anchor, precio_anchor,
        precio_base=precio_base, costo_base=costo_base,
    )
    if tray is None:
        return None, None, None, None

    costo_m, precio_m = tray

    try:
        r_terreno = resolver_terreno_max(costo_m, precio_m, tir_objetivo=tir_objetivo)
    except RuntimeError:
        return None, None, None, None

    terreno = r_terreno["terreno"]
    r_flujo = simular_flujo(terreno, costo_m, precio_m)

    # Cálculo detallado de componentes para el gráfico
    costo_construccion_mes = AVANCE_OBRA * SUPERFICIE_TOTAL * costo_m * (1 + IVA)
    costo_total = costo_construccion_mes.sum()
    monto_venta_cohorte = PCT_VENDIDO * SUPERFICIE_PROPIA * precio_m
    monto_total_ventas = monto_venta_cohorte.sum()

    boletos_mes = calcular_boletos(monto_venta_cohorte)
    cuotas_mes = calcular_cuotas(monto_venta_cohorte)
    entrega_mes, escritura_sola_mes = calcular_entrega(monto_venta_cohorte)
    ingresos_mes = boletos_mes + cuotas_mes + entrega_mes + escritura_sola_mes

    honorarios_mes = np.zeros(37)
    honorarios_mes[0] = costo_total * HONOR_PCT * 0.6
    honorarios_mes[1:19] = costo_total * HONOR_PCT * 0.4 * AVANCE_OBRA[1:19]
    gastos_varios_mes = costo_total * GASTOS_VARIOS_PCT * AVANCE_OBRA
    gastos_comerc_mes = monto_total_ventas * GASTOS_COMERC_PCT * PCT_VENDIDO
    gastos_comerc_mes[1] += monto_total_ventas * GASTOS_COMERC_LANZ_PCT
    gastos_notariales_mes = (escritura_sola_mes / 0.15) * GASTOS_NOTARIALES_PCT

    terreno_mes = np.zeros(37)
    terreno_mes[0] = terreno

    egresos_mes = (
        terreno_mes + costo_construccion_mes + honorarios_mes
        + gastos_comerc_mes + gastos_notariales_mes + gastos_varios_mes
    )

    desembolso_mes = costo_construccion_mes * PCT_CREDITO
    devolucion_mes = np.zeros(37)
    interes_mes = np.zeros(37)
    saldo_credito = 0.0
    cobros_entrega_mes = entrega_mes + escritura_sola_mes
    for m in range(37):
        saldo_disp = saldo_credito + desembolso_mes[m]
        devolucion_mes[m] = min(saldo_disp, cobros_entrega_mes[m])
        saldo_credito = saldo_disp - devolucion_mes[m]
        interes_mes[m] = saldo_credito * TNM

    detalle = {
        "ingresos_mes": ingresos_mes,
        "egresos_mes": egresos_mes,
        "desembolso_credito": desembolso_mes,
        "devolucion_credito": devolucion_mes,
        "interes_mes": interes_mes,
        "costo_construccion_mes": costo_construccion_mes,
        "honorarios_mes": honorarios_mes,
        "gastos_varios_mes": gastos_varios_mes,
        "gastos_comerc_mes": gastos_comerc_mes,
        "gastos_notariales_mes": gastos_notariales_mes,
        "terreno_mes": terreno_mes,
    }

    return r_flujo, terreno, (costo_m, precio_m), detalle


result, terreno, trayectorias, detalle = compute_flujo(
    mes_inicio.strftime("%Y-%m-%d"),
    params["tasa_precio"], params["tasa_costo"],
    params["precio_base"], params["costo_base"],
    params["tir_objetivo"],
)

if result is None:
    st.error(
        "No se pudo calcular el flujo para este mes. "
        "Puede que los datos no cubran el período necesario o que el solver no converja."
    )
    st.stop()

aporte = result["aporte_capital_mensual"]
acumulado = np.cumsum(aporte)

# ============================================================
# KPIs
# ============================================================
st.divider()
st.subheader(f"KPIs · Inicio en {mes_label}")

col1, col2, col3, col4, col5, col6 = st.columns(6)
col1.metric("Terreno máximo", f"u$s {terreno * 1000:,.0f}")
col2.metric("TIR anual", f"{result['tir_anual'] * 100:.2f}%")
col3.metric("Rentabilidad s/cap.", f"{result['rentabilidad'] * 100:.2f}%")
col4.metric("Margen bruto", f"u$s {result['margen_bruto'] / 1e3:.2f}M")
col5.metric("Máx. exposición", f"u$s {result['max_exposicion'] / 1e3:.2f}M")
col6.metric("Total ventas", f"u$s {result['monto_total_ventas'] / 1e3:.2f}M")

# ============================================================
# GRÁFICO DE FLUJO DE CAJA
# ============================================================
st.divider()
meses_labels = [f"M{m}" for m in range(37)]

fig = make_subplots(
    rows=2, cols=1,
    row_heights=[0.55, 0.45],
    shared_xaxes=True,
    vertical_spacing=0.08,
    subplot_titles=[
        "Flujo neto mensual de capital (u$s miles)",
        "Exposición acumulada de capital (u$s miles)",
    ],
)

# Barras: flujo neto mensual
colors_bar = [VERDE if v >= 0 else ROJO for v in aporte]
fig.add_trace(
    go.Bar(
        x=meses_labels,
        y=aporte * 1000,
        name="Flujo neto mensual",
        marker_color=colors_bar,
        hovertemplate="<b>%{x}</b><br>Flujo neto: u$s %{y:,.0f}<extra></extra>",
    ),
    row=1, col=1,
)
fig.add_hline(y=0, line_color="#888888", line_width=1, row=1, col=1)
fig.add_vline(
    x=PLAZO_OBRA - 0.5,
    line_dash="dot", line_color="#888888", line_width=1.2,
    row=1, col=1,
    annotation_text="Entrega obra",
    annotation_position="top right",
    annotation_font_size=10,
)

# Línea: exposición acumulada
fig.add_trace(
    go.Scatter(
        x=meses_labels,
        y=acumulado * 1000,
        name="Exposición acumulada",
        mode="lines+markers",
        line=dict(color=AZUL_OSCURO, width=2.2),
        marker=dict(size=4),
        fill="tozeroy",
        fillcolor="rgba(26, 42, 74, 0.08)",
        hovertemplate="<b>%{x}</b><br>Acumulado: u$s %{y:,.0f}<extra></extra>",
    ),
    row=2, col=1,
)
fig.add_hline(y=0, line_color="#888888", line_width=1, row=2, col=1)

# Marcador de máxima exposición
idx_min = int(np.argmin(acumulado))
fig.add_trace(
    go.Scatter(
        x=[meses_labels[idx_min]],
        y=[acumulado[idx_min] * 1000],
        mode="markers+text",
        marker=dict(color=ROJO, size=10, symbol="triangle-down"),
        text=[f"Máx. exp.<br>u$s {-acumulado[idx_min]*1000:,.0f}"],
        textposition="bottom center",
        showlegend=False,
        hovertemplate=f"Máxima exposición: u$s {-acumulado[idx_min]*1000:,.0f}<extra></extra>",
    ),
    row=2, col=1,
)

fig.update_layout(
    plot_bgcolor="white",
    paper_bgcolor="white",
    height=600,
    showlegend=True,
    legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
    margin=dict(t=80, b=40),
    bargap=0.15,
)
fig.update_yaxes(tickprefix="u$s ", row=1, col=1)
fig.update_yaxes(tickprefix="u$s ", row=2, col=1)
fig.update_xaxes(tickangle=-45, row=2, col=1)

st.plotly_chart(fig, use_container_width=True)

# ============================================================
# TABLA DETALLADA
# ============================================================
with st.expander("Ver tabla mensual detallada"):
    df_tabla = pd.DataFrame({
        "Mes": [f"M{m}" for m in range(37)],
        "Ingresos (u$s)": (detalle["ingresos_mes"] * 1000).round(0).astype(int),
        "Egresos (u$s)": (detalle["egresos_mes"] * 1000).round(0).astype(int),
        "Desemb. crédito (u$s)": (detalle["desembolso_credito"] * 1000).round(0).astype(int),
        "Dev. crédito (u$s)": (detalle["devolucion_credito"] * 1000).round(0).astype(int),
        "Interés (u$s)": (detalle["interes_mes"] * 1000).round(0).astype(int),
        "Flujo neto (u$s)": (aporte * 1000).round(0).astype(int),
        "Acumulado (u$s)": (acumulado * 1000).round(0).astype(int),
    })
    st.dataframe(
        df_tabla.style.format("{:,.0f}", subset=df_tabla.columns[1:]),
        use_container_width=True,
        height=400,
    )

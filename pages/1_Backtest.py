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
# ESCENARIOS DE PROYECCIÓN FUTURA (editables en sidebar-like expander)
# ============================================================
with st.expander("⚙️ Parámetros de escenarios futuros", expanded=False):
    st.caption(
        "Ajustá las tasas anuales para cada escenario. "
        "Los valores por defecto replican el análisis original."
    )
    col_a, col_b, col_c, col_d = st.columns(4)

    with col_a:
        st.markdown("**Optimista**")
        opt_precio = st.slider("Precio %", -20, 40, 20, 1, key="opt_precio")
        opt_costo  = st.slider("Costo %",  -10, 30,  2, 1, key="opt_costo")
    with col_b:
        st.markdown("**Base**")
        base_precio = st.slider("Precio %", -20, 40, 15, 1, key="base_precio")
        base_costo  = st.slider("Costo %",  -10, 30,  5, 1, key="base_costo")
    with col_c:
        st.markdown("**Pesimista**")
        pes_precio = st.slider("Precio %", -20, 40,  5, 1, key="pes_precio")
        pes_costo  = st.slider("Costo %",  -10, 30, 10, 1, key="pes_costo")
    with col_d:
        st.markdown("**Estático**")
        est_precio = st.slider("Precio %", -20, 40,  0, 1, key="est_precio")
        est_costo  = st.slider("Costo %",  -10, 30,  0, 1, key="est_costo")

ESCENARIOS_FIJOS = [
    {
        "nombre": f"Optimista (+{opt_precio}%p / +{opt_costo}%c)",
        "tasa_precio": opt_precio / 100.0,
        "tasa_costo":  opt_costo  / 100.0,
        "color":       VERDE,
    },
    {
        "nombre": f"Base (+{base_precio}%p / +{base_costo}%c)",
        "tasa_precio": base_precio / 100.0,
        "tasa_costo":  base_costo  / 100.0,
        "color":       AZUL_MED,
    },
    {
        "nombre": f"Pesimista (+{pes_precio}%p / +{pes_costo}%c)",
        "tasa_precio": pes_precio / 100.0,
        "tasa_costo":  pes_costo  / 100.0,
        "color":       NARANJA,
    },
    {
        "nombre": f"Estático ({est_precio}%p / {est_costo}%c)",
        "tasa_precio": est_precio / 100.0,
        "tasa_costo":  est_costo  / 100.0,
        "color":       VIOLETA,
    },
]

# ============================================================
# CÓMPUTO CACHEADO
# ============================================================

@st.cache_data(show_spinner="Calculando backtest (puede tomar 15-30 seg la primera vez)...")
def compute_backtest(
    tasa_precio, tasa_costo, precio_base, costo_base, tir_objetivo,
    tc_col, costo_serie, precio_col,
):
    """Backtest completo 2016 → 2029, con proyección hacia adelante."""
    df_raw = cargar_y_preparar_series(
        tc_col=tc_col, costo_serie=costo_serie, precio_col=precio_col
    )
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
        except (RuntimeError, ValueError):
            # Mes inviable: ni con terreno gratis se alcanza la TIR objetivo
            # (brentq no encuentra bracket con cambio de signo). Se omite.
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
def compute_escenario_fijo(
    tasa_precio, tasa_costo, precio_base, costo_base, tir_objetivo,
    tc_col, costo_serie, precio_col,
):
    return compute_backtest(
        tasa_precio, tasa_costo, precio_base, costo_base, tir_objetivo,
        tc_col, costo_serie, precio_col,
    )


@st.cache_data(show_spinner=False)
def compute_hipotetico(
    tasa_precio, tasa_costo, precio_base, costo_base, tir_objetivo,
    tc_col, costo_serie, precio_col,
):
    """
    Escenario hipotético: para cada mes de inicio toma el valor realizado de
    precio y costo en ese mes, y desde ahí proyecta 36 meses a las tasas
    constantes del escenario — sin usar la trayectoria real de los meses
    siguientes.

    Análogo a backtest_naive() pero con crecimiento a tasa constante en lugar
    de congelar los valores (0%/0%).
    """
    df_raw = cargar_y_preparar_series(
        tc_col=tc_col, costo_serie=costo_serie, precio_col=precio_col
    )
    cac_anchor, precio_anchor, fecha_ult_cac, fecha_ult_px = construir_anclas(df_raw)

    # Extender con crecimiento cero: solo para poder leer el valor realizado
    # en meses de inicio muy recientes que caen fuera de la serie histórica pura.
    # El valor en el ancla y posteriores queda congelado (= precio_anchor / cac_anchor).
    df_ext = extender_con_proyeccion(
        df_raw, cac_anchor, precio_anchor, fecha_ult_cac, fecha_ult_px,
        params={"tasa_precio_anual": 0.0, "tasa_cac_usd_anual": 0.0},
        horizonte_meses=60,
    )

    tasa_px_mensual  = (1 + tasa_precio)  ** (1 / 12) - 1
    tasa_cac_mensual = (1 + tasa_costo)   ** (1 / 12) - 1
    meses_idx = np.arange(N_MESES + 1)

    fecha_min = df_raw["precio_usd"].dropna().index.min()
    fecha_hasta = pd.Timestamp("2029-06-01")
    meses_inicio = pd.date_range(fecha_min, fecha_hasta, freq="MS")

    rows = []
    for start in meses_inicio:
        # Leer SOLO el valor realizado en el mes de inicio (índice 0)
        fecha_start = pd.DatetimeIndex([start])
        cac_val = df_ext.reindex(fecha_start)["CAC_USD"]
        px_val  = df_ext.reindex(fecha_start)["precio_usd"]
        if cac_val.isna().any() or px_val.isna().any():
            continue

        # Rebase del mes de inicio (igual que trayectoria_mensual para el mes 0)
        costo_0  = costo_base  * (float(cac_val.iloc[0]) / cac_anchor)
        precio_0 = precio_base * (float(px_val.iloc[0])  / precio_anchor)

        # Proyectar a tasas constantes del escenario para los 37 meses del proyecto
        costo_m  = costo_0  * (1 + tasa_cac_mensual) ** meses_idx
        precio_m = precio_0 * (1 + tasa_px_mensual)  ** meses_idx

        try:
            r = resolver_terreno_max(costo_m, precio_m, tir_objetivo=tir_objetivo)
        except (RuntimeError, ValueError):
            # Mes inviable: ni con terreno gratis se alcanza la TIR objetivo
            # (brentq no encuentra bracket con cambio de signo). Se omite.
            continue
        rows.append({
            "mes_inicio": start,
            "terreno_max_usd": r["terreno"] * 1000,
        })

    return pd.DataFrame(rows)


# --- Escenario del usuario (parámetros del sidebar) ---
df_res = compute_backtest(
    params["tasa_precio"], params["tasa_costo"],
    params["precio_base"], params["costo_base"],
    params["tir_objetivo"],
    params["tc_col"], params["costo_serie"], params["precio_col"],
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

# ============================================================
# ESCENARIOS DE COMPARACIÓN (fijos)
# ============================================================
with st.expander("Mostrar escenarios de proyección"):
    show_flags = {}
    cols_esc = st.columns(len(ESCENARIOS_FIJOS))
    for i, esc in enumerate(ESCENARIOS_FIJOS):
        show_flags[esc["nombre"]] = cols_esc[i].checkbox(
            esc["nombre"], value=(i < 2), key=f"show_esc_{i}"
        )

for esc in ESCENARIOS_FIJOS:
    if not show_flags.get(esc["nombre"], False):
        continue
    df_esc = compute_escenario_fijo(
        esc["tasa_precio"], esc["tasa_costo"],
        params["precio_base"], params["costo_base"],
        params["tir_objetivo"],
        params["tc_col"], params["costo_serie"], params["precio_col"],
    )
    df_esc_proj = df_esc[df_esc["meses_proyectados"] > 0].copy()
    if len(df_esc_proj) > 0:
        anchor2 = df_hist.iloc[[-1]] if len(df_hist) > 0 else pd.DataFrame()
        df_esc_plot = (
            pd.concat([anchor2[["mes_inicio", "terreno_max_usd"]],
                       df_esc_proj[["mes_inicio", "terreno_max_usd"]]])
            .drop_duplicates("mes_inicio")
            .sort_values("mes_inicio")
        )
        fig.add_trace(go.Scatter(
            x=df_esc_plot["mes_inicio"],
            y=df_esc_plot["terreno_max_usd"] / 1e6,
            mode="lines",
            name=esc["nombre"],
            line=dict(color=esc["color"], width=1.8, dash="dot"),
            hovertemplate="<b>%{x|%b %Y}</b><br>" + esc["nombre"] + ": u$s %{y:.2f}M<extra></extra>",
        ))

# ============================================================
# ESCENARIOS HIPOTÉTICOS (sección 4)
# ============================================================
HIPOT_COLORES = ["#E74C3C", "#3498DB", "#2ECC71"]

with st.expander("➕ Agregar escenarios hipotéticos"):
    st.caption(
        "Cada escenario aplica tasas constantes a **todo** el período histórico + proyectado. "
        "Permite preguntar: '¿qué hubiera valido el terreno si siempre se asumiera X% de crecimiento?'"
    )
    hipot_configs = []
    h_cols = st.columns(3)
    for i in range(3):
        with h_cols[i]:
            activo = st.checkbox(f"Activar escenario {i + 1}", key=f"hip_activo_{i}")
            if activo:
                nombre = st.text_input(
                    "Nombre", value=f"Hipotético {i + 1}", key=f"hip_nombre_{i}"
                )
                hp = st.slider("Precio %", -10, 40, 10, 1, key=f"hip_precio_{i}")
                hc = st.slider("Costo %",  -10, 40,  5, 1, key=f"hip_costo_{i}")
                hipot_configs.append({
                    "nombre": nombre,
                    "tasa_precio": hp / 100.0,
                    "tasa_costo":  hc / 100.0,
                    "color":       HIPOT_COLORES[i],
                })

for hcfg in hipot_configs:
    df_hip = compute_hipotetico(
        hcfg["tasa_precio"], hcfg["tasa_costo"],
        params["precio_base"], params["costo_base"],
        params["tir_objetivo"],
        params["tc_col"], params["costo_serie"], params["precio_col"],
    )
    if not df_hip.empty:
        fig.add_trace(go.Scatter(
            x=df_hip["mes_inicio"],
            y=df_hip["terreno_max_usd"] / 1e6,
            mode="lines",
            name=hcfg["nombre"],
            line=dict(color=hcfg["color"], width=1.4, dash="dot"),
            opacity=0.5,
            hovertemplate=(
                "<b>%{x|%b %Y}</b><br>"
                + hcfg["nombre"] + ": u$s %{y:.2f}M<extra></extra>"
            ),
        ))

# Línea de referencia: caso UCEMA (planilla profesor "sin permuta", TIR 25,02%)
fig.add_hline(
    y=7.128890,
    line_dash="longdash", line_color="#888888", line_width=1.2,
    annotation_text="Caso UCEMA base: u$s 7.13M",
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
# EXPORTAR DATOS DEL GRÁFICO (CSV para Datawrapper)
# ============================================================
st.subheader("⬇️ Exportar datos del gráfico")
st.caption(
    "Formato ancho (una columna por serie, valores en **millones de u$s**), listo "
    "para importar en Datawrapper. Incluye la serie histórica y **todos** los "
    "escenarios de proyección, estén o no visibles en el gráfico."
)


def _serie_export(df, col="terreno_max_usd"):
    """Serie indexada por mes de inicio, en millones de u$s."""
    return pd.Series(
        (df[col] / 1e6).values,
        index=pd.to_datetime(df["mes_inicio"].values),
    )


export_series = {}

# 1. Serie histórica (dinámico)
if len(df_hist) > 0:
    export_series["Dinámico histórico"] = _serie_export(df_hist)

# 2. Escenario del usuario (proyección + punto de empalme)
if len(df_proj) > 0:
    tp = int(params["tasa_precio"] * 100)
    tc = int(params["tasa_costo"] * 100)
    export_series[f"Escenario usuario (+{tp}%p / +{tc}%c)"] = _serie_export(df_dashed)

# 3. Los 4 escenarios fijos (SIEMPRE, estén tildados o no) — proyección + empalme
anchor_exp = df_hist.iloc[[-1]] if len(df_hist) > 0 else pd.DataFrame()
for esc in ESCENARIOS_FIJOS:
    df_esc = compute_escenario_fijo(
        esc["tasa_precio"], esc["tasa_costo"],
        params["precio_base"], params["costo_base"],
        params["tir_objetivo"],
        params["tc_col"], params["costo_serie"], params["precio_col"],
    )
    df_esc_proj = df_esc[df_esc["meses_proyectados"] > 0].copy()
    if len(df_esc_proj) > 0:
        df_esc_plot = (
            pd.concat([anchor_exp[["mes_inicio", "terreno_max_usd"]],
                       df_esc_proj[["mes_inicio", "terreno_max_usd"]]])
            .drop_duplicates("mes_inicio")
            .sort_values("mes_inicio")
        )
        export_series[esc["nombre"]] = _serie_export(df_esc_plot)

# 4. Escenarios hipotéticos activados (cubren todo el período)
for hcfg in hipot_configs:
    df_hip = compute_hipotetico(
        hcfg["tasa_precio"], hcfg["tasa_costo"],
        params["precio_base"], params["costo_base"],
        params["tir_objetivo"],
        params["tc_col"], params["costo_serie"], params["precio_col"],
    )
    if not df_hip.empty:
        export_series[hcfg["nombre"]] = _serie_export(df_hip)

if export_series:
    df_export = pd.DataFrame(export_series).sort_index().round(4)
    df_export.index.name = "Mes"
    csv_bytes = df_export.to_csv(date_format="%Y-%m-%d").encode("utf-8")
    st.download_button(
        "📥 Descargar CSV para Datawrapper",
        data=csv_bytes,
        file_name="oferta_max_terreno_datawrapper.csv",
        mime="text/csv",
    )
    with st.expander("Vista previa de la tabla a exportar"):
        st.dataframe(df_export)
else:
    st.info("No hay datos para exportar.")

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

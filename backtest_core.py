"""
Núcleo del backtest, compartido por las páginas Backtest y Mercado.

Vive fuera de pages/ para que ambas páginas importen la misma función y
compartan el resultado cacheado: el backtest recorre ~150 meses de inicio y
resuelve un solver por mes, así que recomputarlo por página sería caro.
"""
import streamlit as st
import pandas as pd
from pathlib import Path
import sys

ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

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

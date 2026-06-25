"""
Utilidades compartidas entre páginas: sidebar, colores, helpers.
"""
import streamlit as st
import sys
from pathlib import Path

ROOT = Path(__file__).parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

AZUL_OSCURO = "#1A2A4A"
ROJO        = "#C0392B"
VERDE       = "#27AE60"
NARANJA     = "#E67E22"
AZUL_MED    = "#2E86AB"
VIOLETA     = "#8E44AD"
GRIS_LINEA  = "#DDDDDD"


def render_sidebar():
    """Renderiza el sidebar global y devuelve un dict con los parámetros."""
    with st.sidebar:
        st.header("⚙️ Parámetros del modelo")

        precio_base = st.number_input(
            "Precio base (miles u$s/m²)",
            min_value=1.0, max_value=20.0, value=5.2, step=0.1,
            key="precio_base",
            help="Ancla de precio sobre la que se rebasa la serie histórica. "
                 "Valor del caso UCEMA: 5.2 miles u$s/m².",
        )
        costo_base = st.number_input(
            "Costo base (miles u$s/m²)",
            min_value=0.5, max_value=10.0, value=1.6, step=0.1,
            key="costo_base",
            help="Ancla de costo (sin IVA). Valor del caso UCEMA: 1.6 miles u$s/m².",
        )

        st.divider()

        tasa_precio_pct = st.slider(
            "Var. precio anual (%)", -20, 40, 15, 1,
            key="tasa_precio_pct",
            help="Tasa de crecimiento anual del precio de venta (solo afecta la proyección forward).",
        )
        tasa_costo_pct = st.slider(
            "Var. costo anual (%)", -10, 30, 5, 1,
            key="tasa_costo_pct",
            help="Tasa de crecimiento anual del costo de construcción (solo afecta la proyección).",
        )

        st.divider()

        tir_pct = st.number_input(
            "TIR objetivo (%)",
            min_value=10.0, max_value=50.0, value=25.0, step=0.5,
            key="tir_pct",
            help="TIR anual mínima exigida al proyecto. El solver encuentra el terreno "
                 "máximo que deja exactamente esta TIR.",
        )

        st.divider()
        st.caption("Datos: **jun-2026**  |  Serie: ZonaProp ESTRENAR")

    return {
        "precio_base": precio_base,
        "costo_base": costo_base,
        "tasa_precio": tasa_precio_pct / 100.0,
        "tasa_costo": tasa_costo_pct / 100.0,
        "tir_objetivo": tir_pct / 100.0,
    }

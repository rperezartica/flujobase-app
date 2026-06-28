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

# Opciones de serie de precio (label → columna en combinadas.csv)
PRECIO_OPCIONES = {
    "ZP ESTRENAR":                "ZonaProp.ESTRENAR",
    "ZP POZO":                    "ZonaProp.POZO",
    "ZP USADO":                   "ZonaProp.USADO",
    "ZP INDEX CABA":              "ZonaProp.INDEX CABA",
    "Remax-UCEMA (desde 2020)":   "Índice Remax.Valor M2 (USD)",
    "Remax empalmada INDEX CABA": "REMAX_EMPALMADA",
}

# Opciones de serie de costo
COSTO_OPCIONES = {
    "Apymeco / CAC CAMARCO": "cac_camarco",
    "ICC INDEC":              "icc_indec",
}

# Opciones de tipo de cambio para dolarizar costos
TC_OPCIONES = {
    "CCL":         "CCL_Yahoo_Sintetico",
    "MEP":         "MEP_Bolsa",
    "Oficial BNA": "Oficial_BNA",
    "Blue":        "Blue_Venta",
}


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
        st.subheader("📈 Series de mercado")

        precio_serie_label = st.selectbox(
            "Serie de precio de venta",
            options=list(PRECIO_OPCIONES.keys()),
            index=0,
            key="precio_serie_label",
            help="Índice de referencia para el rebase del precio de venta.",
        )

        costo_serie_label = st.selectbox(
            "Serie de costo de construcción",
            options=list(COSTO_OPCIONES.keys()),
            index=0,
            key="costo_serie_label",
            help="Apymeco/CAC CAMARCO: serie del caso UCEMA. "
                 "ICC INDEC: metodología actual INDEC, base nov-2015=100.",
        )

        tc_label = st.selectbox(
            "Tipo de cambio para dolarizar costos",
            options=list(TC_OPCIONES.keys()),
            index=0,
            key="tc_label",
            help="Tipo de cambio usado para convertir el índice de costo de pesos a dólares.",
        )

        st.divider()
        st.info(
            "**Nota IPC USA:** las series de precios y costos están expresadas en "
            "dólares nominales (no ajustadas por inflación USD). La serie IPC USA "
            "está disponible en la hoja Series del Excel pero no se aplica a los "
            "gráficos de esta app en la versión actual."
        )
        st.caption("Datos: **jun-2026**")

    return {
        "precio_base":   precio_base,
        "costo_base":    costo_base,
        "tasa_precio":   tasa_precio_pct / 100.0,
        "tasa_costo":    tasa_costo_pct / 100.0,
        "tir_objetivo":  tir_pct / 100.0,
        "precio_col":    PRECIO_OPCIONES[precio_serie_label],
        "costo_serie":   COSTO_OPCIONES[costo_serie_label],
        "tc_col":        TC_OPCIONES[tc_label],
    }

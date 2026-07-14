"""
Utilidades compartidas entre páginas: sidebar, colores, helpers.
"""
import streamlit as st
import pandas as pd
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

# Premisa del caso UCEMA (miles u$s/m2) y serie contra la que se calibra la
# prima por defecto, de modo que "ZP ESTRENAR x prima" reproduzca el caso.
PRECIO_CASO_UCEMA = 5.2
SERIE_CALIBRACION = "ZonaProp.ESTRENAR"

MODO_CASO    = "Caso UCEMA (5,2 miles u$s/m²)"
MODO_MERCADO = "Mercado × prima"

_MESES_ES = ["ene", "feb", "mar", "abr", "may", "jun",
             "jul", "ago", "sep", "oct", "nov", "dic"]


def _fmt_mes(fecha):
    return f"{_MESES_ES[fecha.month - 1]}-{fecha.year}"


@st.cache_data(show_spinner=False)
def ultimos_precios_series():
    """
    Último valor observado (no-NaN) de cada serie de precio de combinadas.csv.

    Devuelve dict columna → (valor en u$s/m2, fecha del dato). El último mes del
    csv puede tener NaN en algunas series (p. ej. Remax, que publica con rezago),
    por eso se toma la última observación válida de cada columna por separado.
    """
    df = pd.read_csv(ROOT / "combinadas.csv", parse_dates=["Fecha"]).set_index("Fecha").sort_index()
    out = {}
    for col in PRECIO_OPCIONES.values():
        if col not in df.columns:
            continue
        s = df[col].dropna()
        if not s.empty:
            out[col] = (float(s.iloc[-1]), s.index[-1])
    return out


def prima_default():
    """Prima que hace que la serie de calibración reproduzca el precio del caso."""
    precios = ultimos_precios_series()
    px = precios.get(SERIE_CALIBRACION, (None, None))[0]
    if not px:
        return 1.77
    return round(PRECIO_CASO_UCEMA / (px / 1000), 2)


def render_sidebar():
    """Renderiza el sidebar global y devuelve un dict con los parámetros."""
    with st.sidebar:
        st.header("⚙️ Parámetros del modelo")

        st.subheader("💲 Precio de referencia de venta")

        precio_serie_label = st.selectbox(
            "Serie de referencia",
            options=list(PRECIO_OPCIONES.keys()),
            index=0,
            key="precio_serie_label",
            help="Índice de mercado que gobierna el precio de venta del proyecto: "
                 "define la dinámica del rebase mes a mes y, en modo mercado, "
                 "también el nivel.",
        )
        precio_col = PRECIO_OPCIONES[precio_serie_label]

        modo_ancla = st.radio(
            "Ancla de precio",
            options=[MODO_CASO, MODO_MERCADO],
            index=0,
            key="modo_ancla",
            help="Caso UCEMA: precio base fijo del enunciado (5.2 miles u$s/m²), "
                 "independiente de la serie elegida. "
                 "Mercado × prima: el precio base sale del último dato de la serie "
                 "elegida, multiplicado por una prima de posicionamiento del producto.",
        )

        px_serie, fecha_serie = ultimos_precios_series().get(precio_col, (None, None))

        if modo_ancla == MODO_MERCADO:
            prima = st.number_input(
                "Prima sobre el índice (×)",
                min_value=0.5, max_value=5.0, value=prima_default(), step=0.01,
                key="prima_producto",
                help="Cuánto se vende el m² del proyecto por encima del índice de "
                     f"referencia. El default reproduce el precio del caso UCEMA "
                     f"({PRECIO_CASO_UCEMA} miles u$s/m²) cuando la serie elegida "
                     "es ZP ESTRENAR.",
            )
            if px_serie is None:
                st.error(f"Sin datos para {precio_serie_label}.")
                st.stop()
            precio_base = px_serie / 1000 * prima
            st.caption(
                f"**{precio_serie_label}** {px_serie:,.0f} u$s/m² ({_fmt_mes(fecha_serie)}) "
                f"× {prima:.2f} = **{precio_base:.2f} miles u$s/m²**"
            )
        else:
            precio_base = st.number_input(
                "Precio base (miles u$s/m²)",
                min_value=1.0, max_value=20.0, value=PRECIO_CASO_UCEMA, step=0.1,
                key="precio_base",
                help="Ancla de precio sobre la que se rebasa la serie histórica. "
                     "Valor del caso UCEMA: 5.2 miles u$s/m².",
            )
            if px_serie:
                st.caption(
                    f"Prima implícita sobre **{precio_serie_label}** "
                    f"({px_serie:,.0f} u$s/m², {_fmt_mes(fecha_serie)}): "
                    f"**{precio_base / (px_serie / 1000):.2f}×**"
                )

        st.divider()

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
        "precio_col":    precio_col,
        "costo_serie":   COSTO_OPCIONES[costo_serie_label],
        "tc_col":        TC_OPCIONES[tc_label],
        # Labels elegidos, para que las páginas puedan rotular sus gráficos con la
        # serie realmente activa en vez de un nombre fijo.
        "precio_label":  precio_serie_label,
        "costo_label":   costo_serie_label,
        "tc_label":      tc_label,
    }

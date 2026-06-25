import streamlit as st

st.set_page_config(
    page_title="FlujoBase",
    page_icon="🏗️",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("FlujoBase — Valuación de Terrenos")
st.caption("Caso Integrador · Diplomatura en Real Estate · UCEMA")

st.markdown("""
**FlujoBase** resuelve el precio máximo que puede pagarse por un terreno —dada una TIR mínima objetivo—
según las condiciones de precio y costo vigentes en cada mes desde enero de 2016 hasta hoy.

Los parámetros del modelo se configuran en el panel lateral izquierdo y se comparten entre todas las páginas.
""")

col1, col2, col3, col4 = st.columns(4)
col1.metric("Superficie total", "23.600 m²")
col2.metric("Superficie vendible", "13.200 m²")
col3.metric("Plazo de obra", "18 meses")
col4.metric("TIR mínima (base)", "25% anual")

st.divider()

st.markdown("""
### Secciones

| Página | Qué muestra |
|--------|-------------|
| **📊 1 · Backtest** | Curva histórica de oferta máxima de terreno + proyección por escenario |
| **🏢 2 · Proyecto** | Flujo de caja mes a mes para el mes de inicio que elijas |
| **📈 3 · Mercado** | Trayectorias históricas, ratios y distribuciones de precio/costo |

---

*Fuentes: ZonaProp ESTRENAR (precio de venta), Apymeco/CCL (costo construcción), índice CAC, CCL Yahoo Sintético · ene-2016 → jun-2026*
""")

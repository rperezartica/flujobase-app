# CONTEXT.md — FlujoBase Streamlit App
*Handoff document para Claude Code. Leer antes de tocar cualquier archivo.*

---

## QUÉ ES ESTE PROYECTO

FlujoBase es una herramienta de análisis financiero para desarrolladores residenciales PyME en Argentina. Este directorio contiene el motor Python de un backtest de valuación de terrenos basado en el caso integrador de la Diplomatura en Real Estate de UCEMA.

**Objetivo de esta sesión:** crear y deployar una app Streamlit en Streamlit Cloud que permita al usuario explorar el backtest interactivamente, cambiando parámetros del modelo en tiempo real.

---

## ARCHIVOS EXISTENTES EN ESTE DIRECTORIO

### Motor principal
- `motor_v1_estatico.py` — motor de valuación estático. Resuelve la oferta máxima de terreno dado precio/costo fijos. VALIDADO contra el Excel original (terreno = u$s 7.254.454, TIR 25%, rentabilidad 56.49%).
- `motor_v3_backtest.py` — motor de backtest completo. Importa funciones de motor_v1. Contiene además las funciones de gráficos matplotlib. **Los dos archivos deben estar en la misma carpeta.**

### Datos
- `combinadas.csv` — series mensuales ene-2016 a jun-2026: CAC_index, CAC_USD, ZonaProp ESTRENAR/POZO/USADO/INDEX_CABA, CCL, Apymeco_ARS, Costo_USD, REMAX_USD. Columna IPC_USA vacía por ahora.

### Excel (no necesario para Streamlit, solo referencia)
- `build_excel_v1.py` — builder del Excel interactivo
- `FlujoBase_Backtest_Solver.xlsx` — Excel generado

---

## ARQUITECTURA DE LA APP STREAMLIT

### Estructura de archivos a crear
```
app.py                    ← landing page / navegación
pages/
  1_Backtest.py           ← backtest histórico + proyección con parámetros
  2_Proyecto.py           ← flujo del proyecto para fecha/params elegidos
  3_Mercado.py            ← trayectorias de precio/costo + KDE
requirements.txt          ← dependencias
.streamlit/
  config.toml             ← tema visual
```

### Página 1 — Backtest
**Inputs (sidebar):**
- Fecha de inicio (slider de mes/año, rango 2016-2026)
- Serie de precio: selectbox (ESTRENAR, POZO, USADO, INDEX_CABA, REMAX)
- Precio unitario base (number_input, default 5.2 miles u$s/m²)
- Costo unitario base (number_input, default 1.6 miles u$s/m²)
- Tasa variación precio anual % (slider, default 15%)
- Tasa variación costo anual % (slider, default 5%)
- TIR objetivo % (number_input, default 25%)

**Outputs:**
- Gráfico Plotly: curva de oferta máxima de terreno (histórico sólido + proyección punteada por escenario)
- Tabla resumen: mes de inicio seleccionado → terreno máx, TIR, rentabilidad, margen, máx exposición
- Indicador de posición actual en la distribución histórica (percentil)

### Página 2 — Proyecto
**Inputs:** mismos del sidebar global + mes de inicio específico
**Outputs:**
- Flujo de caja mes a mes (tabla + gráfico de aportes de capital)
- KPIs: TIR, rentabilidad, margen bruto, máxima exposición, total ventas, total costo

### Página 3 — Mercado
**Outputs:**
- Trayectorias históricas: precio ESTRENAR, POZO, USADO, costo Apymeco/CCL (Plotly interactivo)
- Ratio precio/costo con fill above/below average
- Spread ESTRENAR vs USADO, POZO vs USADO
- KDE: precio, costo, ratio — con marcador de posición actual

---

## PARÁMETROS DEL CASO UCEMA (constantes del modelo)
```python
SUPERFICIE_TOTAL   = 23600    # m2 a construir
SUPERFICIE_PROPIA  = 13200    # m2 vendibles propios
PLAZO_OBRA         = 18       # meses
N_MESES            = 36       # horizonte total
IVA                = 0.105
TNM                = 0.007974 # tasa mensual crédito
PCT_CREDITO        = 0.40     # % sobre costo construcción mensual
PRECIO_VENTA_BASE  = 5.2      # miles u$s/m2 (ancla para rebase)
COSTO_UNIT_BASE    = 1.6      # miles u$s/m2 (ancla para rebase)
TIR_MIN            = 0.25     # TIR anual mínima (restricción solver)
```

---

## DECISIONES TÉCNICAS CLAVE (no rediscutir)

- **Serie de precio para rebase:** ZonaProp ESTRENAR puro (sin empalme con Remax). Remax está en el CSV como referencia pero no se usa en el motor de rebase.
- **CAC dolarizado:** CAC_pesos / CCL_Yahoo_Sintetico antes de rebasar. El CAC en pesos NO se usa directamente como ancla de costo.
- **Ancla "hoy":** último valor disponible de cada serie en combinadas.csv.
- **Proyección forward:** tasas compuestas mensuales, configurables por usuario.
- **Escenario naive:** precio y costo congelados al mes de inicio del proyecto (ancla móvil). Diferente del estático 0%/0%.
- **Solver de terreno:** usa scipy.optimize.brentq sobre la función TIR(terreno). Ya está en motor_v1_estatico.py como `resolver_terreno_max()`.

---

## PALETA DE COLORES (coherente con los gráficos matplotlib existentes)
```python
AZUL_OSCURO = "#1A2A4A"
ROJO        = "#C0392B"
VERDE       = "#27AE60"
NARANJA     = "#E67E22"
AZUL_MED    = "#2E86AB"
VIOLETA     = "#8E44AD"
GRIS_LINEA  = "#DDDDDD"
```

---

## DEPENDENCIAS REQUERIDAS
```
streamlit>=1.35
pandas
numpy
numpy_financial
scipy
plotly
matplotlib  # solo para las funciones de gráfico del motor_v3, no para la app
```

---

## NOTAS PARA CLAUDE CODE

1. **NO modificar** `motor_v1_estatico.py` ni `motor_v3_backtest.py`. Importarlos tal cual.
2. Los gráficos de la app usan **Plotly** (interactivo), no matplotlib (que queda solo en el motor para generar los PNG).
3. El `backtest()` del motor v3 puede tardar ~5-10 segundos para el rango completo. Usar `@st.cache_data` agresivamente.
4. El sidebar con parámetros debe ser **global** (compartido entre páginas via `st.session_state`).
5. La función `resolver_terreno_max()` tarda ~0.1s por punto. Para el backtest completo (88-125 puntos) usar cache.
6. Streamlit Cloud usa Python 3.11. Verificar compatibilidad de numpy_financial.

---

## ESTADO AL INICIO DE ESTA SESIÓN

- Motor Python: validado y funcionando
- Datos: combinadas.csv actualizado a jun-2026
- GitHub: repo a crear en esta sesión
- Streamlit Cloud: cuenta a crear/vincular en esta sesión
- Prioridad: app funcional > diseño perfecto

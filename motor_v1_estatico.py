"""
Motor de valuación de terreno - Caso Integrador UCEMA
Paso 1: réplica del caso ESTÁTICO (precio/costo fijos), calibrada contra la
planilla del profesor "sin permuta" (convención de crédito cancelado en
bloque al fin de obra y honorarios lump en el mes 1). A TIR 25.00% exacta
da Terreno = u$s 7.135.526; la planilla del profesor reporta u$s 7.128.890
porque su solver quedó en TIR 25.02% (mismo modelo, distinta precisión del
objetivo).
"""
import numpy as np
import numpy_financial as npf
from scipy.optimize import brentq

# ============================================================
# PREMISAS FIJAS DEL CASO (no cambian con el rebase)
# ============================================================
SUPERFICIE_TOTAL = 23600.0       # m2 a construir
SUPERFICIE_PROPIA = 13200.0      # m2 vendibles propios
IVA = 0.105
PLAZO_OBRA = 18                  # meses
HONOR_PCT = 0.08                 # % s/costo construcción
GASTOS_VARIOS_PCT = 0.03         # % s/costo construcción
GASTOS_COMERC_PCT = 0.025        # % s/monto ventas (por avance de venta)
GASTOS_COMERC_LANZ_PCT = 0.005   # % s/monto ventas (lanzamiento, mes 1)
GASTOS_NOTARIALES_PCT = 0.015    # % s/monto ventas (a la escritura)
PCT_CREDITO = 0.40               # % s/costo construcción mensual
TNM = 0.007974                   # tasa mensual del préstamo
WACC_ANUAL = 0.12
TIR_MIN = 0.25
RENT_MIN = 0.50

N_MESES = 36  # horizonte total del proyecto (0 a 36)

COSTO_UNIT_BASE = 1.6    # miles u$s/m2, sin IVA - "hoy" (jun-2026)
PRECIO_VENTA_BASE = 5.2  # miles u$s/m2 - "hoy" (jun-2026)


# Avance de obra mensual (% del costo total), meses 0-36
AVANCE_OBRA = np.array(
    [0, .035, .045, .05, .065, .07, .07, .075, .085, .085, .065, .055,
     .05, .045, .045, .045, .04, .04, .035] + [0] * 18
)
assert len(AVANCE_OBRA) == 37
assert abs(AVANCE_OBRA.sum() - 1.0) < 1e-9

# % vendido por mes (cohortes de venta), meses 0-36 (de Plan de Ventas)
# % vendido por mes (cohortes de venta), meses 0-36 - extraído DIRECTO del
# Excel original (Plan de Ventas!B26:AL26, fila "Viviendas") para eliminar
# riesgo de error de transcripción manual.
PCT_VENDIDO = np.array([
    0, 0.1, 0.05, 0.0209677419354839, 0.0209677419354839, 0.0209677419354839,
    0.0209677419354839, 0.0209677419354839, 0.0209677419354839, 0.0209677419354839,
    0.0209677419354839, 0.0209677419354839, 0.0209677419354839, 0.0209677419354839,
    0.0209677419354839, 0.0209677419354839, 0.0209677419354839, 0.0209677419354839,
    0.1, 0.05, 0.05, 0.0209677419354839, 0.0209677419354839, 0.0209677419354839,
    0.0209677419354839, 0.0209677419354839, 0.0209677419354839, 0.0209677419354839,
    0.0209677419354839, 0.0209677419354839, 0.0209677419354839, 0.0209677419354839,
    0.0209677419354839, 0.0209677419354839, 0.0209677419354839, 0.0209677419354839,
    0.0209677419354839,
])
assert len(PCT_VENDIDO) == 37, len(PCT_VENDIDO)
assert abs(PCT_VENDIDO.sum() - 1.0) < 1e-6, PCT_VENDIDO.sum()


def calcular_boletos(monto_venta_cohorte):
    """Boletos: 30% de cada cohorte, cobrado de inmediato en el mes de venta."""
    return 0.30 * monto_venta_cohorte


def calcular_cuotas(monto_venta_cohorte):
    """
    Replica EXACTA de la fórmula recursiva de 'Plan de Ventas'!C14 del
    Excel original del caso (no una versión "corregida"):

        cuotas[m] = 0.40 * monto_cohorte[m] / (19 - m) + cuotas[m-1]   (m = 1..18)
        cuotas[m] = 0                                                  (m >= 19)

    Cada cohorte vendida en el mes m agrega una cuota mensual CONSTANTE
    de 0.40*monto_cohorte[m]/(19-m) al acumulado, pero esa tasa nunca se
    remueve cuando la cohorte "debería" terminar de pagar — el acumulado
    se descarta por completo después del mes 18 (entrega). Es un supuesto
    del Excel original (no un error de transcripción): así está validado
    en el caso, y por eso una porción del 40% nominal nunca se cobra en
    efectivo (no afecta el Margen Bruto, que se calcula sobre lo
    devengado, no sobre lo efectivamente cobrado).

    En el caso estático, monto_cohorte[m] = pct_vendido[m]*monto_total, y
    D6 (pool fijo del Excel) = 0.4*monto_total, por lo que esta
    generalización por-cohorte es idéntica al original cuando el precio
    es fijo, y se extiende naturalmente a cohortes valuadas a precios
    distintos (rebase mes a mes).
    """
    cuotas = np.zeros(37)
    acumulado = 0.0
    for m in range(1, PLAZO_OBRA + 1):  # meses 1 a 18
        incremento = 0.40 * monto_venta_cohorte[m] / (19 - m)
        acumulado += incremento
        cuotas[m] = acumulado
    return cuotas


def calcular_entrega(monto_venta_cohorte):
    """
    Posesión + Escritura, cobrados en el mes de entrega = max(mes_venta, 18).

    - Cohortes vendidas en meses 1-18 (pre-entrega): 15% posesión + 15%
      escritura = 30% del monto, en el mes 18. Su 40% de "cuotas" ya se
      cobró (parcialmente, por el quirk del acumulado) vía calcular_cuotas.
    - Cohortes vendidas en meses 19-36 (post-entrega, edificio terminado):
      el Excel original redirige el 40% nominal de "cuotas" hacia la
      Posesión (fórmula '=($D$7+$D$6)*indicador' a partir del mes 19), de
      modo que esas cohortes cobran 15%(posesión)+40%(cuotas redirigidas)
      +15%(escritura) = 70% en su propio mes de venta (sumado al 30% de
      boleto, dan 100% inmediato).

    Devuelve (entrega_total_mes, escritura_sola_mes) -- esta última (solo
    el 15% de escritura pura) se usa como base de gastos notariales.
    """
    entrega_mes = np.zeros(37)
    escritura_mes = np.zeros(37)
    for mes_venta in range(37):
        monto = monto_venta_cohorte[mes_venta]
        if monto <= 0:
            continue
        mes_entrega = max(mes_venta, PLAZO_OBRA)
        if mes_venta >= PLAZO_OBRA + 1:  # post-entrega: 15%+40% redirigido
            entrega_mes[mes_entrega] += (0.15 + 0.40) * monto
        else:
            entrega_mes[mes_entrega] += 0.15 * monto
        escritura_mes[mes_entrega] += 0.15 * monto
    return entrega_mes, escritura_mes


def simular_flujo(terreno, costo_unit_mensual, precio_unit_mensual):
    """
    Simula el flujo de caja completo del proyecto.

    costo_unit_mensual: array de 37 valores (miles u$s/m2, SIN IVA) -
        costo unitario de construcción vigente en cada mes del proyecto
        (mes 0 a 36). Solo se usan los meses 1-18 (obra).
    precio_unit_mensual: array de 37 valores (miles u$s/m2) - precio de
        venta vigente en cada mes del proyecto (se usa el del mes en que
        se vende cada cohorte).

    Devuelve dict con: tir_anual, rentabilidad, margen_bruto,
    max_exposicion, aporte_capital_mensual (array).
    """
    # --- Costos de construcción (mensual, en pesos/miles u$s) ---
    costo_construccion_mes = AVANCE_OBRA * SUPERFICIE_TOTAL * costo_unit_mensual * (1 + IVA)
    costo_total = costo_construccion_mes.sum()

    # --- Ingresos de venta por cohorte, con cobro distribuido ---
    monto_venta_cohorte = PCT_VENDIDO * SUPERFICIE_PROPIA * precio_unit_mensual
    monto_total_ventas = monto_venta_cohorte.sum()

    boletos_mes = calcular_boletos(monto_venta_cohorte)
    cuotas_mes = calcular_cuotas(monto_venta_cohorte)
    entrega_mes, escritura_sola_mes = calcular_entrega(monto_venta_cohorte)
    ingresos_mes = boletos_mes + cuotas_mes + entrega_mes + escritura_sola_mes
    notariales_base_mes = escritura_sola_mes  # base (15%) para gastos notariales

    # --- Honorarios profesionales ---
    # El lump del 60% se paga en el mes 1 (convención planilla profesor
    # "sin permuta"), no en el mes 0. Se asigna la parte recurrente primero
    # y luego se suma el lump para no pisarla.
    honorarios_mes = np.zeros(37)
    honorarios_mes[1:19] = costo_total * HONOR_PCT * 0.4 * AVANCE_OBRA[1:19]
    honorarios_mes[1] += costo_total * HONOR_PCT * 0.6

    # --- Gastos varios y contingencias ---
    gastos_varios_mes = costo_total * GASTOS_VARIOS_PCT * AVANCE_OBRA

    # --- Gastos comerciales (sobre % vendido mensual + lanzamiento) ---
    gastos_comerciales_mes = monto_total_ventas * GASTOS_COMERC_PCT * PCT_VENDIDO
    gastos_comerciales_mes[1] += monto_total_ventas * GASTOS_COMERC_LANZ_PCT

    # --- Gastos notariales (1.5% sobre el monto que se escritura cada mes, base = 15% de cada cohorte / 0.15 = monto cohorte completo escriturado) ---
    gastos_notariales_mes = (notariales_base_mes / 0.15) * GASTOS_NOTARIALES_PCT

    # --- Egresos totales ---
    terreno_mes = np.zeros(37)
    terreno_mes[0] = terreno

    egresos_mes = (
        terreno_mes
        + costo_construccion_mes
        + honorarios_mes
        + gastos_comerciales_mes
        + gastos_notariales_mes
        + gastos_varios_mes
    )

    # --- Crédito bancario ---
    # Convención planilla profesor "sin permuta": el préstamo se acumula
    # durante la obra y se cancela en un solo bloque al fin de obra (mes
    # PLAZO_OBRA). El interés de cada mes se computa sobre el saldo ANTES de
    # cancelar (por eso en el mes de cancelación se cobra interés sobre el
    # saldo completo y recién después se devuelve todo).
    desembolso_mes = costo_construccion_mes * PCT_CREDITO
    devolucion_mes = np.zeros(37)
    interes_mes = np.zeros(37)
    saldo_credito = 0.0

    for m in range(37):
        saldo_disponible = saldo_credito + desembolso_mes[m]
        interes_mes[m] = saldo_disponible * TNM        # interés sobre saldo pre-cancelación
        if m == PLAZO_OBRA:                            # mes 18: cancela todo el saldo de una
            devolucion_mes[m] = saldo_disponible
        saldo_credito = saldo_disponible - devolucion_mes[m]

    # --- Aporte de capital ---
    aporte_capital_mes = -(
        egresos_mes - ingresos_mes - desembolso_mes + devolucion_mes + interes_mes
    )
    aporte_acumulado = np.cumsum(aporte_capital_mes)

    margen_bruto = ingresos_mes.sum() - egresos_mes.sum() - interes_mes.sum()
    max_exposicion = -aporte_acumulado.min()

    tir_mensual = npf.irr(aporte_capital_mes)
    tir_anual = tir_mensual * 12 if tir_mensual is not None and not np.isnan(tir_mensual) else np.nan

    rentabilidad = abs(margen_bruto / max_exposicion) if max_exposicion != 0 else np.nan

    return {
        "tir_anual": tir_anual,
        "rentabilidad": rentabilidad,
        "margen_bruto": margen_bruto,
        "max_exposicion": max_exposicion,
        "aporte_capital_mensual": aporte_capital_mes,
        "monto_total_ventas": monto_total_ventas,
        "costo_total": costo_total,
    }


def resolver_terreno_max(costo_unit_mensual, precio_unit_mensual, tir_objetivo=TIR_MIN):
    """Encuentra el Terreno que deja la TIR anual exactamente en tir_objetivo."""

    def f(terreno):
        r = simular_flujo(terreno, costo_unit_mensual, precio_unit_mensual)
        return r["tir_anual"] - tir_objetivo

    # Buscar un bracket razonable. La TIR es decreciente en el terreno, así
    # que el máximo terreno es la raíz de f. En meses con costos en USD muy
    # bajos, la TIR a terreno≈0 puede dar NaN (flujo degenerado, sin aporte de
    # capital); en ese caso se sube el extremo inferior hasta que sea finita,
    # para no perder el mes (antes brentq moría con "f(0) is NaN").
    lo, hi = 0.0, 50000.0
    if not np.isfinite(f(lo)):
        lo = 1.0
        while not np.isfinite(f(lo)) and lo < hi:
            lo *= 2

    while f(hi) > 0:
        hi *= 1.5
        if hi > 1e7:
            raise RuntimeError("No se encontró bracket válido")

    # Sin cambio de signo no hay raíz: proyecto infactible a esa TIR objetivo.
    if not (f(lo) > 0 and f(hi) < 0):
        raise RuntimeError("No se encontró bracket válido (proyecto infactible)")

    terreno = brentq(f, lo, hi, xtol=1e-3)
    resultado = simular_flujo(terreno, costo_unit_mensual, precio_unit_mensual)
    resultado["terreno"] = terreno
    return resultado


if __name__ == "__main__":
    # --- VALIDACIÓN: caso estático original ---
    costo_unit_fijo = np.full(37, 1.6)   # miles u$s/m2 sin IVA
    precio_unit_fijo = np.full(37, 5.2)  # miles u$s/m2

    resultado = resolver_terreno_max(costo_unit_fijo, precio_unit_fijo)

    print("=== VALIDACIÓN CONTRA PLANILLA PROFESOR (sin permuta) ===")
    print(f"Terreno (Python):     u$s {resultado['terreno']*1000:,.0f}")
    print(f"Terreno (profe):      u$s 7,128,890  (a TIR 25.02%; a 25.00% exacta: 7,135,526)")
    print(f"TIR anual:            {resultado['tir_anual']*100:.4f}%  (target 25.00%)")
    print(f"Rentabilidad s/Cap:   {resultado['rentabilidad']*100:.2f}%  (profe: 57.17%)")
    print(f"Margen Bruto:         {resultado['margen_bruto']:,.2f} (miles u$s)")
    print(f"Máx exposición cap:   {resultado['max_exposicion']:,.2f} (miles u$s)")
    print(f"Monto total ventas:   {resultado['monto_total_ventas']:,.2f} (profe: 68,640.00)")
    print(f"Costo total constr.:  {resultado['costo_total']:,.2f} (profe: 41,724.80)")

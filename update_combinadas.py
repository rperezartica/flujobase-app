"""
Script para actualizar combinadas.csv con:
  1. ICC_INDEC: Índice del Costo de la Construcción (metodología actual, base nov-2015=100)
  2. REMAX_EMPALMADA: Remax extendida hacia atrás con ZonaProp INDEX CABA

Ejecutar una sola vez. No modifica el motor ni la app.
"""
import pandas as pd
import numpy as np
from pathlib import Path

HERE = Path(__file__).parent
CSV_PATH = HERE / "combinadas.csv"
XLSX_PATH = Path("/tmp/apendice4.xlsx")

# ============================================================
# 1. RECONSTRUIR ICC_INDEC (Base nov-2015 = 100)
# ============================================================

df_xl = pd.read_excel(XLSX_PATH, sheet_name="4.6 ICC", header=None)

# Extraer filas con (fecha, % var mensual) — col 0 y col 7
rows = []
for _, row in df_xl.iterrows():
    val = row[0]
    pct = row[7]
    if pd.notna(val) and pd.notna(pct):
        try:
            fecha = pd.Timestamp(val)
            rows.append({"fecha": fecha, "var_mensual": float(pct)})
        except Exception:
            pass

df_vars = (
    pd.DataFrame(rows)
    .sort_values("fecha")
    .reset_index(drop=True)
)

# Filtrar desde nov-2015 (metodología actual)
BASE_FECHA = pd.Timestamp("2015-11-01")
df_actual = df_vars[df_vars.fecha >= BASE_FECHA].reset_index(drop=True)

# Reconstruir índice: nov-2015 = 100, luego aplicar variaciones hacia adelante
icc_index = {}
level = 100.0
for i, row in df_actual.iterrows():
    if i == 0:
        icc_index[row.fecha] = level  # base = 100
    else:
        level = level * (1.0 + row.var_mensual)
        icc_index[row.fecha] = level

icc_series = pd.Series(icc_index, name="ICC_INDEC")
icc_series.index.name = "Fecha"

print(f"ICC_INDEC reconstruido: {len(icc_series)} meses "
      f"({icc_series.index.min().date()} → {icc_series.index.max().date()})")
print(f"  nov-2015 = {icc_series.iloc[0]:.2f} (base)")
print(f"  ene-2016 = {icc_series.get(pd.Timestamp('2016-01-01'), float('nan')):.2f}")
print(f"  último   = {icc_series.iloc[-1]:.2f}")

# ============================================================
# 2. REMAX EMPALMADA
# ============================================================

df = pd.read_csv(CSV_PATH, parse_dates=["Fecha"])
df = df.sort_values("Fecha").reset_index(drop=True)

REMAX_COL  = "Índice Remax.Valor M2 (USD)"
ZP_IDX_COL = "ZonaProp.INDEX CABA"

# Ventana de solapamiento: ene-2020 a dic-2022
mask_overlap = (
    (df["Fecha"] >= "2020-01-01") &
    (df["Fecha"] <= "2022-12-31") &
    df[REMAX_COL].notna() &
    df[ZP_IDX_COL].notna()
)
ratio_mean = (df.loc[mask_overlap, REMAX_COL] / df.loc[mask_overlap, ZP_IDX_COL]).mean()
print(f"\nREMAX/ZP_INDEX ratio (ene-2020 a dic-2022, {mask_overlap.sum()} meses): {ratio_mean:.4f}")

# Construir REMAX_EMPALMADA
remax_emp = df[REMAX_COL].copy()
mask_antes_2020 = df["Fecha"] < "2020-01-01"
remax_emp.loc[mask_antes_2020] = df.loc[mask_antes_2020, ZP_IDX_COL] * ratio_mean
df["REMAX_EMPALMADA"] = remax_emp

print(f"REMAX_EMPALMADA: {df['REMAX_EMPALMADA'].notna().sum()} meses con dato "
      f"({df.loc[df['REMAX_EMPALMADA'].notna(), 'Fecha'].min().date()} → "
      f"{df.loc[df['REMAX_EMPALMADA'].notna(), 'Fecha'].max().date()})")

# ============================================================
# 3. AGREGAR ICC_INDEC AL CSV
# ============================================================

df = df.set_index("Fecha")
df["ICC_INDEC"] = icc_series

# Verificar
n_icc = df["ICC_INDEC"].notna().sum()
print(f"\nICC_INDEC en combinadas.csv: {n_icc} meses con dato")
print(f"  ene-2016 = {df.loc[pd.Timestamp('2016-01-01'), 'ICC_INDEC']:.2f}")

df = df.reset_index()
df.to_csv(CSV_PATH, index=False)
print(f"\ncombinadas.csv actualizado: {len(df)} filas, {len(df.columns)} columnas")
print(f"Columnas nuevas: ICC_INDEC, REMAX_EMPALMADA")

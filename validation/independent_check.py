"""Independent check of the headline numbers.

Deliberately does NOT import the app's code (epresso/*). It reads plain CSV
exports of the three Access tables (validation/exports/, created once with
validation/export_accdb_tables.py) plus the original Stores file, and computes
the validation measures with basic pandas group-bys.

Run:  python validation/independent_check.py
"""
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
sales = pd.read_csv(HERE / "exports" / "Sales.csv")
stores = pd.read_csv(HERE.parent / "data" / "Support_EX_B_Stores.csv", sep="\t", dtype=str)

sales["Date"] = pd.to_datetime(sales["Date"])
sales["Year"] = sales["Date"].dt.year
sales["Month"] = sales["Date"].dt.month
type_by_store = dict(zip(stores["ID"], stores["StoreType"]))       # dictionary lookup instead of a join
sales["StoreType"] = sales["Store ID"].map(type_by_store)

print("Rows:", len(sales))
print(f"1. Total revenue (5 years): {sales['Revenue'].sum():,.2f}")
by_type = sales.groupby("StoreType")["Revenue"].sum()
print(f"2. Website: {by_type['Website']:,.2f}   Brick & Mortar: {by_type['Brick & Mortar']:,.2f}")
print("3. Revenue by year:")
print(sales.pivot_table(index="Year", columns="StoreType", values="Revenue", aggfunc="sum", margins=True).round(2))
monthly = sales.groupby("Month")["Revenue"].sum()
print("4. Monthly share of 5-year total (%):")
print((monthly / monthly.sum() * 100).round(2).to_string())
chi = sales[sales["Store ID"] == "SH11"].groupby("Year")["Revenue"].sum()
print(f"5. Chicago (SH11) 2025 -> 2029: {chi[2025]:,.0f} -> {chi[2029]:,.0f} ({(chi[2029]/chi[2025]-1)*100:.2f}%)")

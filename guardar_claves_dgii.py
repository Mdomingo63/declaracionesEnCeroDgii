"""Importa credenciales DGII desde credenciales.csv al keyring del sistema.

El CSV debe tener las columnas ``rnc,clave``. Este script guarda cada clave
con el servicio ``dgii_ofv`` y el RNC como usuario, para que el automatizador
pueda recuperarla sin incluirla en su código. El CSV contiene claves en texto
plano: protégelo y elimínalo cuando termine la importación.

Uso: ``python guardar_claves_dgii.py``
"""

import csv
import sys
import keyring

SERVICIO = "dgii_ofv"
ARCHIVO_CSV = "credenciales.csv"


def main():
    try:
        with open(ARCHIVO_CSV, encoding="utf-8") as f:
            filas = list(csv.DictReader(f))
    except FileNotFoundError:
        print(f"❌ No se encontró {ARCHIVO_CSV}.")
        print("Crea un archivo CSV con este formato:")
        print("rnc,clave")
        print("00109491563,MiClave123")
        print("501481808,OtraClave456")
        sys.exit(1)

    if not filas:
        print("❌ El archivo CSV está vacío.")
        sys.exit(1)

    guardadas = 0
    for fila in filas:
        rnc = (fila.get("rnc") or "").strip()
        clave = (fila.get("clave") or "").strip()

        if not rnc or not clave:
            continue

        keyring.set_password(SERVICIO, rnc, clave)
        print(f"✅ Guardado: {rnc}")
        guardadas += 1

    print(f"\nProceso completado. Se guardaron {guardadas} claves en el keyring.")


if __name__ == "__main__":
    main()

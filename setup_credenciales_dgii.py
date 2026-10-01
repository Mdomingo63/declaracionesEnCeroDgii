"""
setup_credenciales_dgii.py

Ejecuta este script UNA SOLA VEZ (o cada vez que necesites agregar/actualizar
un usuario) para guardar las credenciales de la DGII en el keyring del
sistema operativo (Keychain en macOS, Credential Manager en Windows,
Secret Service / KWallet en Linux).

Las claves NUNCA quedan escritas en ningún archivo de texto plano ni en el
código fuente del script principal. Se piden por consola con `getpass`,
que no las muestra en pantalla mientras las escribes.

Requisitos:
    pip install keyring

Uso:
    python setup_credenciales_dgii.py
"""

import json
import sys
import keyring
import getpass
from pathlib import Path

# Nombre del "servicio" bajo el cual se agrupan todas las credenciales.
# No es secreto, solo es un namespace dentro del keyring.
SERVICIO = "dgii_ofv"

# La lista de RNCs se mantiene fuera del control de versiones porque revela
# información comercial de los clientes.
ARCHIVO_RNC = Path(__file__).parent / "config_rnc.json"


def cargar_rncs():
    if not ARCHIVO_RNC.exists():
        print("❌ No se encontró config_rnc.json. Crea el archivo con una lista de RNCs, por ejemplo:")
        print('   ["00109491563", "501481808", ...]')
        sys.exit(1)

    with ARCHIVO_RNC.open(encoding="utf-8") as f:
        return json.load(f)


def main():
    rncs = cargar_rncs()
    print(f"Se registrarán/actualizarán {len(rncs)} credenciales en el keyring del sistema.")
    print("Presiona ENTER sin escribir nada para saltar un RNC y dejar su clave actual sin cambios.\n")

    for rnc in rncs:
        existente = keyring.get_password(SERVICIO, rnc)
        estado = "(ya existe una clave guardada)" if existente else "(sin clave guardada)"
        clave = getpass.getpass(f"Clave para RNC {rnc} {estado}: ")

        if clave.strip() == "":
            print(f"  -> Saltado (sin cambios) para {rnc}\n")
            continue

        keyring.set_password(SERVICIO, rnc, clave)
        print(f"  -> Guardado correctamente para {rnc}\n")

    print("Proceso de configuración completado.")


if __name__ == "__main__":
    main()
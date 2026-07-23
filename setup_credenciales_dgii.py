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

# La lista de RNCs vive en un archivo aparte (config_rncs.json), fuera del
# código fuente. El RNC no es un secreto de seguridad (es un identificador
# fiscal público), pero revela qué clientes maneja este despacho, así que
# se mantiene fuera del control de versiones (ver .gitignore).
ARCHIVO_RNCS = Path(__file__).parent / "config_rncs.json"


def cargar_rncs():
    if not ARCHIVO_RNCS.exists():
        print(f"❌ No se encontró {ARCHIVO_RNCS.name}. Crea ese archivo con la lista de RNCs, por ejemplo:")
        print('   ["00109491563", "501481808", ...]')
        sys.exit(1)

    with open(ARCHIVO_RNCS, encoding="utf-8") as f:
        return json.load(f)


RNCS = cargar_rncs()


def main():
    print(f"Se registrarán/actualizarán {len(RNCS)} credenciales en el keyring del sistema.")
    print("Presiona ENTER sin escribir nada para saltar un RNC y dejar su clave actual sin cambios.\n")

    for rnc in RNCS:
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
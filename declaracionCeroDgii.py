"""
declaracionCeroDgii.py

Presenta declaraciones en cero (IR3, 606, 607, ITBIS) para una lista de
usuarios en la Oficina Virtual de la DGII.

Las claves de acceso YA NO están escritas en este archivo. Se leen en
tiempo de ejecución desde el keyring del sistema operativo (Keychain en
macOS, Credential Manager en Windows, Secret Service/KWallet en Linux),
usando el mismo "servicio" (namespace) con el que fueron guardadas por
setup_credenciales_dgii.py.

Requisitos:
    pip install selenium webdriver-manager keyring

Antes de correr este script por primera vez, ejecuta:
    python setup_credenciales_dgii.py
para registrar las claves en el keyring de esta máquina.
"""

import json
import sys
import keyring
from pathlib import Path
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from datetime import datetime, timedelta
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

# Namespace usado en el keyring (debe coincidir con setup_credenciales_dgii.py)
SERVICIO = "dgii_ofv"

# La lista de RNCs vive en un archivo aparte, fuera del código fuente y fuera
# de git (ver .gitignore), porque aunque el RNC no es un secreto de seguridad,
# revela qué clientes maneja este despacho. Aceptamos ambos nombres para no
# romper proyectos antiguos que usaban "config_rnc.json".
# Las claves NO están en ningún archivo: se recuperan del keyring del sistema
# operativo en tiempo de ejecución con keyring.get_password().
ARCHIVO_RNCS = Path(__file__).parent / "config_rncs.json"
ARCHIVO_RNC_LEGACY = Path(__file__).parent / "config_rnc.json"


def cargar_rncs():
    archivo = ARCHIVO_RNC_LEGACY if ARCHIVO_RNC_LEGACY.exists() else ARCHIVO_RNCS

    if not archivo.exists():
        print(f"❌ No se encontró config_rnc.json ni config_rncs.json. Crea uno con la lista de RNCs, por ejemplo:")
        print('   ["00109491563", "501481808", ...]')
        sys.exit(1)

    with open(archivo, encoding="utf-8") as f:
        return json.load(f)


def cargar_usuarios(rncs):
    """
    Construye la lista de usuarios a procesar, recuperando cada clave
    desde el keyring del sistema. Si a algún RNC le falta la clave
    guardada, se avisa y se omite (no se detiene todo el proceso).
    """
    usuarios = []
    faltantes = []

    for rnc in rncs:
        clave = keyring.get_password(SERVICIO, rnc)
        if clave is None:
            faltantes.append(rnc)
            continue
        usuarios.append({"rnc": rnc, "clave": clave})

    if faltantes:
        print("⚠️  No se encontró clave guardada en el keyring para estos RNC (se omitirán):")
        for rnc in faltantes:
            print(f"   - {rnc}")
        print("   Ejecuta setup_credenciales_dgii.py para registrarlas.\n")

    if not usuarios:
        print("❌ No hay credenciales disponibles. Nada que procesar.")
        sys.exit(1)

    return usuarios


hoy = datetime.now()
mes_anterior = hoy.replace(day=1) - timedelta(days=1)
periodo = mes_anterior.strftime("%Y%m")


def obtener_numero_badge(elemento):
    """Obtiene el número entero de un badge de mensajes."""
    try:
        texto = (elemento.text or "").strip()
        if not texto:
            return 0
        texto = texto.replace("(", "").replace(")", "").replace(".", "").replace(",", "")
        return int(texto)
    except (ValueError, TypeError, AttributeError):
        return 0


def procesar_mensajes_dgii(driver):
    """Procesa notificaciones y mensajes pendientes después del login."""
    try:
        try:
            mensaje = WebDriverWait(driver, 8).until(
                EC.visibility_of_element_located((By.XPATH, '//*[@id="lblMensaje"]'))
            )
            print(f"📢 Mensaje DGII: {mensaje.text}")
            WebDriverWait(driver, 5).until(
                EC.element_to_be_clickable((By.XPATH, '//*[@id="cboxClose"]'))
            ).click()
            print("✅ Popup cerrado")
        except TimeoutException:
            print("ℹ️ No apareció el popup lblMensaje")

        try:
            badge_notificacion = WebDriverWait(driver, 5).until(
                EC.presence_of_element_located(
                    (By.XPATH, '//*[@id="ctl00_ContentPlaceHolder1_badgeNotificacion"]')
                )
            )
        except TimeoutException:
            badge_notificacion = None

        if badge_notificacion is not None:
            cantidad = obtener_numero_badge(badge_notificacion)
            print(f"🔔 Notificaciones pendientes: {cantidad}")
            while cantidad > 0:
                WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, '//*[@id="ctl00_ContentPlaceHolder1_GVMensajes_ctl02_Enlace_47245731"]'))
                ).click()
                WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, '//*[@id="ctl00_ContentPlaceHolder1_btnSig"]'))
                ).click()
                cantidad = obtener_numero_badge(
                    WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.XPATH, '//*[@id="ctl00_ContentPlaceHolder1_badgeNotificacion"]'))
                    )
                )
                print(f"🔔 Notificaciones pendientes: {cantidad}")
            print("✅ Verificación de notificaciones finalizada")

        try:
            WebDriverWait(driver, 5).until(
                EC.presence_of_element_located((By.XPATH, '//*[@id="alert"]/a/div[2]'))
            )
        except TimeoutException:
            print("ℹ️ No hay mensajes pendientes para este usuario")
            return

        badge_mensajes = WebDriverWait(driver, 8).until(
            EC.presence_of_element_located((By.XPATH, '//*[@id="ctl00_ContentPlaceHolder1_badgeMensajes"]'))
        )
        cantidad = obtener_numero_badge(badge_mensajes)
        print(f"📨 Mensajes pendientes: {cantidad}")
        if cantidad > 0:
            WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, '//*[@id="ctl00_ContentPlaceHolder1_btnMensaje"]'))
            ).click()
            while cantidad > 0:
                WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, '//*[@id="ctl00_ContentPlaceHolder1_GVMensajes_ctl02_Enlace_47351055"]'))
                ).click()
                WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, '//*[@id="ctl00_ContentPlaceHolder1_btnSig"]/span'))
                ).click()
                cantidad = obtener_numero_badge(
                    WebDriverWait(driver, 5).until(
                        EC.presence_of_element_located((By.XPATH, '//*[@id="ctl00_ContentPlaceHolder1_badgeMensajes"]'))
                    )
                )
                print(f"📨 Mensajes pendientes: {cantidad}")

        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, '//*[@id="ctl00_ContentPlaceHolder1_btnTodosMensajes"]'))
        ).click()
        checkbox = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, '//*[@id="ctl00_ContentPlaceHolder1_tablaTextoTipoMensaje"]/tbody/tr/td[1]/input'))
        )
        if not checkbox.is_selected():
            checkbox.click()
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, '//*[@id="ctl00_ContentPlaceHolder1_btnEliminarTodos"]'))
        ).click()
        try:
            WebDriverWait(driver, 3).until(EC.alert_is_present())
            driver.switch_to.alert.accept()
        except TimeoutException:
            ActionChains(driver).send_keys(Keys.ENTER).perform()
        print("🗑️ Mensajes eliminados")

    except Exception as e:
        print(f"⚠️ Error procesando mensajes DGII: {e}")


def presentar_declaracion(driver, index_impuesto, escribir_periodo=True, log=print):
    # Verificar que el menú esté disponible y hacer clic
    try:
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, "2187"))
        ).click()
    except Exception as e:
        log(f"⚠️  Menú principal no disponible: {e}")
        return False

    # Verificar que el formulario esté disponible
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_ddlImpuesto"))
        )
    except Exception as e:
        log(f"⚠️  Formulario no disponible: {e}")
        return False

    Select(driver.find_element(By.ID, "ctl00_ContentPlaceHolder1_ddlImpuesto")).select_by_index(index_impuesto)

    if escribir_periodo:
        try:
            input_periodo = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_txtPeriodo"))
            )
            input_periodo.clear()
            input_periodo.send_keys(periodo)
        except Exception as e:
            log(f"⚠️  Campo período no disponible: {e}")
            return False

    try:
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, "ctl00_ContentPlaceHolder1_btnPresentar"))
        ).click()
    except Exception as e:
        log(f"⚠️  Botón presentar no disponible: {e}")
        return False

    # Regresar al menú principal solo si no es el último formulario (paso 4)
    if escribir_periodo:
        try:
            # Vuelve a buscar el elemento cada vez
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.XPATH, '//*[@id="menus"]/li[1]/a'))
            )
            WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, '//*[@id="menus"]/li[1]/a'))
            ).click()
        except Exception as e:
            log(f"⚠️  No se pudo regresar al menú principal: {e}")
            return False

    return True


def presentar_declaraciones_cero(driver, log=print):
    declaraciones = (
        ("IR3", 1, True),
        ("606", 3, True),
        ("607", 4, True),
        ("ITBIS", 2, False),
    )
    for nombre, index_impuesto, escribir_periodo in declaraciones:
        log(f"Presentando declaración {nombre}.")
        if not presentar_declaracion(
            driver,
            index_impuesto=index_impuesto,
            escribir_periodo=escribir_periodo,
            log=log,
        ):
            log(f"❌ Se detuvo el proceso; no se pudo completar {nombre}.")
            return False
    log("✅ Declaraciones en cero completadas.")
    return True


def main():
    from eliminarMensajesDgii import main as ejecutar_flujo_por_usuario

    return ejecutar_flujo_por_usuario(presentar_declaraciones=presentar_declaraciones_cero)


if __name__ == "__main__":
    sys.exit(main())
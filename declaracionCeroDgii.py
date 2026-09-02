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
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from datetime import datetime, timedelta
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains

# Namespace usado en el keyring (debe coincidir con setup_credenciales_dgii.py)
SERVICIO = "dgii_ofv"

# La lista de RNCs vive en un archivo aparte (config_rncs.json), fuera del
# código fuente y fuera de git (ver .gitignore), porque aunque el RNC no es
# un secreto de seguridad, revela qué clientes maneja este despacho.
# Las claves NO están en ningún archivo: se recuperan del keyring del
# sistema operativo en tiempo de ejecución con keyring.get_password().
ARCHIVO_RNCS = Path(__file__).parent / "config_rncs.json"


def cargar_rncs():
    if not ARCHIVO_RNCS.exists():
        print(f"❌ No se encontró {ARCHIVO_RNCS.name}. Crea ese archivo con la lista de RNCs, por ejemplo:")
        print('   ["00109491563", "501481808", ...]')
        sys.exit(1)

    with open(ARCHIVO_RNCS, encoding="utf-8") as f:
        return json.load(f)


RNCS = cargar_rncs()


def cargar_usuarios():
    """
    Construye la lista de usuarios a procesar, recuperando cada clave
    desde el keyring del sistema. Si a algún RNC le falta la clave
    guardada, se avisa y se omite (no se detiene todo el proceso).
    """
    usuarios = []
    faltantes = []

    for rnc in RNCS:
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
    """Verifica primero el popup de mensajes y luego las notificaciones del usuario."""
    try:
        # 1) Comprobar si aparece el popup con lblMensaje
        try:
            mensaje = WebDriverWait(driver, 8).until(
                EC.visibility_of_element_located((By.XPATH, '//*[@id="lblMensaje"]'))
            )
            print(f"📢 Mensaje DGII: {mensaje.text}")
            driver.find_element(By.XPATH, '//*[@id="cboxClose"]').click()
            print("✅ Popup cerrado")

            # 2) Una vez cerrado, comprobar el botón de notificaciones
            try:
                badge_notificacion = WebDriverWait(driver, 8).until(
                    EC.presence_of_element_located((By.XPATH, '//*[@id="ctl00_ContentPlaceHolder1_badgeNotificacion"]'))
                )
                cantidad = obtener_numero_badge(badge_notificacion)
                print(f"🔔 Notificaciones pendientes: {cantidad}")

                while cantidad > 0:
                    try:
                        primer_mensaje = WebDriverWait(driver, 10).until(
                            EC.element_to_be_clickable(
                                (By.XPATH, '//*[@id="ctl00_ContentPlaceHolder1_GVMensajes_ctl02_Enlace_47245731"]')
                            )
                        )
                        primer_mensaje.click()
                    except Exception as e:
                        print(f"⚠️ No se pudo abrir el primer mensaje de notificaciones: {e}")
                        break

                    try:
                        btn_siguiente = WebDriverWait(driver, 10).until(
                            EC.element_to_be_clickable((By.XPATH, '//*[@id="ctl00_ContentPlaceHolder1_btnSig"]'))
                        )
                        btn_siguiente.click()
                    except Exception as e:
                        print(f"⚠️ No se pudo avanzar al siguiente mensaje: {e}")
                        break

                    try:
                        badge_notificacion = WebDriverWait(driver, 5).until(
                            EC.presence_of_element_located((By.XPATH, '//*[@id="ctl00_ContentPlaceHolder1_badgeNotificacion"]'))
                        )
                        cantidad = obtener_numero_badge(badge_notificacion)
                        print(f"🔔 Notificaciones pendientes: {cantidad}")
                    except Exception:
                        cantidad = 0
                        break

                print("✅ Verificación de notificaciones finalizada")
            except TimeoutException:
                print("ℹ️ No hay botón de notificaciones visible para este usuario")

        except TimeoutException:
            print("ℹ️ No apareció el popup lblMensaje; se continúa con la verificación del otro mensaje.")

        # 3) Verificación del flujo actual de mensajes (siempre se ejecuta cuando no aparece popup)
        try:
            WebDriverWait(driver, 8).until(
                EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_GVMensajes"))
            )
        except TimeoutException:
            print("ℹ️ No apareció la grilla de mensajes para este usuario.")
            return

        while True:
            try:
                badge = driver.find_element(By.ID, "ctl00_ContentPlaceHolder1_badgeTodos")
            except Exception:
                break

            pendientes = obtener_numero_badge(badge)
            print(f"📨 Mensajes pendientes: {pendientes}")

            if pendientes <= 0:
                break

            try:
                mensajes = driver.find_elements(By.CSS_SELECTOR, "a.enlace-asunto")
                if not mensajes:
                    break

                mensajes[0].click()
                WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.ID, "ctl00_ContentPlaceHolder1_btnTodosMensajes"))
                ).click()
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_GVMensajes"))
                )
            except Exception as e:
                print(f"⚠️ No se pudo recorrer el listado de mensajes: {e}")
                break

        print("✅ Se revisó el listado de mensajes del usuario")

        # 4) Eliminar mensajes si son eliminables
        try:
            driver.find_element(By.ID, "ctl00_ContentPlaceHolder1_btnTodosMensajes").click()
            WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable(
                    (By.XPATH, '//*[@id="ctl00_ContentPlaceHolder1_tablaTextoTipoMensaje"]/tbody/tr/td[1]/input')
                )
            )

            checkbox = driver.find_element(
                By.XPATH,
                '//*[@id="ctl00_ContentPlaceHolder1_tablaTextoTipoMensaje"]/tbody/tr/td[1]/input'
            )
            if not checkbox.is_selected():
                checkbox.click()

            driver.find_element(By.ID, "ctl00_ContentPlaceHolder1_btnEliminarTodos").click()

            try:
                WebDriverWait(driver, 3).until(EC.alert_is_present())
                driver.switch_to.alert.accept()
                print("✅ Alerta de confirmación aceptada")
            except TimeoutException:
                ActionChains(driver).send_keys(Keys.ENTER).perform()
                print("✅ Enter enviado para confirmar eliminación")

            print("🗑️ Mensajes eliminados")

            WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, '//*[@id="menus"]/li[1]/a'))
            ).click()
            print("🏠 Regresando al inicio")

        except TimeoutException:
            print("ℹ️ No aparecieron mensajes eliminables para este usuario")
        except Exception as e:
            print(f"⚠️ Error eliminando mensajes: {e}")

    except Exception as e:
        print(f"⚠️ Error procesando mensajes DGII: {e}")


def presentar_declaracion(driver, index_impuesto, escribir_periodo=True):
    # Verificar que el menú esté disponible y hacer clic
    try:
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, "2187"))
        ).click()
    except Exception as e:
        print(f"⚠️  Menú principal no disponible: {e}")
        return

    # Verificar que el formulario esté disponible
    try:
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_ddlImpuesto"))
        )
    except Exception as e:
        print(f"⚠️  Formulario no disponible: {e}")
        return

    Select(driver.find_element(By.ID, "ctl00_ContentPlaceHolder1_ddlImpuesto")).select_by_index(index_impuesto)

    if escribir_periodo:
        try:
            input_periodo = WebDriverWait(driver, 10).until(
                EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_txtPeriodo"))
            )
            input_periodo.clear()
            input_periodo.send_keys(periodo)
        except Exception as e:
            print(f"⚠️  Campo período no disponible: {e}")
            return

    try:
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.ID, "ctl00_ContentPlaceHolder1_btnPresentar"))
        ).click()
    except Exception as e:
        print(f"⚠️  Botón presentar no disponible: {e}")
        return

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
            print(f"⚠️  No se pudo regresar al menú principal: {e}")


def main():
    usuarios = cargar_usuarios()

    options = webdriver.ChromeOptions()
    options.add_argument("--start-maximized")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    driver.get("https://dgii.gov.do/OFV/login.aspx")

    for user in usuarios:
        try:
            print(f"🔐 Iniciando sesión con RNC: {user['rnc']}")

            # Ir siempre a la página de login antes de cada usuario
            driver.get("https://dgii.gov.do/OFV/login.aspx")
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_txtUsuario"))
                )
            except Exception as e:
                print(f"❌ No se encontró campo usuario para RNC {user['rnc']}: {e}")
                continue

            driver.find_element(By.ID, "ctl00_ContentPlaceHolder1_txtUsuario").clear()
            driver.find_element(By.ID, "ctl00_ContentPlaceHolder1_txtUsuario").send_keys(user["rnc"])
            driver.find_element(By.ID, "ctl00_ContentPlaceHolder1_txtPassword").clear()
            driver.find_element(By.ID, "ctl00_ContentPlaceHolder1_txtPassword").send_keys(user["clave"])
            driver.find_element(By.ID, "ctl00_ContentPlaceHolder1_BtnAceptar").click()

            # Si aparece popup, cerrarlo
            procesar_mensajes_dgii(driver)

            # Verificar si el login fue exitoso
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.ID, "2187"))
                )
            except Exception as e:
                print(f"❌ Login fallido para RNC {user['rnc']}: {e}")
                continue

            # Paso 1: IR3
            presentar_declaracion(driver, index_impuesto=1)

            # Paso 2: 606
            presentar_declaracion(driver, index_impuesto=3)

            # Paso 3: 607
            presentar_declaracion(driver, index_impuesto=4)

            # Paso 4: ITBIS (NO escribir período, solo hacer clic en presentar)
            presentar_declaracion(driver, index_impuesto=2, escribir_periodo=False)

            # Cerrar sesión
            try:
                WebDriverWait(driver, 10).until(
                    EC.element_to_be_clickable((By.XPATH, '//*[@id="menus"]/li[5]/a'))
                ).click()
            except Exception as e:
                print(f"⚠️  No se pudo cerrar sesión para RNC {user['rnc']}: {e}")

            # Esperar a que vuelva la pantalla de login antes de continuar con el siguiente usuario
            try:
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_txtUsuario"))
                )
            except Exception as e:
                print(f"⚠️  No volvió a la pantalla de login para RNC {user['rnc']}: {e}")

        except Exception as e:
            print(f"❌ Error general con RNC {user['rnc']}: {e}")
            try:
                driver.get("https://dgii.gov.do/OFV/login.aspx")
                WebDriverWait(driver, 10).until(
                    EC.presence_of_element_located((By.ID, "ctl00_ContentPlaceHolder1_txtUsuario"))
                )
            except Exception:
                pass

    driver.quit()
    print("✅ Proceso completado.")


if __name__ == "__main__":
    main()
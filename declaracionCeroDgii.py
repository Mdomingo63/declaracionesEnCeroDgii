from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select, WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from datetime import datetime, timedelta
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.keys import Keys

usuarios = [
    {"rnc": "00109491563", "clave": "aespinal63"},
    {"rnc": "501481808", "clave": "aperez08"},
    {"rnc": "00107853400", "clave": "cmota400"},
    {"rnc": "00108331513", "clave": "LULY5555"}, 
    {"rnc": "00112183710", "clave": "frank710"},
    {"rnc": "101594918", "clave": "hfagf"},
    {"rnc": "00105730089", "clave": "BwjM3bmOG89"},
    {"rnc": "101535393", "clave": "aetla"},
    {"rnc": "00117924779", "clave": "jvhr79"},
    {"rnc": "00105517940", "clave": "jbr21"}, 
    {"rnc": "22301207787", "clave": "javilla87"},  
    {"rnc": "132965701", "clave": "QADR5701"},
    {"rnc": "00109598946", "clave": "Margom3737"},
    {"rnc": "00114646516", "clave": "mfdl16"},
    {"rnc": "00116144742", "clave": "1n3fKXaa4Z742"},
    {"rnc": "00109465617", "clave": "Rcastillo17"},
    {"rnc": "00113180574", "clave": "w628HVRXh74"},
    {"rnc": "531597862", "clave": "YENI0062"}
]

hoy = datetime.now()
mes_anterior = hoy.replace(day=1) - timedelta(days=1)
periodo = mes_anterior.strftime("%Y%m")


def procesar_mensajes_dgii(driver):

    try:
        # Capturar popup
        mensaje = WebDriverWait(driver, 10).until(
            EC.visibility_of_element_located(
                (By.ID, "lblMensaje")
            )
        )

        print(f"📢 Mensaje DGII: {mensaje.text}")

        # Cerrar popup
        driver.find_element(
            By.ID,
            "cboxClose"
        ).click()

        print("✅ Popup cerrado")

        # Esperar tabla de mensajes
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located(
                (
                    By.ID,
                    "ctl00_ContentPlaceHolder1_GVMensajes"
                )
            )
        )

        # Leer todos los mensajes pendientes
        while True:

            pendientes = int(
                driver.find_element(
                    By.ID,
                    "ctl00_ContentPlaceHolder1_badgeTodos"
                ).text.strip()
            )

            print(f"📨 Mensajes pendientes: {pendientes}")

            if pendientes == 0:
                break

            mensajes = driver.find_elements(
                By.CSS_SELECTOR,
                "a.enlace-asunto"
            )

            if not mensajes:
                break

            mensajes[0].click()

            # Esperar botón Todo
            WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable(
                    (
                        By.ID,
                        "ctl00_ContentPlaceHolder1_btnTodosMensajes"
                    )
                )
            ).click()

            # Esperar que regrese a la tabla
            WebDriverWait(driver, 10).until(
                EC.presence_of_element_located(
                    (
                        By.ID,
                        "ctl00_ContentPlaceHolder1_GVMensajes"
                    )
                )
            )

        print("✅ Todos los mensajes fueron leídos")

        # Ir a vista de todos los mensajes
        driver.find_element(
            By.ID,
            "ctl00_ContentPlaceHolder1_btnTodosMensajes"
        ).click()

        # Seleccionar mensajes eliminables
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    '//*[@id="ctl00_ContentPlaceHolder1_tablaTextoTipoMensaje"]/tbody/tr/td[1]/input'
                )
            )
        ).click()

        # Eliminar
        driver.find_element(
            By.ID,
            "ctl00_ContentPlaceHolder1_btnEliminarTodos"
        ).click()

        # Confirmar ventana emergente
        driver.switch_to.active_element.send_keys(Keys.ENTER)

        print("🗑️ Mensajes eliminados")

        # Volver a Inicio
        WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable(
                (
                    By.XPATH,
                    '//*[@id="menus"]/li[1]/a'
                )
            )
        ).click()

        print("🏠 Regresando al inicio")

    except TimeoutException:
        print("ℹ️ No apareció ventana de mensajes")

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
        except:
            pass

driver.quit()
print("✅ Proceso completado.")
import json
import locale
import re
import sys
import time
import threading
from io import BytesIO
from pathlib import Path
from typing import Optional
import keyring
import pytesseract
from PIL import Image, ImageOps
from selenium import webdriver
from selenium.webdriver.chrome.webdriver import WebDriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import (
    TimeoutException, NoSuchElementException, WebDriverException
)
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QLabel, QSpinBox
)
from PySide6.QtCore import QThread, Signal, QTimer

SERVICIO_KEYRING = "dgii_ofv"
RUTA_CONFIG_RNCS = Path(__file__).parent / "config_rncs.json"
RUTA_CONFIG_RNC_LEGACY = Path(__file__).parent / "config_rnc.json"
XPATH_CONTRIBUYENTE = '//*[@id="cabecera"]/div[3]/table/tbody/tr/td[2]/font/b'
XPATH_CONTENIDO_MENSAJE = '//*[@id="content_content_derecha"]/div[3]/div/div[2]/div/div/p[4]/img'
XPATH_ELIMINAR_MENSAJE = '//*[@id="ctl00_ContentPlaceHolder1_btnEliminar"]'
XPATH_BADGE_MENSAJES = '//*[@id="ctl00_ContentPlaceHolder1_badgeMensajes"]'
XPATH_TOKEN_TARJETA = '//*[@id="ctl00_ContentPlaceHolder1_txtpasscodeTarjetaToken"]'
XPATH_CONTINUAR_TOKEN = '//*[@id="ctl00_ContentPlaceHolder1_BtnAceptarTarjetaToken"]'
XPATH_PRIMER_MENSAJE = '//*[@id="ctl00_ContentPlaceHolder1_GVMensajes_ctl02_48014729"]'
XPATH_PRIMER_MENSAJE_TABLA = '//*[@id="ctl00_ContentPlaceHolder1_GVMensajes"]//tr[td]//a'
TIEMPO_ESPERA_TOKEN = 180
TIEMPO_ESTABLE_TOKEN = 2


class AutomationWorker(QThread):
    """Hilo que ejecuta toda la automatización con Selenium."""

    log_signal = Signal(str)
    finished_signal = Signal(str)
    review_signal = Signal(str, str, int, int, str)

    def __init__(self, cuentas, segundos_revision):
        super().__init__()
        self.cuentas = cuentas
        self.segundos_revision = segundos_revision
        self.driver: Optional[WebDriver] = None
        self.driver_wait: Optional[WebDriverWait] = None
        self._decision_event = threading.Event()
        self._stop_event = threading.Event()
        self._decision = None
        self._idioma_ocr = None
        self._aviso_modelo_espanol = False

    def log(self, msg):
        self.log_signal.emit(msg)

    def decidir(self, decision):
        self._decision = decision
        self._decision_event.set()

    def detener(self):
        self._stop_event.set()
        self._decision_event.set()

    def run(self):
        resultados = []
        try:
            for rnc, clave in self.cuentas:
                if self._stop_event.is_set():
                    break
                try:
                    nombre, revisados, eliminados = self._procesar_cuenta(rnc, clave)
                    resultados.append(
                        f"{rnc} ({nombre}): {revisados} revisados, {eliminados} eliminados"
                    )
                except Exception as e:
                    resultados.append(f"{rnc}: error ({e})")
                    self.log(f"{rnc}: no se pudo completar la cuenta ({e})")
                finally:
                    self._cerrar_navegador()
            estado = "Detenido por el usuario. " if self._stop_event.is_set() else "Proceso terminado. "
            self.finished_signal.emit(estado + " | ".join(resultados))
        except Exception as e:
            self.finished_signal.emit(f"Error del proceso: {e}")

    # ------------------------------------------------------------------
    # Flujo principal
    # ------------------------------------------------------------------
    def _procesar_cuenta(self, usuario, clave):
        # --- Configurar y abrir navegador ---
        options = Options()
        # options.add_argument('--headless')  # Descomentar para modo sin ventana
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--start-maximized')

        self.driver = webdriver.Chrome(options=options)
        self.driver_wait = WebDriverWait(self.driver, 20)

        url = "https://www.dgii.gov.do/OFV/login.aspx"
        self.driver.get(url)

        campo_usuario = self.driver_wait.until(
            EC.presence_of_element_located(
                (By.XPATH, '//*[@id="ctl00_ContentPlaceHolder1_txtUsuario"]')
            )
        )
        campo_usuario.clear()
        campo_usuario.send_keys(usuario)

        campo_clave = self.driver.find_element(
            By.XPATH, '//*[@id="ctl00_ContentPlaceHolder1_txtPassword"]'
        )
        campo_clave.clear()
        campo_clave.send_keys(clave)

        btn_aceptar = self.driver.find_element(
            By.XPATH, '//*[@id="ctl00_ContentPlaceHolder1_BtnAceptar"]'
        )
        btn_aceptar.click()
        nombre = self._completar_inicio_sesion()
        if nombre is None:
            return usuario, 0, 0
        self.log(f"Cuenta {usuario}: {nombre}")

        try:
            alerta = WebDriverWait(self.driver, 8).until(
                EC.presence_of_element_located(
                    (By.XPATH, '//*[@id="alert"]/a/div[2]')
                )
            )
            alerta.click()
            time.sleep(3)
        except TimeoutException:
            self.log(f"{nombre}: no hay avisos pendientes.")
            return nombre, 0, 0

        badge = self.driver_wait.until(
            EC.presence_of_element_located(
                (By.XPATH, '//*[@id="ctl00_ContentPlaceHolder1_badgeMensajes"]')
            )
        )
        cantidad = self._obtener_cantidad(badge)
        if cantidad == 0:
            self._cerrar_sesion()
            return nombre, 0, 0

        primer_mensaje = self.driver_wait.until(
            EC.element_to_be_clickable(
                (By.XPATH,
                 '//*[@id="ctl00_ContentPlaceHolder1_GVMensajes"]//tr[td]//a')
            )
        )
        primer_mensaje.click()
        time.sleep(3)

        revisados = 0
        eliminados = 0
        while not self._stop_event.is_set() and revisados < cantidad:
            numero_mensaje = revisados + 1
            resumen = self._resumen_mensaje()
            self._decision = None
            self._decision_event.clear()
            self.review_signal.emit(usuario, nombre, numero_mensaje, cantidad, resumen)
            self._decision_event.wait()

            if self._stop_event.is_set():
                break
            if self._decision == "eliminar":
                if self._eliminar_mensaje_actual():
                    eliminados += 1
                    self.log(f"{nombre}: mensaje {numero_mensaje} eliminado.")
                else:
                    self.log(
                        f"{nombre}: no se confirmó el borrado del mensaje {numero_mensaje}; "
                        "permanece abierto para otra decisión."
                    )
                    continue
            else:
                self.log(f"{nombre}: mensaje {numero_mensaje} conservado.")

            revisados += 1
            if self._decision == "eliminar" and self._cantidad_mensajes() == 0:
                self.log(f"{nombre}: no quedan mensajes pendientes.")
                break
            if revisados >= cantidad:
                break
            try:
                if self._decision == "eliminar":
                    WebDriverWait(self.driver, 10).until(
                        EC.any_of(
                            EC.element_to_be_clickable((By.XPATH, XPATH_PRIMER_MENSAJE)),
                            EC.element_to_be_clickable((By.XPATH, XPATH_PRIMER_MENSAJE_TABLA)),
                        )
                    ).click()
                else:
                    btn_siguiente = self.driver.find_element(
                        By.XPATH, '//*[@id="ctl00_ContentPlaceHolder1_btnSig"]/span'
                    )
                    btn_siguiente.click()
                time.sleep(2)
            except NoSuchElementException:
                break

        self._cerrar_sesion()
        return nombre, revisados, eliminados

    def _completar_inicio_sesion(self):
        if self.driver is None:
            raise RuntimeError("el navegador no está disponible")
        try:
            resultado = WebDriverWait(self.driver, 20).until(
                EC.any_of(
                    EC.visibility_of_element_located((By.XPATH, XPATH_TOKEN_TARJETA)),
                    EC.visibility_of_element_located((By.XPATH, XPATH_CONTRIBUYENTE)),
                )
            )
        except TimeoutException as e:
            raise RuntimeError(
                "no apareció el campo de tarjeta/token ni se confirmó el inicio de sesión"
            ) from e

        if resultado.get_attribute("id") != "ctl00_ContentPlaceHolder1_txtpasscodeTarjetaToken":
            return resultado.text.strip()

        self.log(
            "La DGII solicita tarjeta o token digital. Escríbelo en el navegador; "
            f"Continuar se pulsará automáticamente. Tienes hasta {TIEMPO_ESPERA_TOKEN // 60} minutos."
        )
        try:
            resultado.click()
        except WebDriverException:
            self.log("[AVISO] Haz clic manualmente en el campo de tarjeta/token para escribirlo.")

        limite = time.monotonic() + TIEMPO_ESPERA_TOKEN
        token_anterior = ""
        token_estable_desde = None
        token_enviado = False
        while time.monotonic() < limite and not self._stop_event.is_set():
            campos_token = self.driver.find_elements(By.XPATH, XPATH_TOKEN_TARJETA)
            if campos_token and not token_enviado:
                token_actual = campos_token[0].get_attribute("value") or ""
                ahora = time.monotonic()
                if token_actual and token_actual == token_anterior:
                    if token_estable_desde is not None and ahora - token_estable_desde >= TIEMPO_ESTABLE_TOKEN:
                        boton_continuar = WebDriverWait(self.driver, 10).until(
                            EC.element_to_be_clickable((By.XPATH, XPATH_CONTINUAR_TOKEN))
                        )
                        boton_continuar.click()
                        token_enviado = True
                        self.log("Token ingresado; se pulsó Continuar automáticamente.")
                else:
                    token_anterior = token_actual
                    token_estable_desde = ahora if token_actual else None

            contribuyentes = self.driver.find_elements(By.XPATH, XPATH_CONTRIBUYENTE)
            for contribuyente in contribuyentes:
                if contribuyente.is_displayed():
                    return contribuyente.text.strip()
            self._stop_event.wait(0.5)
        else:
            if self._stop_event.is_set():
                return None
            raise TimeoutError("no se confirmó el inicio de sesión con tarjeta o token")

    def _resumen_mensaje(self):
        driver_wait = self.driver_wait
        if self.driver is None or driver_wait is None:
            return "No se pudo leer el contenido del mensaje."
        try:
            imagen = driver_wait.until(
                EC.presence_of_element_located((By.XPATH, XPATH_CONTENIDO_MENSAJE))
            )
        except TimeoutException:
            return "No se encontró el contenido del mensaje en la página."

        texto_ocr = self._leer_imagen_con_ocr(imagen)
        if texto_ocr:
            return self._resumir_texto(texto_ocr)

        partes = [
            imagen.get_attribute("alt"),
            imagen.get_attribute("title"),
            imagen.get_attribute("aria-label"),
        ]
        for nivel in range(1, 6):
            xpath_padre = "/".join([".."] * nivel)
            try:
                texto = imagen.find_element(By.XPATH, xpath_padre).text.strip()
            except NoSuchElementException:
                continue
            if texto:
                partes.append(texto)
                break

        texto_mensaje = " ".join(parte.strip() for parte in partes if parte and parte.strip())
        if not texto_mensaje:
            return "El aviso aparece como imagen y no tiene texto accesible para resumir."
        return self._resumir_texto(texto_mensaje)

    def _leer_imagen_con_ocr(self, elemento):
        try:
            if self._idioma_ocr is None:
                codificacion_original = pytesseract.pytesseract.DEFAULT_ENCODING
                try:
                    pytesseract.pytesseract.DEFAULT_ENCODING = (
                        locale.getpreferredencoding(False) or "utf-8"
                    )
                    idiomas = set(pytesseract.get_languages(config=""))
                finally:
                    pytesseract.pytesseract.DEFAULT_ENCODING = codificacion_original
                if "spa" in idiomas:
                    self._idioma_ocr = "spa+eng" if "eng" in idiomas else "spa"
                else:
                    self._idioma_ocr = "eng" if "eng" in idiomas else next(
                        (idioma for idioma in sorted(idiomas) if idioma != "osd"), "eng"
                    )
                if "spa" not in idiomas and not self._aviso_modelo_espanol:
                    self.log("[AVISO] Tesseract no tiene modelo spa; OCR con eng puede ser menos preciso en español.")
                    self._aviso_modelo_espanol = True

            imagen = Image.open(BytesIO(elemento.screenshot_as_png)).convert("L")
            imagen = ImageOps.autocontrast(imagen)
            if imagen.width < 1200:
                imagen = imagen.resize((imagen.width * 2, imagen.height * 2))
            return pytesseract.image_to_string(
                imagen, lang=self._idioma_ocr, config="--psm 6"
            ).strip()
        except (OSError, UnicodeDecodeError, WebDriverException,
            pytesseract.TesseractError, pytesseract.TesseractNotFoundError) as e:
            self.log(f"[AVISO] OCR no disponible para este aviso; se usará texto accesible ({e}).")
            return ""

    def _resumir_texto(self, texto):
        texto = " ".join(texto.split())
        if not texto:
            return "Mensaje sin texto legible."
        oraciones = re.split(r"(?<=[.!?])\s+", texto)
        resumen = " ".join(oraciones[:3])
        return resumen[:600] + ("…" if len(resumen) > 600 else "")

    def _eliminar_mensaje_actual(self):
        if self.driver is None:
            return False
        try:
            mensaje_actual = self.driver.find_element(By.XPATH, XPATH_CONTENIDO_MENSAJE)
        except NoSuchElementException:
            return False
        cantidad_antes = self._cantidad_mensajes()
        if cantidad_antes is None:
            return False
        try:
            boton_eliminar = WebDriverWait(self.driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, XPATH_ELIMINAR_MENSAJE))
            )
            boton_eliminar.click()
        except TimeoutException:
            return False
        except WebDriverException:
            return False

        try:
            alerta = WebDriverWait(self.driver, 3).until(EC.alert_is_present())
            alerta.accept()
        except TimeoutException:
            try:
                ActionChains(self.driver).send_keys(Keys.ENTER).perform()
            except WebDriverException:
                return False

        def eliminacion_confirmada(driver):
            if EC.staleness_of(mensaje_actual)(driver):
                return True
            cantidad_actual = self._cantidad_mensajes()
            return cantidad_actual is not None and cantidad_actual < cantidad_antes

        try:
            WebDriverWait(self.driver, 10).until(eliminacion_confirmada)
        except TimeoutException:
            return False
        return True

    def _cantidad_mensajes(self):
        if self.driver is None:
            return None
        try:
            badge = WebDriverWait(self.driver, 5).until(
                EC.presence_of_element_located((By.XPATH, XPATH_BADGE_MENSAJES))
            )
        except TimeoutException:
            return None
        return self._obtener_cantidad(badge)

    # ------------------------------------------------------------------
    # Métodos auxiliares
    # ------------------------------------------------------------------
    def _obtener_cantidad(self, badge_element):
        """Extrae el número entero del texto del badge."""
        try:
            texto = badge_element.text.strip()
            # Si el texto tiene paréntesis, p. ej. "(5)", extraer solo el número
            texto = texto.strip("()")
            return int(texto)
        except (ValueError, AttributeError):
            return 0

    def _cerrar_sesion(self):
        """Hace click en el botón Salir del menú."""
        if self.driver is None:
            return
        try:
            btn_salir = self.driver.find_element(
                By.XPATH, '//*[@id="menus"]/li[5]/a'
            )
            btn_salir.click()
            self.log("Sesión cerrada correctamente.")
            time.sleep(2)
        except NoSuchElementException:
            self.log("[AVISO] No se pudo encontrar el botón de salir.")

    def _cerrar_navegador(self):
        """Cierra el navegador si está abierto."""
        if self.driver:
            try:
                self.driver.quit()
                self.log("Navegador cerrado.")
            except Exception:
                pass
            self.driver = None


# ======================================================================
# Interfaz gráfica con PySide6
# ======================================================================
class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("DGII - Automatización de Mensajes")
        self.setMinimumSize(650, 550)
        self.worker = None
        self.revision_pendiente = False
        self.segundos_restantes = 0
        self.timer_revision = QTimer(self)
        self.timer_revision.timeout.connect(self._actualizar_cuenta_regresiva)
        self._construir_ui()

    def _construir_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        opciones = QHBoxLayout()
        opciones.addWidget(QLabel("Pausa para leer cada mensaje (segundos):"))
        self.input_segundos = QSpinBox()
        self.input_segundos.setRange(0, 300)
        self.input_segundos.setValue(15)
        opciones.addWidget(self.input_segundos)
        opciones.addStretch()
        layout.addLayout(opciones)

        # --- Controles del proceso y revisión ---
        botones = QHBoxLayout()
        self.btn_iniciar = QPushButton("▶  Iniciar Proceso")
        self.btn_iniciar.clicked.connect(self._iniciar_proceso)

        self.btn_detener = QPushButton("■  Detener")
        self.btn_detener.clicked.connect(self._detener_proceso)
        self.btn_detener.setEnabled(False)

        self.btn_eliminar = QPushButton("Eliminar mensaje leído")
        self.btn_eliminar.clicked.connect(lambda: self._decidir_mensaje("eliminar"))
        self.btn_eliminar.setEnabled(False)

        self.btn_conservar = QPushButton("Conservar y siguiente")
        self.btn_conservar.clicked.connect(lambda: self._decidir_mensaje("conservar"))
        self.btn_conservar.setEnabled(False)

        botones.addWidget(self.btn_iniciar)
        botones.addWidget(self.btn_detener)
        botones.addWidget(self.btn_eliminar)
        botones.addWidget(self.btn_conservar)
        layout.addLayout(botones)

        # --- Área de logs ---
        layout.addWidget(QLabel("Registro de actividad:"))
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        layout.addWidget(self.log_area)

    # ------------------------------------------------------------------
    def _iniciar_proceso(self):
        archivo = RUTA_CONFIG_RNC_LEGACY if RUTA_CONFIG_RNC_LEGACY.exists() else RUTA_CONFIG_RNCS
        if not archivo.exists():
            self._agregar_log("[ERROR] No se encontró config_rnc.json ni config_rncs.json.")
            return

        try:
            with archivo.open(encoding="utf-8") as f:
                rncs = json.load(f)
            if not isinstance(rncs, list) or not all(isinstance(rnc, str) for rnc in rncs):
                raise ValueError("la configuración debe ser una lista JSON de RNC como texto")
        except (OSError, json.JSONDecodeError, ValueError) as e:
            self._agregar_log(f"[ERROR] Configuración de RNC inválida: {e}")
            return

        cuentas = []
        sin_clave = 0
        for rnc in dict.fromkeys(rnc.strip() for rnc in rncs if rnc.strip()):
            try:
                clave = keyring.get_password(SERVICIO_KEYRING, rnc)
            except Exception as e:
                self._agregar_log(f"[ERROR] No se pudo consultar el keyring: {e}")
                return
            if clave:
                cuentas.append((rnc, clave))
            else:
                sin_clave += 1
        if not cuentas:
            self._agregar_log("[ERROR] No hay credenciales guardadas para los RNC configurados.")
            return

        self.log_area.clear()
        self._agregar_log(f"Iniciando {len(cuentas)} cuentas; {sin_clave} sin clave guardada se omitirán.")
        self.btn_iniciar.setEnabled(False)
        self.btn_detener.setEnabled(True)
        self.input_segundos.setEnabled(False)
        self.worker = AutomationWorker(cuentas, self.input_segundos.value())
        self.worker.log_signal.connect(self._agregar_log)
        self.worker.review_signal.connect(self._mostrar_revision)
        self.worker.finished_signal.connect(self._proceso_finalizado)
        self.worker.start()

    def _detener_proceso(self):
        if self.worker and self.worker.isRunning():
            self.worker.detener()
            self._agregar_log("Se detendrá al terminar el mensaje actual.")
            self.btn_detener.setEnabled(False)

    def _mostrar_revision(self, rnc, nombre, numero, total, resumen):
        self.revision_pendiente = True
        self.segundos_restantes = self.input_segundos.value()
        self._agregar_log(f"\n{nombre} ({rnc}) | Mensaje {numero} de {total}")
        self._agregar_log(f"Resumen: {resumen}")
        self._agregar_log("Esperando tu decisión; no se eliminará ni avanzará automáticamente.")
        self.btn_eliminar.setEnabled(False)
        self.btn_conservar.setEnabled(False)
        if self.segundos_restantes == 0:
            self._habilitar_decision()
        else:
            self._agregar_log(f"Decisión disponible en {self.segundos_restantes} segundos.")
            self.timer_revision.start(1000)

    def _actualizar_cuenta_regresiva(self):
        self.segundos_restantes -= 1
        if self.segundos_restantes <= 0:
            self.timer_revision.stop()
            self._habilitar_decision()

    def _habilitar_decision(self):
        self.btn_eliminar.setEnabled(True)
        self.btn_conservar.setEnabled(True)

    def _decidir_mensaje(self, decision):
        if self.revision_pendiente and self.worker:
            self.revision_pendiente = False
            self.timer_revision.stop()
            self.btn_eliminar.setEnabled(False)
            self.btn_conservar.setEnabled(False)
            self.worker.decidir(decision)

    def _proceso_finalizado(self, mensaje):
        self.timer_revision.stop()
        self.revision_pendiente = False
        self._agregar_log(f"\n{mensaje}")
        self.btn_iniciar.setEnabled(True)
        self.btn_detener.setEnabled(False)
        self.btn_eliminar.setEnabled(False)
        self.btn_conservar.setEnabled(False)
        self.input_segundos.setEnabled(True)
        self.worker = None

    def _agregar_log(self, texto):
        self.log_area.append(texto)
        bar = self.log_area.verticalScrollBar()
        bar.setValue(bar.maximum())


# ======================================================================
# Punto de entrada
# ======================================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    ventana = MainWindow()
    ventana.show()
    sys.exit(app.exec())

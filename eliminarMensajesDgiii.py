import json
import sys
import time
import threading
from pathlib import Path
from typing import Optional
import keyring
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

URL_LOGIN = "https://www.dgii.gov.do/OFV/login.aspx"
XPATH_USUARIO = '//*[@id="ctl00_ContentPlaceHolder1_txtUsuario"]'
XPATH_CLAVE = '//*[@id="Table2"]/tbody/tr[3]/td[2]//input'
XPATH_TOKEN = '//*[@id="ctl00_ContentPlaceHolder1_txtpasscodeTarjetaToken"]'
XPATH_ENTRAR = '//*[@id="ctl00_ContentPlaceHolder1_BtnAceptar"]'
XPATH_CONTINUAR_TOKEN = '//*[@id="ctl00_ContentPlaceHolder1_BtnAceptarTarjetaToken"]'
XPATH_CONTRIBUYENTE = '//*[@id="cabecera"]/div[3]/table/tbody/tr/td[2]/font/b'
XPATH_POPUP = '//*[@id="lblMensaje"]'
XPATH_CERRAR_POPUP = '//*[@id="cboxClose"]'
XPATH_ALERTA = '//*[@id="alert"]/a/div[2]'
XPATH_BADGE_NOTIFICACIONES = '//*[@id="ctl00_ContentPlaceHolder1_badgeNotificacion"]'
XPATH_BADGE_MENSAJES = '//*[@id="ctl00_ContentPlaceHolder1_badgeMensajes"]'
XPATH_BOTON_MENSAJES = '//*[@id="ctl00_ContentPlaceHolder1_btnMensaje"]'
XPATH_TABLA = '//*[@id="ctl00_ContentPlaceHolder1_GVMensajes"]'
XPATH_SIGUIENTE = '//*[@id="ctl00_ContentPlaceHolder1_btnSig"]'
XPATH_ELIMINAR = '//*[@id="ctl00_ContentPlaceHolder1_btnEliminar"]'
XPATH_SALIR = '//*[@id="menus"]/li[5]/a'
TIEMPO_ESPERA_TOKEN = 180
TIEMPO_ESTABLE_TOKEN = 2


def xpaths_enlace_mensaje(indice):
    """XPaths candidatos del enlace del mensaje en la fila `indice` (base 1) de la tabla."""
    return (
        f'({XPATH_TABLA}//tr[td]/td[2]//a)[{indice}]',
        f'({XPATH_TABLA}//tr[td]//a)[{indice}]',
    )


class AutomationWorker(QThread):
    """Hilo que ejecuta toda la automatización con Selenium."""

    log_signal = Signal(str)
    finished_signal = Signal(str)
    review_signal = Signal(str, str, int, int)

    def __init__(self, cuentas, segundos_revision):
        super().__init__()
        self.cuentas = cuentas
        self.segundos_revision = segundos_revision
        self.driver: Optional[WebDriver] = None
        self._decision_event = threading.Event()
        self._stop_event = threading.Event()
        self._decision = None

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
            self._abrir_navegador()
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
                    self._cerrar_sesion()
            estado = "Detenido por el usuario. " if self._stop_event.is_set() else "Proceso terminado. "
            self.finished_signal.emit(estado + " | ".join(resultados))
        except Exception as e:
            self.finished_signal.emit(f"Error del proceso: {e}")
        finally:
            self._cerrar_navegador()

    # ------------------------------------------------------------------
    # Flujo principal por cuenta
    # ------------------------------------------------------------------
    def _procesar_cuenta(self, usuario, clave):
        nombre = self._iniciar_sesion(usuario, clave)
        if nombre is None:
            return usuario, 0, 0
        self.log(f"Cuenta {usuario}: {nombre}")

        notificaciones = 0
        # El emergente sale al iniciar sesión cuando hay Notificaciones obligatorias.
        if self._hay_popup_notificaciones():
            self.log(f"{nombre}: aviso emergente detectado; se cierra para ver las notificaciones.")
            self._cerrar_popup()
            self._stop_event.wait(2)
            notificaciones = self._procesar_notificaciones(nombre)
        else:
            self.log(f"{nombre}: no apareció el aviso emergente; se continúa con los mensajes.")
            if self._visible(XPATH_ALERTA, 5):
                self._click(XPATH_ALERTA)
                self._stop_event.wait(3)

        revisados, eliminados = self._procesar_mensajes(usuario, nombre)
        if notificaciones == 0 and revisados == 0 and not self._stop_event.is_set():
            self.log(f"{nombre}: sin notificaciones ni mensajes; se pasa a la siguiente cuenta.")
        self._cerrar_sesion()
        return nombre, revisados, eliminados

    # ------------------------------------------------------------------
    # Inicio de sesión
    # ------------------------------------------------------------------
    def _iniciar_sesion(self, usuario, clave):
        driver = self._driver()
        driver.get(URL_LOGIN)

        campo_usuario = WebDriverWait(driver, 20).until(
            EC.presence_of_element_located((By.XPATH, XPATH_USUARIO))
        )
        campo_usuario.clear()
        campo_usuario.send_keys(usuario)

        campo_clave = driver.find_element(By.XPATH, XPATH_CLAVE)
        campo_clave.clear()
        campo_clave.send_keys(clave)

        campo_token = self._visible(XPATH_TOKEN, 3)
        if campo_token is None:
            self._click(XPATH_ENTRAR)
            campo_token = self._visible(XPATH_TOKEN, 5)

        if campo_token is not None and not self._esperar_token(campo_token):
            return None

        contribuyente = self._visible(XPATH_CONTRIBUYENTE, 20)
        if contribuyente is None:
            raise RuntimeError("no se confirmó el inicio de sesión")
        return contribuyente.text.strip()

    def _esperar_token(self, campo_token):
        """Espera a que el usuario escriba el token/tarjeta y pulsa Continuar."""
        self.log(
            "La DGII solicita tarjeta o token digital. Escríbelo en el navegador; "
            f"Continuar se pulsará automáticamente. Tienes hasta {TIEMPO_ESPERA_TOKEN // 60} minutos."
        )
        try:
            campo_token.click()
        except WebDriverException:
            self.log("[AVISO] Haz clic manualmente en el campo de tarjeta/token para escribirlo.")

        limite = time.monotonic() + TIEMPO_ESPERA_TOKEN
        anterior = ""
        estable_desde = time.monotonic()
        while time.monotonic() < limite and not self._stop_event.is_set():
            try:
                actual = campo_token.get_attribute("value") or ""
            except WebDriverException:
                break
            ahora = time.monotonic()
            if actual and actual == anterior:
                if ahora - estable_desde >= TIEMPO_ESTABLE_TOKEN:
                    self._click(XPATH_CONTINUAR_TOKEN)
                    self.log("Token ingresado; se pulsó Continuar automáticamente.")
                    return True
            else:
                anterior = actual
                estable_desde = ahora
            self._stop_event.wait(0.5)

        if self._stop_event.is_set():
            return False
        raise TimeoutError("no se ingresó la tarjeta o token a tiempo")

    # ------------------------------------------------------------------
    # Notificaciones (no se pueden eliminar)
    # ------------------------------------------------------------------
    def _procesar_notificaciones(self, nombre):
        total = self._cantidad(XPATH_BADGE_NOTIFICACIONES)
        self.log(f"{nombre}: {total} notificaciones.")
        if total == 0 or not self._abrir_mensaje(1):
            return 0

        leidas = 1
        while not self._stop_event.is_set() and leidas < total:
            if self._cantidad(XPATH_BADGE_NOTIFICACIONES) == 0:
                break
            try:
                self._click(XPATH_SIGUIENTE)
            except (TimeoutException, NoSuchElementException):
                break
            self._stop_event.wait(2)
            leidas += 1
        self.log(f"{nombre}: {leidas} notificaciones leídas.")
        return leidas

    # ------------------------------------------------------------------
    # Mensajes (el usuario lee y decide)
    # ------------------------------------------------------------------
    def _procesar_mensajes(self, usuario, nombre):
        total = self._cantidad(XPATH_BADGE_MENSAJES)
        self.log(f"{nombre}: {total} mensajes.")
        if total == 0:
            return 0, 0

        if self._visible(XPATH_BOTON_MENSAJES, 3):
            self._click(XPATH_BOTON_MENSAJES)
            self._stop_event.wait(2)
        if not self._abrir_mensaje(1):
            self.log(f"{nombre}: no se encontró ningún mensaje en la tabla.")
            return 0, 0

        revisados = eliminados = conservados = 0
        while not self._stop_event.is_set() and revisados < total:
            self._decision = None
            self._decision_event.clear()
            self.review_signal.emit(usuario, nombre, revisados + 1, total)
            self._decision_event.wait()
            if self._stop_event.is_set():
                break

            if self._decision == "eliminar":
                if not self._eliminar_mensaje_actual():
                    self.log(f"{nombre}: no se confirmó el borrado; el mensaje sigue abierto.")
                    continue
                eliminados += 1
                revisados += 1
                self.log(f"{nombre}: mensaje eliminado.")
                if self._cantidad(XPATH_BADGE_MENSAJES) == 0:
                    break
                # Los mensajes conservados quedan al inicio de la tabla.
                if not self._abrir_mensaje(conservados + 1):
                    break
            else:
                conservados += 1
                revisados += 1
                self.log(f"{nombre}: mensaje conservado.")
                if revisados >= total:
                    break
                try:
                    self._click(XPATH_SIGUIENTE)
                except (TimeoutException, NoSuchElementException):
                    break
                self._stop_event.wait(2)

        return revisados, eliminados

    def _eliminar_mensaje_actual(self):
        driver = self._driver()
        try:
            boton = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.XPATH, XPATH_ELIMINAR))
            )
            boton.click()
        except (TimeoutException, WebDriverException):
            return False

        try:
            alerta = WebDriverWait(driver, 3).until(EC.alert_is_present())
            self.log(f"Confirmación de la página: \"{alerta.text}\"; se acepta.")
            alerta.accept()
        except TimeoutException:
            try:
                ActionChains(driver).send_keys(Keys.ENTER).perform()
            except WebDriverException:
                return False

        try:
            WebDriverWait(driver, 10).until(EC.staleness_of(boton))
        except TimeoutException:
            return False
        return True

    # ------------------------------------------------------------------
    # Auxiliares
    # ------------------------------------------------------------------
    def _driver(self):
        if self.driver is None:
            raise RuntimeError("el navegador no está disponible")
        return self.driver

    def _abrir_mensaje(self, indice):
        """Abre el mensaje de la fila `indice` de la tabla."""
        for xpath in xpaths_enlace_mensaje(indice):
            try:
                WebDriverWait(self._driver(), 6).until(
                    EC.element_to_be_clickable((By.XPATH, xpath))
                ).click()
                self._stop_event.wait(2)
                return True
            except (TimeoutException, WebDriverException):
                continue
        return False

    def _hay_popup_notificaciones(self, espera=10):
        """True si aparece el emergente (lblMensaje) o su botón de cerrar."""
        driver = self._driver()

        def popup_presente(d):
            for xpath in (XPATH_POPUP, XPATH_CERRAR_POPUP):
                if any(e.is_displayed() for e in d.find_elements(By.XPATH, xpath)):
                    return True
            return False

        try:
            return bool(WebDriverWait(driver, espera).until(popup_presente))
        except TimeoutException:
            return False

    def _cerrar_popup(self):
        driver = self._driver()
        boton = WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, XPATH_CERRAR_POPUP))
        )
        try:
            boton.click()
        except WebDriverException:
            driver.execute_script("arguments[0].click();", boton)

    def _visible(self, xpath, espera):
        try:
            return WebDriverWait(self._driver(), espera).until(
                EC.visibility_of_element_located((By.XPATH, xpath))
            )
        except TimeoutException:
            return None

    def _click(self, xpath, espera=10):
        WebDriverWait(self._driver(), espera).until(
            EC.element_to_be_clickable((By.XPATH, xpath))
        ).click()

    def _cantidad(self, xpath):
        """Número mostrado en un badge; 0 si no existe o no es legible."""
        try:
            badge = WebDriverWait(self._driver(), 5).until(
                EC.presence_of_element_located((By.XPATH, xpath))
            )
        except TimeoutException:
            return 0
        digitos = "".join(c for c in badge.text if c.isdigit())
        return int(digitos) if digitos else 0

    def _abrir_navegador(self):
        options = Options()
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--start-maximized')
        self.driver = webdriver.Chrome(options=options)

    def _cerrar_sesion(self):
        if self.driver is None:
            return
        try:
            self._click(XPATH_SALIR, 5)
            self.log("Sesión cerrada correctamente.")
            self._stop_event.wait(2)
        except (TimeoutException, WebDriverException):
            self.log("[AVISO] No se pudo encontrar el botón de salir.")

    def _cerrar_navegador(self):
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
        self.input_segundos.setValue(5)
        opciones.addWidget(self.input_segundos)
        opciones.addStretch()
        layout.addLayout(opciones)

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

    def _mostrar_revision(self, rnc, nombre, numero, total):
        self.revision_pendiente = True
        self.segundos_restantes = self.input_segundos.value()
        self._agregar_log(f"\n{nombre} ({rnc}) | Mensaje {numero} de {total}")
        self._agregar_log("Lee el mensaje en el navegador y luego elige Eliminar o Conservar.")
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

import sys
import time
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QTextEdit, QLabel, QLineEdit, QGroupBox, QFormLayout
)
from PySide6.QtCore import QThread, Signal


class AutomationWorker(QThread):
    """Hilo que ejecuta toda la automatización con Selenium."""

    log_signal = Signal(str)
    finished_signal = Signal(bool, str)

    def __init__(self, usuario, clave):
        super().__init__()
        self.usuario = usuario
        self.clave = clave
        self.driver = None
        self.wait = None

    def log(self, msg):
        self.log_signal.emit(msg)

    def run(self):
        try:
            self._ejecutar_automatizacion()
            self.finished_signal.emit(True, "Proceso completado exitosamente.")
        except Exception as e:
            self.log(f"[ERROR] {e}")
            self.finished_signal.emit(False, str(e))
        finally:
            self._cerrar_navegador()

    # ------------------------------------------------------------------
    # Flujo principal
    # ------------------------------------------------------------------
    def _ejecutar_automatizacion(self):
        # --- Configurar y abrir navegador ---
        options = Options()
        # options.add_argument('--headless')  # Descomentar para modo sin ventana
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--start-maximized')

        self.driver = webdriver.Chrome(options=options)
        self.wait = WebDriverWait(self.driver, 20)

        # 1) Abrir la página de login
        url = "https://www.dgii.gov.do/OFV/login.aspx"
        self.log(f"Abriendo página: {url}")
        self.driver.get(url)

        # 2) Escribir usuario
        self.log("Escribiendo usuario...")
        campo_usuario = self.wait.until(
            EC.presence_of_element_located(
                (By.XPATH, '//*[@id="ctl00_ContentPlaceHolder1_txtUsuario"]')
            )
        )
        campo_usuario.clear()
        campo_usuario.send_keys(self.usuario)

        # 3) Escribir clave
        self.log("Escribiendo clave...")
        campo_clave = self.driver.find_element(
            By.XPATH, '//*[@id="ctl00_ContentPlaceHolder1_txtPassword"]'
        )
        campo_clave.clear()
        campo_clave.send_keys(self.clave)

        # 4) Click en Aceptar
        self.log("Haciendo click en Aceptar...")
        btn_aceptar = self.driver.find_element(
            By.XPATH, '//*[@id="ctl00_ContentPlaceHolder1_BtnAceptar"]'
        )
        btn_aceptar.click()
        time.sleep(3)

        # 5) Verificar si aparece el mensaje de alerta
        self.log("Verificando mensaje de alerta...")
        alerta_encontrada = False
        try:
            alerta = WebDriverWait(self.driver, 8).until(
                EC.presence_of_element_located(
                    (By.XPATH, '//*[@id="alert"]/a/div[2]')
                )
            )
            self.log("Mensaje de alerta encontrado. Haciendo click...")
            alerta.click()
            alerta_encontrada = True
            time.sleep(3)
        except TimeoutException:
            self.log("No apareció mensaje de alerta. Saliendo del flujo...")
            return  # cerrar navegador en finally

        if not alerta_encontrada:
            return

        # 6) Verificar cantidad de mensajes en el badge
        self.log("Verificando cantidad de mensajes...")
        badge = self.wait.until(
            EC.presence_of_element_located(
                (By.XPATH, '//*[@id="ctl00_ContentPlaceHolder1_badgeMensajes"]')
            )
        )
        cantidad = self._obtener_cantidad(badge)
        self.log(f"Cantidad de mensajes: {cantidad}")

        if cantidad == 0:
            self.log("No hay mensajes. Cerrando sesión...")
            self._cerrar_sesion()
            return

        # 7) Click en el primer mensaje
        self.log("Haciendo click en el primer mensaje...")
        primer_mensaje = self.wait.until(
            EC.element_to_be_clickable(
                (By.XPATH,
                 '//*[@id="ctl00_ContentPlaceHolder1_GVMensajes_ctl02_Enlace_47351055"]')
            )
        )
        primer_mensaje.click()
        time.sleep(3)

        # 8) Click en Siguiente hasta que la cantidad llegue a 0
        self.log("Navegando mensajes con el botón Siguiente...")
        while True:
            badge = self.driver.find_element(
                By.XPATH, '//*[@id="ctl00_ContentPlaceHolder1_badgeMensajes"]'
            )
            cantidad = self._obtener_cantidad(badge)
            self.log(f"  → Cantidad actual: {cantidad}")

            if cantidad == 0:
                self.log("La cantidad de mensajes llegó a cero.")
                break

            try:
                btn_siguiente = self.driver.find_element(
                    By.XPATH, '//*[@id="ctl00_ContentPlaceHolder1_btnSig"]/span'
                )
                btn_siguiente.click()
                time.sleep(2)
            except NoSuchElementException:
                self.log("No se encontró el botón Siguiente. Saliendo del bucle...")
                break

        # 9) Click en el botón 'Todo'
        self.log("Haciendo click en el botón 'Todo'...")
        btn_todo = self.wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, '//*[@id="ctl00_ContentPlaceHolder1_btnTodosMensajes"]')
            )
        )
        btn_todo.click()
        time.sleep(3)

        # 10) Seleccionar todas las casillas de verificación
        self.log("Seleccionando todas las casillas de verificación...")
        checkbox = self.wait.until(
            EC.element_to_be_clickable(
                (By.XPATH,
                 '//*[@id="ctl00_ContentPlaceHolder1_tablaTextoTipoMensaje"]'
                 '/tbody/tr/td[1]/input')
            )
        )
        if not checkbox.is_selected():
            checkbox.click()
        time.sleep(1)

        # 11) Click en Eliminar
        self.log("Haciendo click en el botón Eliminar...")
        btn_eliminar = self.driver.find_element(
            By.XPATH, '//*[@id="ctl00_ContentPlaceHolder1_btnEliminarTodos"]'
        )
        btn_eliminar.click()
        time.sleep(2)

        # 12) Presionar Enter para confirmar la eliminación
        self.log("Presionando Enter para confirmar eliminación...")
        # Intentar primero con un alert de JavaScript
        try:
            alert = WebDriverWait(self.driver, 3).until(EC.alert_is_present())
            alert.accept()
            self.log("Alerta de JavaScript aceptada.")
        except TimeoutException:
            # Si no es un alert JS, usar ActionChains para enviar Enter
            ActionChains(self.driver).send_keys(Keys.ENTER).perform()
            self.log("Enter enviado vía teclado.")
        time.sleep(3)

        # 13) Cerrar sesión
        self.log("Cerrando sesión...")
        self._cerrar_sesion()

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
        self._construir_ui()

    def _construir_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        layout = QVBoxLayout(central)

        # --- Grupo de credenciales ---
        grupo_cred = QGroupBox("Credenciales DGII")
        form = QFormLayout()

        self.input_usuario = QLineEdit("101594918")
        self.input_clave = QLineEdit("hfagf")
        self.input_clave.setEchoMode(QLineEdit.Password)

        form.addRow("Usuario:", self.input_usuario)
        form.addRow("Clave:", self.input_clave)
        grupo_cred.setLayout(form)
        layout.addWidget(grupo_cred)

        # --- Botones ---
        botones = QHBoxLayout()
        self.btn_iniciar = QPushButton("▶  Iniciar Proceso")
        self.btn_iniciar.clicked.connect(self._iniciar_proceso)

        self.btn_detener = QPushButton("■  Detener")
        self.btn_detener.clicked.connect(self._detener_proceso)
        self.btn_detener.setEnabled(False)

        botones.addWidget(self.btn_iniciar)
        botones.addWidget(self.btn_detener)
        layout.addLayout(botones)

        # --- Área de logs ---
        layout.addWidget(QLabel("Registro de actividad:"))
        self.log_area = QTextEdit()
        self.log_area.setReadOnly(True)
        layout.addWidget(self.log_area)

    # ------------------------------------------------------------------
    def _iniciar_proceso(self):
        usuario = self.input_usuario.text().strip()
        clave = self.input_clave.text().strip()

        if not usuario or not clave:
            self._agregar_log("[ERROR] Debe ingresar usuario y clave.")
            return

        self.log_area.clear()
        self._agregar_log("=== Iniciando proceso de automatización ===")
        self.btn_iniciar.setEnabled(False)
        self.btn_detener.setEnabled(True)

        self.worker = AutomationWorker(usuario, clave)
        self.worker.log_signal.connect(self._agregar_log)
        self.worker.finished_signal.connect(self._proceso_finalizado)
        self.worker.start()

    def _detener_proceso(self):
        if self.worker and self.worker.isRunning():
            self._agregar_log("Deteniendo proceso...")
            self.worker.terminate()
            self.worker.wait()
            self._proceso_finalizado(False, "Proceso detenido por el usuario.")

    def _proceso_finalizado(self, exito, mensaje):
        simbolo = "✓" if exito else "✗"
        self._agregar_log(f"\n{simbolo} {mensaje}")
        self.btn_iniciar.setEnabled(True)
        self.btn_detener.setEnabled(False)
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

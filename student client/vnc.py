import sys
import requests
import uuid
import time
from PyQt6.QtCore import QCoreApplication , Qt, QUrl,QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QApplication, QMainWindow,QMessageBox, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel
from PyQt6.QtWebEngineWidgets import QWebEngineView

# Sunucudan cevap bekleme suresi (saniye)
REQUEST_TIMEOUT = 15
# Guvenli kapanis (shutdown + shelve) bundan uzun surerse beklemeyi birak ve hata ver (saniye)
CLOSE_TIMEOUT_SECONDS = 300

class JetstreamClient(QMainWindow):
    def __init__(self,url,server_info,token ,baseurl,login_id):
        super().__init__()
        self._closing = False  # closeEvent basladiysa True; changeEvent/eventFilter bunu kontrol eder
        self._close_confirmed = False    # True olunca closeEvent pencereyi gercekten kapatir
        self._close_in_progress = False  # Secure Close calisirken ikinci kapatma istegini engeller
        self._close_started_at = 0
        self.is_maximized = False
        self.server_info = server_info
        self.token = token
        self.baseurl = baseurl
        self.url = url
        self.login_id = login_id

        self.inactivity_timer = QTimer(self)
        self.inactivity_timer.timeout.connect(self.close_machine)
        self.timer_duration = 15 * 60 * 1000  # 15 dakika
        self.inactivity_timer.start(self.timer_duration)


        self.is_active_in_session = False
        self.keep_open_timer = QTimer(self)
        self.keep_open_timer.timeout.connect(self._check_and_trigger_keep_open)
        # 4 dakika = 4 * 60 * 1000 milisaniye (sunucu baglanti oturumu 5 dk, sadece aktifken uzar)
        self.keep_open_timer.start( 4 * 60 * 1000)

        # Login token'i (son istekten 5 dk sonra olur) bu pencere acik oldugu surece, kullanici
        # aktif olsun olmasin, 4 dakikada bir canli tutulur. Pencere zaten calisan kullanici icin
        # acik ve bos kalirsa 15 dk sonra kendini kapatiyor. MainWindow'da bu YOK: orada
        # oturum 5 dakika sonra biter.
        self.login_keepalive_timer = QTimer(self)
        self.login_keepalive_timer.timeout.connect(self._keep_login_alive)
        self.login_keepalive_timer.start( 4 * 60 * 1000)


        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowSystemMenuHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(1100, 750)
        self.setMinimumSize(600, 400)

        main_widget = QWidget()
        main_widget.setStyleSheet("background-color: #1e1e1e; margin: 0; padding: 0;")
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)


        self.title_bar = QWidget()
        self.title_bar.setFixedHeight(35)
        self.title_bar.setStyleSheet("background-color: #2d2d2d;")
        title_layout = QHBoxLayout(self.title_bar)
        title_layout.setContentsMargins(15, 0, 0, 0)
        title_layout.setSpacing(0)

        title_label = QLabel("Jetstream Client")
        title_label.setStyleSheet("color: #ccc; font-family: sans-serif; font-size: 13px; font-weight: bold;")
        title_layout.addWidget(title_label)
        title_layout.addStretch()

        btn_style = """
            QPushButton {
                background-color: transparent;
                color: white;
                border: none;
                font-size: 14px;
                width: 45px;
                height: 35px;
            }
            QPushButton:hover { background-color: #444; }
        """
        close_btn_style = btn_style + " QPushButton:hover { background-color: #e81123; }"

        self.btn_fullscreen = QPushButton("⛶")
        self.btn_fullscreen.setStyleSheet(btn_style)
        self.btn_fullscreen.clicked.connect(self.toggle_fullscreen)
        title_layout.addWidget(self.btn_fullscreen)

        self.btn_maximize = QPushButton("▢")
        self.btn_maximize.setStyleSheet(btn_style)
        self.btn_maximize.clicked.connect(self.toggle_maximize)
        title_layout.addWidget(self.btn_maximize)

        self.btn_close = QPushButton("✕")
        self.btn_close.setStyleSheet(close_btn_style)
        self.btn_close.clicked.connect(self.close_machine)
        title_layout.addWidget(self.btn_close)

        main_layout.addWidget(self.title_bar)

        # Baslik cubugu dugmeleri klavye odagi almasin. Aksi halde terminalde Tab'e basinca odak
        # sayfadan bu dugmelere gecer (yazilanlar hicbir yere gitmez), odak X'teyken yazilan bir
        # bosluk ya da Enter da pencereyi kapatma akisini (Secure Close) baslatir.
        # Dugmeler yalnizca fareyle calisir.
        for _btn in (self.btn_fullscreen, self.btn_maximize, self.btn_close):
            _btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)


        self.browser = QWebEngineView()
        self.browser.setUrl(QUrl(self.url))
        main_layout.addWidget(self.browser)

        self.esc_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Escape), self)
        self.esc_shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
        self.esc_shortcut.activated.connect(self.handle_escape_shortcut)

        self.drag_position = None
        #self.installEventFilter(self)
        #self.browser.installEventFilter(self)
        QApplication.instance().installEventFilter(self)


    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and event.position().y() < 35:
            self.drag_position = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event):
        if self.drag_position is not None and event.buttons() == Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self.drag_position)
            event.accept()

    def mouseReleaseEvent(self, event):
        self.drag_position = None

    # --- BUTON FONKSİYONLARI ---
    def toggle_maximize(self):
        if self.is_maximized:
            self.showNormal()
            self.is_maximized = False
        else:
            self.showMaximized()
            self.is_maximized = True

    def toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
            self.title_bar.show()
        else:
            self.title_bar.hide()
            self.showFullScreen()

    def shutdown(self):
        url = self.baseurl + "/server/shut_down"
        payload = {
            "token": self.token,
            "server_id": self.server_info["os_id"]
        }
        response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        data = response.json()
        return bool(data.get("status", 0))

    def shelve_server(self):
        url = self.baseurl + "/server/shelve"
        payload = {
            "token": self.token,
            "server_id": self.server_info["os_id"]
        }
        response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        data = response.json()
        return bool(data.get("status", 0))
    
    def _set_user_passive(self):
        try:
            url = self.baseurl + "/server/set_passive" 
            payload = {
                "token": self.token,
                "login_id": self.login_id
            }
            response = requests.post(url, json=payload, timeout=3)
        except Exception as e:
            print("Error Occured During logout user:", e)

    def get_server_status(self):
        url = self.baseurl + "/server/status2"
        payload = {
            "token": self.token,
            "server_id": self.server_info["os_id"],
            "login_id" : self.login_id
        }
        response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
        data = response.json()
        return data.get("status", 0) 
        # 1 = ACTIVE
        # 2 = SHUTOFF
        # 3 = SHELVED

    def _stop_close_ui(self):
        """Secure Close kutusunu ve bekleme zamanlayicisini durdur."""
        if hasattr(self, '_polling_timer') and self._polling_timer:
            self._polling_timer.stop()
        if hasattr(self, '_polling_dialog') and self._polling_dialog:
            self._polling_dialog.hide()
            self._polling_dialog.destroy()
            self._polling_dialog = None

    def _finish_close(self):
        """Guvenli kapanis bitti: pencereyi gercekten kapat (closeEvent artik engellemez)."""
        self._stop_close_ui()
        self._close_in_progress = False
        self._close_confirmed = True
        self.close()

    def _abort_close(self, text):
        """Guvenli kapanis basarisiz: kutuyu kapat, yeniden denemeye izin ver, kullaniciya bildir."""
        self._stop_close_ui()
        self._close_in_progress = False
        QMessageBox.critical(self, "Error", text)

    def close_machine(self):
        # Zaten bir kapanis suruyorsa (X'e ya da Alt+F4'e tekrar basildi, hareketsizlik
        # zamanlayicisi vb.) ikinci bir akis baslatma.
        if self._close_in_progress:
            return
        self._close_in_progress = True
        self._close_started_at = time.monotonic()
        try:

            current_status  = self.get_server_status()

            if current_status == 3:
                self._finish_close()
                return


            self._polling_dialog = QMessageBox(self)
            self._polling_dialog.setWindowTitle("Secure Close")
            self._polling_dialog.setStandardButtons(QMessageBox.StandardButton.NoButton)
            self._polling_dialog.show()
            QCoreApplication.processEvents()

            if current_status == 2:
                shelve_success = False
                for i in range(3):
                    self._polling_dialog.setText(f"2/2 Sending Shelve Request (Attempt {i+1}/3)...")
                    QCoreApplication.processEvents()

                    if self.shelve_server():
                        shelve_success = True
                        break

                if shelve_success:
                    self._current_stage = "shelve"
                else:
                    self._abort_close("Unable to send shelve request after 3 attempts.")
                    return

            else:
                shutdown_success = False
                for i in range(3):
                    self._polling_dialog.setText(f"1/2 Sending Shutdown Request (Attempt {i+1}/3)...")
                    QCoreApplication.processEvents()

                    if self.shutdown():
                        shutdown_success = True
                        break

                if shutdown_success:
                    self._current_stage = "shutdown"
                else:
                    self._abort_close("Unable to send shutdown request after 3 attempts.")
                    return

            self._polling_timer = QTimer(self)
            self._polling_timer.timeout.connect(self._check_server_status)
            self._polling_timer.start(5000)

        except Exception as e:
            self._abort_close(str(e))

    def _check_server_status(self):
        try:
            # Kapanis cok uzun surduyse sonsuza kadar bekleme; hata ver, kullanici tekrar denesin
            if time.monotonic() - self._close_started_at > CLOSE_TIMEOUT_SECONDS:
                self._abort_close("Closing the session is taking too long. Please try again.")
                return

            status = self.get_server_status()

            if self._current_stage == "shutdown":
                self._polling_dialog.setText("1/2 Waiting for server to power OFF...")
                QCoreApplication.processEvents()

                if status == 3:
                    # status2 hem "zaten shelved" hem "baska kullanici baglandi" icin 3 doner;
                    # ikisinde de bekleyecek bir sey yok (eskiden burada sonsuza kadar beklenirdi).
                    self._finish_close()
                    return

                if status == 2:
                    shelve_success = False
                    for i in range(3):
                        self._polling_dialog.setText(f"2/2 Server is OFF. Sending Shelve Request (Attempt {i+1}/3)...")
                        QCoreApplication.processEvents()
                        if self.shelve_server():
                            shelve_success = True
                            break

                    if shelve_success:
                        self._current_stage = "shelve"
                    else:
                        self._abort_close("Server shut down but failed to send shelve request.")
                return

            if self._current_stage == "shelve":
                self._polling_dialog.setText("2/2 Waiting for server to become SHELVED...")
                QCoreApplication.processEvents()

                if status == 3:
                    self._finish_close()
                    return

        except Exception as e:
            print("Polling Error:", e)
   
    
    def changeEvent(self, event):
            from PyQt6.QtCore import QEvent
            # Pencere kapanirken (closeEvent timer'lari None yapar) ActivationChange gelir;
            # o durumda timer'a dokunma, yoksa AttributeError -> PyQt uygulamayi abort eder.
            if event.type() == QEvent.Type.ActivationChange and not self._closing:
                if not self.isActiveWindow():
                    self.inactivity_timer.start(self.timer_duration)
                else:
                    self.inactivity_timer.start(self.timer_duration)
                    self.is_active_in_session = True
                    
            super().changeEvent(event)

    def eventFilter(self, watched, event):
        from PyQt6.QtCore import QEvent
        if self._closing:
            return False
        user_interaction_events = (
            QEvent.Type.MouseMove,
            QEvent.Type.MouseButtonPress,
            QEvent.Type.KeyPress,
            QEvent.Type.Wheel
        )
        
        if event.type() in user_interaction_events:
            if hasattr(self, 'inactivity_timer') and self.inactivity_timer.isActive():
                self.inactivity_timer.start(self.timer_duration)
            self.is_active_in_session = True
                
        return super().eventFilter(watched, event)

    def _check_and_trigger_keep_open(self):
        # Sunucu baglanti oturumu (server_login_list) SADECE kullanici aktifken uzatilir.
        # (Login token'i ayri ve kosulsuz uzatilir: _keep_login_alive)
        if self.is_active_in_session:
            # Istek basarisiz olursa bayragi sifirlama, bir sonraki turda tekrar denensin
            if self._keep_open():
                self.is_active_in_session = False

    def _keep_open(self):
        # QTimer slot'unda yakalanmamis hata PyQt'de uygulamayi cokertir; ag hatasi yutulmali
        try:
            url = self.baseurl + "/server/keep_open"
            payload = {
                "token": self.token,
                "login_id": self.login_id
            }
            response = requests.post(url, json=payload, timeout=REQUEST_TIMEOUT)
            data = response.json()
            return data.get("status", 0)
        except Exception as e:
            print("Keep open failed:", e)
            return 0

    def _keep_login_alive(self):
        # /server/list sadece DB'den kullanicinin sunucu listesini okur (Nova'ya gitmez,
        # server_login_list'e dokunmaz); loginControl.php token suresini 5 dk uzatir.
        # Baglanti oturumunu (keep_open) UZATMAZ. Ag hatasi uygulamayi cokertmesin diye yutulur.
        if self._closing or not self.token:
            return
        try:
            requests.post(self.baseurl + "/server/list", json={"token": self.token}, timeout=REQUEST_TIMEOUT)
        except Exception as e:
            print("Login keep-alive failed:", e)

    def closeEvent(self, event):
        # Alt+F4, gorev cubugundan kapat, taskkill (/f olmadan), Ctrl+C... tum kapatma istekleri
        # buraya duser. Guvenli kapanis (shutdown/shelve) bitmeden pencereyi kapatma: istegi
        # X dugmesiyle ayni akisa (close_machine) yonlendir. Akis bitince _finish_close
        # _close_confirmed'i acip tekrar close() cagirir.
        if not self._close_confirmed:
            event.ignore()
            # close_machine'i closeEvent icinden dogrudan cagirma: hemen bitiyorsa (sunucu zaten
            # shelved ya da baska biri iceride) icindeki self.close() Qt tarafindan yok sayilir
            # (closeEvent calisirken ayni pencereye close() etkisizdir). Bir sonraki donguye ertele.
            QTimer.singleShot(0, self.close_machine)
            return

        # Uygulama capindaki event filter'i gercekten kaldir (asagidaki eski
        # self.removeEventFilter(self) bunu yapmiyordu) ve kapanis bayragini kaldir.
        self._closing = True
        QApplication.instance().removeEventFilter(self)

        self._set_user_passive()

        if hasattr(self, 'inactivity_timer') and self.inactivity_timer:
            self.inactivity_timer.stop()
            self.inactivity_timer.deleteLater()
            self.inactivity_timer = None
            
        if hasattr(self, 'keep_open_timer') and self.keep_open_timer:
            self.keep_open_timer.stop()
            self.keep_open_timer.deleteLater()
            self.keep_open_timer = None

        if hasattr(self, 'login_keepalive_timer') and self.login_keepalive_timer:
            self.login_keepalive_timer.stop()
            self.login_keepalive_timer.deleteLater()
            self.login_keepalive_timer = None

        if hasattr(self, '_polling_timer') and self._polling_timer:
            self._polling_timer.stop()
            self._polling_timer.deleteLater()
            self._polling_timer = None


        if hasattr(self, 'browser') and self.browser:
            self.browser.removeEventFilter(self)
            self.browser.stop() 
            self.browser.setUrl(QUrl("about:blank"))
            self.browser.deleteLater()
            self.browser = None

        self.server_info = None
        self.token = None
        self.login_id = None
        
        event.accept() 

    def handle_escape_shortcut(self):
        if self.isFullScreen():
            self.toggle_fullscreen()

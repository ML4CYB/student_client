import sys
import requests
import uuid
from PyQt6.QtCore import QCoreApplication , Qt, QUrl,QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QApplication, QMainWindow,QMessageBox, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel
from PyQt6.QtWebEngineWidgets import QWebEngineView

class JetstreamClient(QMainWindow):
    def __init__(self,url,server_info,token ,baseurl,login_id):
        super().__init__()
        self.is_maximized = False
        self.server_info = server_info
        self.token = token
        self.baseurl = baseurl
        self.url = url
        self.login_id = login_id

        self.inactivity_timer = QTimer(self)
        self.inactivity_timer.timeout.connect(self.close_machine)
        self.timer_duration = 15 * 60 * 1000  # 5 dakika
        self.inactivity_timer.start(self.timer_duration)


        self.is_active_in_session = False    
        self.keep_open_timer = QTimer(self)
        self.keep_open_timer.timeout.connect(self._check_and_trigger_keep_open)
        # 3 dakika = 3 * 60 * 1000 milisaniye
        self.keep_open_timer.start( 4 * 60 * 1000)
        

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
        response = requests.post(url, json=payload, timeout=5)
        data = response.json()
        return bool(data.get("status", 0))

    def shelve_server(self):
        url = self.baseurl + "/server/shelve"
        payload = {
            "token": self.token,
            "server_id": self.server_info["os_id"]
        }
        response = requests.post(url, json=payload, timeout=5)
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
        response = requests.post(url, json=payload, timeout=5)
        data = response.json()
        return data.get("status", 0) 
        # 1 = ACTIVE
        # 2 = SHUTOFF
        # 3 = SHELVED

    def close_machine(self):
        try:

            current_status  = self.get_server_status()
            
            if current_status == 3:
                self.close()
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
                    self._polling_dialog.hide()
                    self._polling_dialog.destroy()
                    self._polling_dialog = None
                    QMessageBox.critical(self, "Error", "Unable to send shelve request after 3 attempts.")
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
                    self._polling_dialog.hide()
                    self._polling_dialog.destroy()
                    self._polling_dialog = None
                    QMessageBox.critical(self, "Error", "Unable to send shutdown request after 3 attempts.")
                    return

            self._polling_timer = QTimer(self)
            self._polling_timer.timeout.connect(self._check_server_status)
            self._polling_timer.start(5000)

        except Exception as e:
            if hasattr(self, '_polling_dialog') and self._polling_dialog:
                self._polling_dialog.hide()
                self._polling_dialog.destroy()
                self._polling_dialog = None
            QMessageBox.critical(self, "Error", str(e))

    def _check_server_status(self):
        try:

            status = self.get_server_status()
            
            if self._current_stage == "shutdown":
                self._polling_dialog.setText("1/2 Waiting for server to power OFF...")
                QCoreApplication.processEvents()
                
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
                        self._polling_timer.stop()
                        self._polling_dialog.hide()
                        self._polling_dialog.destroy()
                        self._polling_dialog = None
                        QMessageBox.critical(self, "Error", "Server shut down but failed to send shelve request.")
                return

            if self._current_stage == "shelve":
                self._polling_dialog.setText("2/2 Waiting for server to become SHELVED...")
                QCoreApplication.processEvents()
                
                if status == 3: 
                    self._polling_timer.stop()
                    
                    self._polling_dialog.hide()
                    self._polling_dialog.destroy()
                    self._polling_dialog = None
                    
                    self.close()
                    return

        except Exception as e:
            print("Polling Error:", e)
   
    
    def changeEvent(self, event):
            from PyQt6.QtCore import QEvent
            if event.type() == QEvent.Type.ActivationChange:
                if not self.isActiveWindow():
                    self.inactivity_timer.start(self.timer_duration)
                else:
                    self.inactivity_timer.start(self.timer_duration)
                    self.is_active_in_session = True
                    
            super().changeEvent(event)

    def eventFilter(self, watched, event):
        from PyQt6.QtCore import QEvent
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
        if self.is_active_in_session:
            self._keep_open()
            self.is_active_in_session = False
        else : 
            print("")

    def _keep_open(self):
        url = self.baseurl + "/server/keep_open"
        payload = {
            "token": self.token,
            "login_id": self.login_id
        }
        response = requests.post(url, json=payload, timeout=5)
        data = response.json()
        return data.get("status", 0)
    
    def closeEvent(self, event):
        self._set_user_passive()

        if hasattr(self, 'inactivity_timer') and self.inactivity_timer:
            self.inactivity_timer.stop()
            self.inactivity_timer.deleteLater()
            self.inactivity_timer = None
            
        if hasattr(self, 'keep_open_timer') and self.keep_open_timer:
            self.keep_open_timer.stop()
            self.keep_open_timer.deleteLater()
            self.keep_open_timer = None
            
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

        self.removeEventFilter(self)

        self.server_info = None
        self.token = None
        self.login_id = None
        
        event.accept() 

    def handle_escape_shortcut(self):
        if self.isFullScreen():
            self.toggle_fullscreen()

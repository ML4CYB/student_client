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

        # --- HAREKETSİZLİK VE ODAK SAYAÇ AYARLARI ---
        self.inactivity_timer = QTimer(self)
        self.inactivity_timer.timeout.connect(self.close_machine)
        self.timer_duration = 5 * 60 * 1000  # 5 dakika
        self.inactivity_timer.start(self.timer_duration)

        # --- YENİ: KEEP OPEN KONTROLÜ ---
        self.is_active_in_session = False    # Kullanıcı işlem yaptı mı takibi
        self.keep_open_timer = QTimer(self)
        self.keep_open_timer.timeout.connect(self._check_and_trigger_keep_open)
        # 3 dakika = 3 * 60 * 1000 milisaniye
        self.keep_open_timer.start( 60 * 1000)
        
        # 1. PENCERE AYARLARI
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowSystemMenuHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(1100, 750)
        self.setMinimumSize(600, 400)
        # 2. ANA LAYOUT
        main_widget = QWidget()
        main_widget.setStyleSheet("background-color: #1e1e1e; margin: 0; padding: 0;")
        self.setCentralWidget(main_widget)
        main_layout = QVBoxLayout(main_widget)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 3. ÖZEL BAŞLIK ÇUBUĞU
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
        self.installEventFilter(self)
        self.browser.installEventFilter(self)

    # --- SÜRÜKLEME KONTROLLERİ ---
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
        print(response.text)
        data = response.json()
        return bool(data.get("status", 0))

    def shelve_server(self):
        url = self.baseurl + "/server/shelve"
        payload = {
            "token": self.token,
            "server_id": self.server_info["os_id"]
        }
        response = requests.post(url, json=payload, timeout=5)
        print(response.text)
        data = response.json()
        return bool(data.get("status", 0))
    
    def _set_user_passive(self):
        try:
            print("Kullanici veritabaninda pasife cekiliyor...")
            url = self.baseurl + "/server/set_passive" 
            payload = {
                "token": self.token,
                "login_id": self.login_id
            }
            # Kapanış esnasında arayüzü kilitlememesi için timeout'u kısa (2-3 sn) tutuyoruz
            response = requests.post(url, json=payload, timeout=3)
            print("Pasif yapma API Yaniti:", response.text)
        except Exception as e:
            print("Kullanici pasif yapilirken API hatasi oluştu:", e)

    def get_server_status(self):
        url = self.baseurl + "/server/status2"
        payload = {
            "token": self.token,
            "server_id": self.server_info["os_id"],
            "login_id" : self.login_id
        }
        response = requests.post(url, json=payload, timeout=5)
        print(response.text)
        data = response.json()
        return data.get("status", 0) 
        # 1 = ACTIVE
        # 2 = SHUTOFF
        # 3 = SHELVED

    def close_machine(self):
        try:
            # [SENARYO BAŞLANGICI] Sunucunun anlık durumunu alıyoruz
            current_status  = self.get_server_status()
            
            # ------------------------------------------------------------------
            # SENARYO 3: Sunucu zaten shelved ise hiçbir şey yapma çık
            # ------------------------------------------------------------------
            if current_status == 3:
                self.close()
                return
                
            # Takip dialog kutusunu hazırlıyoruz
            self._polling_dialog = QMessageBox(self)
            self._polling_dialog.setWindowTitle("Secure Close")
            self._polling_dialog.setStandardButtons(QMessageBox.StandardButton.NoButton)
            self._polling_dialog.show()
            QCoreApplication.processEvents()
            
            # ------------------------------------------------------------------
            # SENARYO 2: Sunucu kapalı (SHUTOFF = 2) -> 3 Kere Shelve İsteği Dene
            # ------------------------------------------------------------------
            if current_status == 2:
                shelve_success = False
                for i in range(3):
                    self._polling_dialog.setText(f"2/2 Sending Shelve Request (Attempt {i+1}/3)...")
                    QCoreApplication.processEvents()
                    
                    if self.shelve_server():
                        shelve_success = True
                        break
                
                if shelve_success:
                    self._current_stage = "shelve"  # Başarılı, artık her 5 saniyede bir durum 3 mü diye bakacağız
                else:
                    # 3 deneme de başarısız olduysa dialogu imha et ve hata bas
                    self._polling_dialog.hide()
                    self._polling_dialog.destroy()
                    self._polling_dialog = None
                    QMessageBox.critical(self, "Error", "Unable to send shelve request after 3 attempts.")
                    return
                
            # ------------------------------------------------------------------
            # SENARYO 1: Sunucu aktif (ACTIVE = 1) -> 3 Kere Shutdown İsteği Dene
            # ------------------------------------------------------------------
            else:
                shutdown_success = False
                for i in range(3):
                    self._polling_dialog.setText(f"1/2 Sending Shutdown Request (Attempt {i+1}/3)...")
                    QCoreApplication.processEvents()
                    
                    if self.shutdown():
                        shutdown_success = True
                        break
                
                if shutdown_success:
                    self._current_stage = "shutdown" # Başarılı, artık her 5 saniyede bir durum 2 oldu mu diye bakacağız
                else:
                    # 3 deneme de başarısız olduysa dialogu imha et ve hata bas
                    self._polling_dialog.hide()
                    self._polling_dialog.destroy()
                    self._polling_dialog = None
                    QMessageBox.critical(self, "Error", "Unable to send shutdown request after 3 attempts.")
                    return

            # [ORTAK POLING] Sinyaller başarıyla ulaştıysa, her 5 saniyede bir durum kontrol makinesini başlat
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
            # 5 saniyede bir durum sorguluyoruz
            status = self.get_server_status()
            
            # ------------------------------------------------------------------
            # SENARYO 1'İN DEVAMI (AŞAMA 1: Sunucunun kapanmasını bekle)
            # ------------------------------------------------------------------
            if self._current_stage == "shutdown":
                self._polling_dialog.setText("1/2 Waiting for server to power OFF...")
                QCoreApplication.processEvents()
                
                if status == 2: # Sunucu kapanmış! Şimdi Shelve emri göndereceğiz (Yine 3 deneme garantisiyle)
                    shelve_success = False
                    for i in range(3):
                        self._polling_dialog.setText(f"2/2 Server is OFF. Sending Shelve Request (Attempt {i+1}/3)...")
                        QCoreApplication.processEvents()
                        if self.shelve_server():
                            shelve_success = True
                            break
                            
                    if shelve_success:
                        self._current_stage = "shelve" # Başarılı, artık durum 3 mü diye bekleyeceğiz
                    else:
                        # Eğer bu aşamadaki 3 deneme de başarısız olursa mecburen döngüyü kırıp çıkıyoruz
                        self._polling_timer.stop()
                        self._polling_dialog.hide()
                        self._polling_dialog.destroy()
                        self._polling_dialog = None
                        QMessageBox.critical(self, "Error", "Server shut down but failed to send shelve request.")
                return

            # ------------------------------------------------------------------
            # SENARYO 1 ve 2'NİN ORTAK SONU (AŞAMA 2: Shelved olunca kapat)
            # ------------------------------------------------------------------
            if self._current_stage == "shelve":
                self._polling_dialog.setText("2/2 Waiting for server to become SHELVED...")
                QCoreApplication.processEvents()
                
                if status == 3: # Hedefe ulaşıldı!
                    # 1. Zamanlayıcıyı durdur
                    self._polling_timer.stop()
                    
                    # 2. Önce dialog kutusunu tamamen imha et
                    self._polling_dialog.hide()
                    self._polling_dialog.destroy()
                    self._polling_dialog = None
                    
                    # 3. Son olarak ekranı kapat ve çık
                    self.close()
                    return

        except Exception as e:
            print("Polling Error:", e)
   
        # ─── SHORTCUT TETİKLENME METODU ───
    
    def changeEvent(self, event):
            from PyQt6.QtCore import QEvent
            if event.type() == QEvent.Type.ActivationChange:
                if not self.isActiveWindow():
                    print("Window Arkaya dustu yada fokus kaybetti")
                    self.inactivity_timer.start(self.timer_duration)
                else:
                    print("Window su anda yeniden aktif")
                    self.inactivity_timer.start(self.timer_duration)
                    # Kullanıcı uygulamaya geri döndüğünde de işlem yapmış sayıyoruz
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
            # 1. 5 dakikalık kapanma sayacını sıfırla
            if hasattr(self, 'inactivity_timer') and self.inactivity_timer.isActive():
                self.inactivity_timer.start(self.timer_duration)
            
            # 2. YENİ: Kullanıcının hareket ettiğini işaretle (3 dakikalık kontrol için)
            self.is_active_in_session = True
                
        return super().eventFilter(watched, event)

    # --- YENİ KONTROL METODU ---
    def _check_and_trigger_keep_open(self):
        """3 dakikada bir çalisir, işlem yapilmissa _keep_open'i tetikler."""
        if self.is_active_in_session:
            print("Son 3 dakika icinde islem algilandi keep open cagirilacak.")
            self._keep_open()
            
            # Tetiklendikten sonra bayrağı sıfırlıyoruz ki 
            # sonraki 3 dakika boyunca tekrar işlem yapılması beklensin.
            self.is_active_in_session = False
        else : 
            print("Son 3 dakika icinde herhangi bir islem yok Herhangi bir islem yok ...")

    def _keep_open(self):
        print("Keep open calisti")
        url = self.baseurl + "/server/keep_open"
        payload = {
            "token": self.token,
            "login_id": self.login_id
        }
        print(f"Login id : {self.login_id}")
        response = requests.post(url, json=payload, timeout=5)
        print(response.text)
        data = response.json()
        return data.get("status", 0)
    
    def closeEvent(self, event):
        self._set_user_passive()
        print("JetstreamClient penceresi ve RAM belleği tamamen yok ediliyor...")
        
        # 1. Zamanlayıcıları (Timer) durdur ve sil
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

        # 2. Web Tarayıcıyı (WebEngineView) ve ağ bağlantısını RAM'den kazı
        if hasattr(self, 'browser') and self.browser:
            self.browser.removeEventFilter(self)
            self.browser.stop()  # VNC akışını kes
            self.browser.setUrl(QUrl("about:blank")) # Boş sayfaya yönlendir ki RAM boşalsın
            self.browser.deleteLater() # Tarayıcı nesnesini tamamen sil
            self.browser = None

        # 3. Olay filtresini kaldır
        self.removeEventFilter(self)

        # 4. Değişkenleri boşa çıkar
        self.server_info = None
        self.token = None
        self.login_id = None
        
        print("Pencere içeriği RAM'den temizlendi.")
        event.accept() # Kapanış onaylandı

    def handle_escape_shortcut(self):
        print("Shortcut Calisti: Escape tuşu algılandı!")
        if self.isFullScreen():
            self.toggle_fullscreen()

import sys
import requests
import uuid
import time
from PyQt6.QtCore import QCoreApplication , Qt, QUrl,QTimer
from PyQt6.QtGui import QKeySequence, QShortcut
from PyQt6.QtWidgets import QApplication, QMainWindow,QMessageBox, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel
from PyQt6.QtWebEngineWidgets import QWebEngineView

from client_log import log, api_post, safe_url

# Sunucudan cevap bekleme suresi (saniye)
REQUEST_TIMEOUT = 15
# Guvenli kapanis (shutdown + shelve) bundan uzun surerse beklemeyi birak ve hata ver (saniye)
CLOSE_TIMEOUT_SECONDS = 300
# Nabiz: arayuz dongusunun donup donmadigini anlamak icin 5 sn'de bir kontrol, 30 sn'de bir ozet satiri
HEARTBEAT_TICK_MS = 5000
HEARTBEAT_LOG_EVERY = 6
LAG_WARN_SECONDS = 1.5

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

        # Tanilama sayaclari (icerik degil, sadece sayi/zaman)
        self._ev_counts = {"key": 0, "move": 0, "press": 0, "wheel": 0}
        self._last_input = time.monotonic()
        self._last_key_stamp = None
        self._hb_last = time.monotonic()
        self._hb_ticks = 0
        try:
            log.info("VNC window created: login_id=%s server=%s (%s) page=%s", login_id,
                     server_info.get("os_id"), server_info.get("server_name"), safe_url(url))
        except Exception:
            pass

        self.inactivity_timer = QTimer(self)
        self.inactivity_timer.timeout.connect(self._on_inactivity_timeout)
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

        self.heartbeat_timer = QTimer(self)
        self.heartbeat_timer.timeout.connect(self._heartbeat)
        self.heartbeat_timer.start(HEARTBEAT_TICK_MS)


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
        self.btn_close.clicked.connect(self._on_close_button)
        title_layout.addWidget(self.btn_close)

        main_layout.addWidget(self.title_bar)

        # Baslik cubugu dugmeleri klavye odagi almasin. Aksi halde terminalde Tab'e basinca odak
        # sayfadan bu dugmelere gecer (yazilanlar hicbir yere gitmez), odak X'teyken yazilan bir
        # bosluk ya da Enter da pencereyi kapatma akisini (Secure Close) baslatir.
        # Dugmeler yalnizca fareyle calisir.
        for _btn in (self.btn_fullscreen, self.btn_maximize, self.btn_close):
            _btn.setFocusPolicy(Qt.FocusPolicy.NoFocus)


        self.browser = QWebEngineView()
        # Sayfa olaylarini (yukleme, adres degisimi, tarayici surecinin olmesi) logla; adreslerin
        # token tasiyan kismi safe_url ile atilir.
        self.browser.loadStarted.connect(self._on_page_load_started)
        self.browser.loadFinished.connect(self._on_page_load_finished)
        self.browser.urlChanged.connect(self._on_page_url_changed)
        self.browser.page().renderProcessTerminated.connect(self._on_render_process_terminated)
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

    # --- TANILAMA YARDIMCILARI (log) ---
    def _state_name(self):
        if self.isMinimized():
            return "minimized"
        if self.isFullScreen():
            return "fullscreen"
        if self.isMaximized():
            return "maximized"
        return "normal"

    def _focus_desc(self):
        w = QApplication.focusWidget()
        if w is None:
            return "none"
        if w is self.btn_close:
            return "X button"
        if w is self.btn_maximize:
            return "maximize button"
        if w is self.btn_fullscreen:
            return "fullscreen button"
        return type(w).__name__

    def _note_input(self, etype, event):
        """Girdiyi say (icerik kaydetme); sadece Tab/Esc/F tuslari gibi ozel tuslarin adini yaz."""
        from PyQt6.QtCore import QEvent
        try:
            self._last_input = time.monotonic()
            if etype == QEvent.Type.KeyPress:
                # Ayni tus olayi ust widget'lara yayilirken filtre tekrar cagrilir; ayni
                # zaman damgali olayi bir kez say/yaz (damga 0 ise sentetik olaydir, hepsini say)
                ts = event.timestamp()
                stamp = (ts, event.key())
                if ts and stamp == self._last_key_stamp:
                    return
                self._last_key_stamp = stamp
                self._ev_counts["key"] += 1
                self._log_special_key(event)
            elif etype == QEvent.Type.MouseMove:
                self._ev_counts["move"] += 1
            elif etype == QEvent.Type.MouseButtonPress:
                self._ev_counts["press"] += 1
            elif etype == QEvent.Type.Wheel:
                self._ev_counts["wheel"] += 1
        except Exception:
            pass

    def _log_special_key(self, event):
        key = event.key()
        mods = event.modifiers()
        ctrl = bool(mods & Qt.KeyboardModifier.ControlModifier)
        alt = bool(mods & Qt.KeyboardModifier.AltModifier)
        meta = bool(mods & Qt.KeyboardModifier.MetaModifier)
        shift = bool(mods & Qt.KeyboardModifier.ShiftModifier)
        non_printable = key >= 0x01000000     # Qt'nin ozel tuslari (Tab, Esc, F1.., ok tuslari...)
        special = (
            key in (Qt.Key.Key_Tab.value, Qt.Key.Key_Backtab.value, Qt.Key.Key_Escape.value)
            or Qt.Key.Key_F1.value <= key <= Qt.Key.Key_F12.value
            or ((alt or meta) and (non_printable or key == Qt.Key.Key_Space.value))
            or (ctrl and not alt and key in (Qt.Key.Key_Q.value, Qt.Key.Key_W.value))
        )
        if not special:
            return
        try:
            name = Qt.Key(key).name.replace("Key_", "")
        except ValueError:
            name = hex(key)
        combo = "+".join(n for n, on in (("Ctrl", ctrl), ("Alt", alt), ("Meta", meta), ("Shift", shift)) if on)
        log.info("special key: %s%s (focus: %s)", (combo + "+") if combo else "", name, self._focus_desc())

    def _heartbeat(self):
        try:
            if self._closing:
                return
            now = time.monotonic()
            lag = now - self._hb_last - HEARTBEAT_TICK_MS / 1000.0
            self._hb_last = now
            if lag > LAG_WARN_SECONDS:
                log.warning("UI FROZE for about %.1fs (event loop was blocked; likely a network request on the UI thread)", lag)
            self._hb_ticks += 1
            if self._hb_ticks % HEARTBEAT_LOG_EVERY == 0:
                c = self._ev_counts
                remaining = self.inactivity_timer.remainingTime() // 1000 if self.inactivity_timer else -1
                log.info("alive: last 30s input keys=%d mouse-moves=%d clicks=%d wheel=%d | idle=%.0fs | window=%s active=%s | focus=%s | inactivity-close in %ss",
                         c["key"], c["move"], c["press"], c["wheel"], now - self._last_input,
                         self._state_name(), self.isActiveWindow(), self._focus_desc(), remaining)
                for k in c:
                    c[k] = 0
        except Exception:
            pass

    def _on_page_load_started(self):
        log.info("page load started")

    def _on_page_load_finished(self, ok):
        log.info("page load finished ok=%s", ok)

    def _on_page_url_changed(self, url):
        try:
            log.info("page URL changed -> %s", safe_url(url.toString()))
        except Exception:
            pass

    def _on_render_process_terminated(self, status, exit_code):
        try:
            log.error("BROWSER RENDER PROCESS TERMINATED: status=%s exit_code=%s (the remote desktop view stopped working)",
                      getattr(status, "name", status), exit_code)
        except Exception:
            pass

    def _on_close_button(self):
        self.close_machine("X button (mouse click)")

    def _on_inactivity_timeout(self):
        log.warning("INACTIVITY TIMER fired: no input for %d min", self.timer_duration // 60000)
        self.close_machine("inactivity timer")

    # --- BUTON FONKSİYONLARI ---
    def toggle_maximize(self):
        log.info("maximize toggle requested (currently %s)", self._state_name())
        if self.is_maximized:
            self.showNormal()
            self.is_maximized = False
        else:
            self.showMaximized()
            self.is_maximized = True

    def toggle_fullscreen(self):
        log.info("fullscreen toggle requested (currently %s)", self._state_name())
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
        data = api_post(url, payload, REQUEST_TIMEOUT)
        return bool(data.get("status", 0))

    def shelve_server(self):
        url = self.baseurl + "/server/shelve"
        payload = {
            "token": self.token,
            "server_id": self.server_info["os_id"]
        }
        data = api_post(url, payload, REQUEST_TIMEOUT)
        return bool(data.get("status", 0))

    def _set_user_passive(self):
        try:
            url = self.baseurl + "/server/set_passive"
            payload = {
                "token": self.token,
                "login_id": self.login_id
            }
            data = api_post(url, payload, 3)
            if not (isinstance(data, dict) and data.get("status") == 1):
                log.error("SET_PASSIVE NOT APPLIED: the server session stays active=1 until the watchdog closes it")
        except Exception as e:
            print("Error Occured During logout user:", e)
            log.error("SET_PASSIVE FAILED (%s): the server session stays active=1 until the watchdog closes it", type(e).__name__)

    def get_server_status(self):
        url = self.baseurl + "/server/status2"
        payload = {
            "token": self.token,
            "server_id": self.server_info["os_id"],
            "login_id" : self.login_id
        }
        data = api_post(url, payload, REQUEST_TIMEOUT)
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
        log.info("secure close finished after %.0fs -> closing window", time.monotonic() - self._close_started_at)
        self._stop_close_ui()
        self._close_in_progress = False
        self._close_confirmed = True
        self.close()

    def _abort_close(self, text):
        """Guvenli kapanis basarisiz: kutuyu kapat, yeniden denemeye izin ver, kullaniciya bildir."""
        log.error("SECURE CLOSE ABORTED after %.0fs: %s", time.monotonic() - self._close_started_at, text)
        self._stop_close_ui()
        self._close_in_progress = False
        QMessageBox.critical(self, "Error", text)

    def close_machine(self, source=None):
        # source: kapanisi kimin tetikledigi (log icin). Dogrudan baglanti sinyalinden gelen
        # bool gibi degerler yok sayilir.
        if not isinstance(source, str):
            source = "direct call"
        # Zaten bir kapanis suruyorsa (X'e ya da Alt+F4'e tekrar basildi, hareketsizlik
        # zamanlayicisi vb.) ikinci bir akis baslatma.
        if self._close_in_progress:
            log.info("close request ignored, a secure close is already running (request source: %s)", source)
            return
        self._close_in_progress = True
        self._close_started_at = time.monotonic()
        log.warning("SECURE CLOSE started: triggered by %s (last input %.0fs ago)", source, time.monotonic() - self._last_input)
        try:

            current_status  = self.get_server_status()
            log.info("secure close: server status2=%s", current_status)

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

            log.info("secure close: stage=%s request accepted, waiting for the server", self._current_stage)
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
            log.info("secure close poll: stage=%s status2=%s", self._current_stage, status)

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
            log.warning("secure close poll error: %s: %s", type(e).__name__, str(e)[:200])


    def changeEvent(self, event):
            from PyQt6.QtCore import QEvent
            # Pencere kapanirken (closeEvent timer'lari None yapar) ActivationChange gelir;
            # o durumda timer'a dokunma, yoksa AttributeError -> PyQt uygulamayi abort eder.
            if event.type() == QEvent.Type.ActivationChange and not self._closing:
                try:
                    log.info("window %s", "ACTIVATED (in front, has focus)" if self.isActiveWindow()
                             else "DEACTIVATED (another window took focus)")
                except Exception:
                    pass
                if not self.isActiveWindow():
                    self.inactivity_timer.start(self.timer_duration)
                else:
                    self.inactivity_timer.start(self.timer_duration)
                    self.is_active_in_session = True
            elif event.type() == QEvent.Type.WindowStateChange and not self._closing:
                try:
                    log.info("window state -> %s", self._state_name())
                except Exception:
                    pass

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
            self._note_input(event.type(), event)

        return super().eventFilter(watched, event)

    def _check_and_trigger_keep_open(self):
        # Sunucu baglanti oturumu (server_login_list) SADECE kullanici aktifken uzatilir.
        # (Login token'i ayri ve kosulsuz uzatilir: _keep_login_alive)
        if self.is_active_in_session:
            log.info("keep_open tick: user was active -> extending the server session")
            # Istek basarisiz olursa bayragi sifirlama, bir sonraki turda tekrar denensin
            if self._keep_open():
                self.is_active_in_session = False
            else:
                log.warning("keep_open did not succeed; will retry at the next tick")
        else:
            log.info("keep_open tick: no input since the last tick -> NOT extending (server session ends 5 min after its last extension)")

    def _keep_open(self):
        # QTimer slot'unda yakalanmamis hata PyQt'de uygulamayi cokertir; ag hatasi yutulmali
        try:
            url = self.baseurl + "/server/keep_open"
            payload = {
                "token": self.token,
                "login_id": self.login_id
            }
            data = api_post(url, payload, REQUEST_TIMEOUT)
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
        log.info("login keep-alive tick")
        try:
            data = api_post(self.baseurl + "/server/list", {"token": self.token}, REQUEST_TIMEOUT)
            if isinstance(data, dict) and data.get("status") != 1:
                log.error("LOGIN TOKEN IS NO LONGER VALID (server said: %s): secure close and set_passive will fail from now on",
                          str(data.get("detail"))[:120])
        except Exception as e:
            print("Login keep-alive failed:", e)

    def closeEvent(self, event):
        # Alt+F4, gorev cubugundan kapat, taskkill (/f olmadan), Ctrl+C... tum kapatma istekleri
        # buraya duser. Guvenli kapanis (shutdown/shelve) bitmeden pencereyi kapatma: istegi
        # X dugmesiyle ayni akisa (close_machine) yonlendir. Akis bitince _finish_close
        # _close_confirmed'i acip tekrar close() cagirir.
        if not self._close_confirmed:
            event.ignore()
            # spontaneous: istek pencere sisteminden geldi (Alt+F4, gorev cubugu, isletim sistemi);
            # degilse programdan (sinyal isleyicisi ya da kod) close() cagrildi.
            if event.spontaneous():
                source = "window close request from the window system (Alt+F4 / taskbar / OS)"
            else:
                source = "close() called by the program (signal handler or code)"
            log.warning("closeEvent before the secure close finished: %s -> redirecting to secure close", source)
            # close_machine'i closeEvent icinden dogrudan cagirma: hemen bitiyorsa (sunucu zaten
            # shelved ya da baska biri iceride) icindeki self.close() Qt tarafindan yok sayilir
            # (closeEvent calisirken ayni pencereye close() etkisizdir). Bir sonraki donguye ertele.
            QTimer.singleShot(0, lambda: self.close_machine(source))
            return

        # Uygulama capindaki event filter'i gercekten kaldir (asagidaki eski
        # self.removeEventFilter(self) bunu yapmiyordu) ve kapanis bayragini kaldir.
        self._closing = True
        QApplication.instance().removeEventFilter(self)

        log.info("window closing: sending set_passive")
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

        if hasattr(self, 'heartbeat_timer') and self.heartbeat_timer:
            self.heartbeat_timer.stop()
            self.heartbeat_timer.deleteLater()
            self.heartbeat_timer = None

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

        log.info("VNC window closed")
        event.accept()

    def handle_escape_shortcut(self):
        log.info("Escape shortcut fired (fullscreen=%s)", self.isFullScreen())
        if self.isFullScreen():
            self.toggle_fullscreen()

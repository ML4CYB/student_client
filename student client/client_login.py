import sys
import signal
import requests
import uuid


from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QApplication, QWidget, QMainWindow, QVBoxLayout,
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox,QTableWidget, QTableWidgetItem ,QHeaderView
)



from loginwindow import LoginWindow


def install_signal_handlers(app, get_main_window):
    """Terminalden Ctrl+C (SIGINT), Ctrl+Break (SIGBREAK, Windows) ve kill (SIGTERM) gelince
    uygulamayi aniden oldurmek yerine guvenli kapanis prosedurune yonlendirir:
      - acik bir Desktop/SSH penceresi varsa: pencere X dugmesine basilmis gibi kapatilir
        (shutdown/shelve + set_passive), kapanis bitince uygulama da kapanir
      - yoksa: uygulama dogrudan kapanir (kapatilacak bir oturum yok)
    get_main_window: o anki MainWindow'u (ya da None) donduren fonksiyon.
    """

    def request_safe_exit():
        main_window = get_main_window()
        if main_window is not None and main_window._has_open_session():
            main_window.vnc.destroyed.connect(app.quit)   # pencere kapaninca uygulama da kapansin
            main_window.vnc.close()                        # closeEvent -> close_machine
        else:
            app.quit()

    def handler(signum, frame):
        # Python sinyal isleyicisinde Qt'ye dokunma, isi olay dongusune birak
        QTimer.singleShot(0, request_safe_exit)

    for name in ("SIGINT", "SIGTERM", "SIGBREAK"):
        sig = getattr(signal, name, None)
        if sig is not None:
            signal.signal(sig, handler)

    # Qt olay dongusu C++'ta beklerken Python sinyal isleyicileri calismaz; bos bir zamanlayici
    # Python'un duzenli araliklarla kod calistirmasini saglar.
    pump = QTimer(app)
    pump.timeout.connect(lambda: None)
    pump.start(250)
    return pump


if __name__ == "__main__":
    baseurl = "https://j.cradlelab.us"
    app = QApplication(sys.argv)

    app.setStyle("Fusion")

    login = LoginWindow(baseurl)
    signal_pump = install_signal_handlers(app, lambda: login.main_window)

    login.show()
    sys.exit(app.exec())

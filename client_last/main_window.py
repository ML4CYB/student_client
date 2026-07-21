
import sys
import requests
import uuid


from PyQt6.QtCore import Qt ,QTimer
from PyQt6.QtWidgets import (
    QApplication, QWidget, QMainWindow, QVBoxLayout, 
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox,QTableWidget, QTableWidgetItem ,QHeaderView
)
from vnc import JetstreamClient


class MainWindow(QMainWindow):
    def __init__(self, token,baseurl,password):
        super().__init__()
        self.token = token  
        self.setWindowTitle("Jetstream Panel")
        self.resize(600, 500) 
        self.baseurl = baseurl
        self.password = password
        
        # Ana Ekran Düzeni
        central_widget = QWidget()
        self.main_layout = QVBoxLayout(central_widget)
        
        welcome_label = QLabel("Welcome to Jetstream Client!")
        welcome_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #2c3e50;")
        welcome_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.main_layout.addWidget(welcome_label)
        
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(["Server Name", "OS ID", "Status", "Connect"])
        
        # Tablo başlıklarının genişlik ayarları
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch) 
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        
        self.main_layout.addWidget(self.table)
        self.setCentralWidget(central_widget)
        self.load_servers()

    def load_servers(self):
        url = self.baseurl + "/server/list" 
        payload = {"token": self.token}


        try:

            response = requests.post(url, json=payload, timeout=5)
            print("bir "+response.text)
            data = response.json()
            server_list = data.get("result")            
            self.table.setRowCount(len(server_list))
            
            for row_idx, server in enumerate(server_list):
                self.table.setItem(row_idx, 0, QTableWidgetItem(server["server_name"]))
                self.table.setItem(row_idx, 1, QTableWidgetItem(server["os_id"]))

                staturl = self.baseurl + "/server/status"
                payload = {"token": self.token, "server_id": server["os_id"]}
                response = requests.post(staturl, json=payload, timeout=5)
                print("iki "+response.text)
                statdata = response.json()
                status = statdata.get("server_status", "UNKNOWN")
                print(status)
                self.table.setItem(row_idx, 2, QTableWidgetItem(status))
                
                button_widget = QWidget()
                button_layout = QHBoxLayout(button_widget)
                button_layout.setContentsMargins(5, 2, 5, 2) 
                button_layout.setSpacing(5)
                
                btn_desktop = QPushButton("Desktop")
                btn_desktop.setStyleSheet("background-color: #3498db; color: white; font-weight: bold; padding: 4px 8px;")
                btn_desktop.clicked.connect(lambda checked, s=server: self.handle_desktop(s,open=False,desktop=True))
                
                btn_ssh = QPushButton("SSH")
                btn_ssh.setStyleSheet("background-color: #2ecc71; color: white; font-weight: bold; padding: 4px 8px;")
                btn_ssh.clicked.connect(lambda checked, s=server: self.handle_ssh(s))
                
                button_layout.addWidget(btn_desktop)
                button_layout.addWidget(btn_ssh)
                self.table.setCellWidget(row_idx, 3, button_widget)

                self.table.resizeColumnsToContents()
                
        except Exception as e:
            print(f"Hata oluştu: {e}")

    def handle_desktop(self, server_info,open=False,desktop=False):
        url = self.baseurl + "/server/open"
        if desktop : 
            my_type = "desktop"
        else  :
            my_type = "ssh"
        if open :
            reg_id = self.server_login_list
            payload = {"token":self.token , "server_id":server_info["os_id"],"reg_id": reg_id ,"reconnect" :1,"password":self.password,"guac" : server_info["guac"], "type" : my_type}
        else : 
            reg_id = server_info["id"]
            payload = {"token":self.token , "server_id":server_info["os_id"],"reg_id": reg_id,"password":self.password ,"guac" : server_info["guac"], "type" : my_type}
        response = requests.post(url,json=payload , timeout=5)
        print("uc "+response.text)
        data = response.json()
        status = data.get("status",None)
        self.server_login_list = data.get("log_reg_id",None);
        vncurl = data.get("url",None)
        if status != 1 :
            QMessageBox.information(self, "Error", "Could not get url")
        else : 
            if not vncurl: 
                self._start_server_polling(server_info,desktop)
            else : 
                self.vnc = JetstreamClient(vncurl,server_info,self.token,self.baseurl,self.server_login_list)
                self.vnc.show()



    def _start_server_polling(self, server_info,desktop=False):
        """Sunucu hazır olana kadar her 5 saniyede bir /server/status adresini kontrol eder."""
        # Kullanıcıya bilgi ver
        if not hasattr(self, '_polling_dialog') or self._polling_dialog is None:
            self._polling_dialog = QMessageBox(self)
            self._polling_dialog.setWindowTitle("Preparing Server")
            self._polling_dialog.setText("Preparing Server, Please Wait...")
            #self._polling_dialog.setStandardButtons(QMessageBox.StandardButton.Cancel)
            #self._polling_dialog.buttonClicked.connect(self._cancel_polling)
            self._polling_dialog.show()

        # QTimer ile 5 saniye sonra tekrar kontrol et
        self._polling_timer = QTimer(self)
        self._polling_timer.setSingleShot(True)
        self._polling_timer.timeout.connect(lambda: self._check_server_status(server_info,desktop))
        self._polling_timer.start(5000)  # 5000 ms = 5 saniye

    def _check_server_status(self, server_info,desktop=False):
        """Sunucu durumunu kontrol eder, hazırsa bağlantıyı açar."""
        try:
            url = self.baseurl + "/server/status"
            payload = {"token": self.token, "server_id": server_info["os_id"]}
            response = requests.post(url, json=payload, timeout=5)
            data = response.json()
            status = data.get("status", None)
            if status == 1:
                if server_info["guac"] == 1:
                    is_guac_ready  = data.get("guac",False)
                    if is_guac_ready : 
                        self._stop_polling_dialog()
                        self.handle_desktop(server_info,open=True,desktop = desktop)  # Kendini çağır
                    else:
                        # Henüz hazır değil, 5 saniye sonra tekrar dene
                        self._polling_timer = QTimer(self)
                        self._polling_timer.setSingleShot(True)
                        self._polling_timer.timeout.connect(lambda: self._check_server_status(server_info,desktop))
                        self._polling_timer.start(5000)
                else: 
                    self._stop_polling_dialog()
                    self.handle_desktop(server_info,open=True,desktop=desktop)  # Kendini çağır
            else:
                # Henüz hazır değil, 5 saniye sonra tekrar dene
                self._polling_timer = QTimer(self)
                self._polling_timer.setSingleShot(True)
                self._polling_timer.timeout.connect(lambda: self._check_server_status(server_info,desktop))
                self._polling_timer.start(5000)

        except Exception as e:
            # Hata durumunda da tekrar dene
            self._polling_timer = QTimer(self)
            self._polling_timer.setSingleShot(True)
            self._polling_timer.timeout.connect(lambda: self._check_server_status(server_info,desktop))
            self._polling_timer.start(5000)

    def _cancel_polling(self, button):
        if hasattr(self, '_polling_timer') and self._polling_timer:
            self._polling_timer.stop()
            self._polling_timer = None
        self._stop_polling_dialog()

    def _stop_polling_dialog(self):
        """Polling dialog'unu kapat."""
        if hasattr(self, '_polling_dialog') and self._polling_dialog:
            self._polling_dialog.close()
            self._polling_dialog = None

    def handle_ssh(self, server_info):
        self.handle_desktop(server_info,open=False,desktop=False)

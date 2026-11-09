
import sys
import requests
import uuid


from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication, QWidget, QMainWindow, QVBoxLayout, 
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox,QTableWidget, QTableWidgetItem ,QHeaderView
)
from  main_window import MainWindow
from vnc import REQUEST_TIMEOUT
from client_log import log, api_post

class LoginWindow(QWidget):
    def __init__(self,baseurl):
        super().__init__()
        self.windowid = id = uuid.uuid4().hex
        self.setWindowTitle("Jetstream Client- User Login")
        self.resize(350, 250)
        self.setMinimumSize(350, 250)
        self.baseurl = baseurl
        
        layout = QVBoxLayout()
        layout.setSpacing(15)
        layout.setContentsMargins(30, 30, 30, 30)


        title = QLabel("Login Your Account")
        title.setStyleSheet("font-size: 18px; font-weight: bold; margin-bottom: 10px;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title)


        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("User Name")
        self.username_input.setStyleSheet("padding: 8px; font-size: 13px;")
        layout.addWidget(self.username_input)

        self.password_input = QLineEdit()
        self.password_input.setPlaceholderText("Password")
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password) 
        self.password_input.setStyleSheet("padding: 8px; font-size: 13px;")
        layout.addWidget(self.password_input)


        self.login_btn = QPushButton("Login")
        self.login_btn.setStyleSheet("""
            QPushButton { background-color: #2980b9; color: white; padding: 10px; font-size: 14px; font-weight: bold; border: none; border-radius: 4px; }
            QPushButton:hover { background-color: #3498db; }
        """)
        self.login_btn.clicked.connect(self.handle_login)
        layout.addWidget(self.login_btn)

        self.setLayout(layout)
        self.main_window = None 


    def handle_login(self):
        username = self.username_input.text().strip()
        password = self.password_input.text().strip()

        # Giriş Validasyonu
        if not username or not password:
            QMessageBox.warning(self, "Error", "Please Fill All fields!")
            return

        url = self.baseurl
        log.info("login attempt for user %r", username)   # parola ASLA loglanmaz
        payload = {
            "username": username,
            "password": password,
            "window_id" : self.windowid
        }

        try:
            data = api_post(url, payload, REQUEST_TIMEOUT)
            

            # (cevap api_post icinde JSON olarak ayristirildi)
            status = data.get("status") 
            
            if status == 1:
                token = data.get("token", "")
                log.info("login OK")
                QMessageBox.information(self, "Successful", "You Are Redirecting to Main Window")
                self.main_window = MainWindow(token,self.baseurl,password)
                self.main_window.show()
                self.close() 
                
            elif status == 2:
                log.warning("login rejected: username or password is wrong")
                QMessageBox.warning(self, "Error", "Username or Password Is Wrong")
                
            elif status == 0:
                detail = data.get("detail")
                log.warning("login system error: %s", str(detail)[:160])
                QMessageBox.critical(self, "System Error", detail )
                
            else:
                QMessageBox.warning(self, "Unkown Status", "Server sent unknown code")

        except requests.exceptions.Timeout:
            QMessageBox.critical(self, "Connection Error", "Server Timed Out")
        except requests.exceptions.ConnectionError:
            QMessageBox.critical(self, "Connection Error", "Cannot Connect Server check url")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Unknown Error:\n{str(e)}")

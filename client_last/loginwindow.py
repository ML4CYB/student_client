
import sys
import requests
import uuid


from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication, QWidget, QMainWindow, QVBoxLayout, 
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox,QTableWidget, QTableWidgetItem ,QHeaderView
)
from  main_window import MainWindow

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


        self.login_btn = QPushButton("Giriş Yap")
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
            QMessageBox.warning(self, "Hata", "Lütfen tüm alanları doldurun!")
            return

        url = self.baseurl
        payload = {
            "username": username,
            "password": password,
            "window_id" : self.windowid
        }

        try:
            response = requests.post(url, json=payload, timeout=5)
            

            data = response.json()
            status = data.get("status") 
            
            if status == 1:
                token = data.get("token", "")
                QMessageBox.information(self, "Successful", "You Are Redirecting to Main Window")
                self.main_window = MainWindow(token,self.baseurl,password)
                self.main_window.show()
                self.close() 
                
            elif status == 2:
                QMessageBox.warning(self, "Error", "Username or Password Is Wrong")
                
            elif status == 0:
                detail = data.get("detail")
                QMessageBox.critical(self, "System Error", detail )
                
            else:
                QMessageBox.warning(self, "Unkown Status", "Server sent unknown code")

        except requests.exceptions.Timeout:
            QMessageBox.critical(self, "Connection Error", "Server Timed Out")
        except requests.exceptions.ConnectionError:
            QMessageBox.critical(self, "Connection Error", "Cannot Connect Server check url")
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Unknown Error:\n{str(e)}")
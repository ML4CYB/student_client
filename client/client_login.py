import sys
import requests
import uuid


from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QApplication, QWidget, QMainWindow, QVBoxLayout, 
    QHBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox,QTableWidget, QTableWidgetItem ,QHeaderView
)



from loginwindow import LoginWindow



if __name__ == "__main__":
    baseurl = "http://149.165.153.255"
    app = QApplication(sys.argv)

    app.setStyle("Fusion")
    
    login = LoginWindow(baseurl)
    
    login.show()
    sys.exit(app.exec())
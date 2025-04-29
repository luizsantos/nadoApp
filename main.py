# NadosApp/main.py
import sys
import os
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QCoreApplication

# Adiciona o diretório atual ao sys.path para encontrar main_window e outros módulos
script_dir = os.path.dirname(os.path.abspath(__file__))
if script_dir not in sys.path:
    sys.path.append(script_dir)

# Importa a janela principal
try:
    from main_window import MainWindow
except ImportError as e:
    print(f"Erro ao importar MainWindow: {e}")
    print("Verifique se main_window.py está no diretório correto ou no sys.path.")
    sys.exit(1)

# --- Configurações Globais (Podem ser movidas ou removidas se não usadas aqui) ---
# Estas constantes agora são definidas DENTRO de main_window.py,
# então não são estritamente necessárias aqui, a menos que usadas para outra coisa.
# APP_NAME = "NadosApp"
# APP_VERSION = "0.2.0"
# DB_FOLDER = "data"
# DB_FILENAME = "nadosapp.db"
# TARGET_CLUB_NAME = "Fundação De Esportes De Campo Mourão"

# # Monta o caminho completo para o banco de dados
# DB_FILE = os.path.join(script_dir, DB_FOLDER, DB_FILENAME)

# # Garante que o diretório de dados exista (redundante se main_window já faz)
# os.makedirs(os.path.join(script_dir, DB_FOLDER), exist_ok=True)

if __name__ == '__main__':
    # Configurações da aplicação Qt
    QCoreApplication.setApplicationName("NadosApp")
    # QCoreApplication.setApplicationVersion(APP_VERSION) # Opcional

    app = QApplication(sys.argv)

    # --- CORREÇÃO AQUI ---
    # Instancia a janela principal SEM passar os argumentos
    window = MainWindow()
    # --- FIM DA CORREÇÃO ---

    window.show()
    sys.exit(app.exec())


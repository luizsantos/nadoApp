# NadosApp/main_window.py
import sys
import os
from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QTabWidget, QMessageBox
from PySide6.QtCore import Slot

# Adiciona diretório pai para encontrar 'core' e 'widgets'
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = script_dir # Assume que main_window.py está na raiz do NadosApp
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

# Importa as abas dos widgets
from widgets.import_tab import ImportTab
from widgets.view_data_tab import ViewDataTab
from widgets.filter_data_tab import FilterDataTab
from widgets.analysis_tab import AnalysisTab
from widgets.edit_meet_tab import EditMeetTab 
from widgets.meet_summary_tab import MeetSummaryTab
from widgets.athlete_report_tab import AthleteReportTab
from widgets.stroke_report_tab import StrokeReportTab # <<< ADICIONAR
from widgets.about_tab import AboutTab # <<< ADICIONAR


# --- Configurações ---
APP_DIR = parent_dir
DB_DIR = os.path.join(APP_DIR, 'data')
DB_PATH = os.path.join(DB_DIR, 'nadosapp.db') # Nome padrão do banco
# TARGET_CLUB = "Fundação De Esportes De Campo Mourão" # Defina o nome exato do seu clube alvo

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NadosApp - Importador e Visualizador LENEX")
        self.setGeometry(100, 100, 1200, 800) # Aumentei um pouco a largura

        # Garante que o diretório de dados exista
        os.makedirs(DB_DIR, exist_ok=True)

        # Verifica a conexão inicial com o DB (get_db_connection já lida com setup/update)
        # Importa get_db_connection aqui para garantir uso da versão atualizada
        from core.database import get_db_connection
        self.db_conn_check = get_db_connection(DB_PATH)
        if not self.db_conn_check:
            QMessageBox.critical(self, "Erro Crítico", f"Não foi possível conectar ou criar o banco de dados em:\n{DB_PATH}\nO aplicativo será fechado.")
            sys.exit(1)
        self.db_conn_check.close() # Fecha a conexão de verificação

        self._init_ui()

    def _init_ui(self):
        # Widget Central e Layout Principal
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)

        # Sistema de Abas
        self.tabs = QTabWidget()
        main_layout.addWidget(self.tabs)

        # --- Criação das Abas ---
        # 1. Aba de Importação
        # Passa o valor padrão, mas o usuário pode alterar na UI
        self.import_tab = ImportTab(DB_PATH, default_target_club="Fundação De Esportes De Campo Mourão")
        self.tabs.addTab(self.import_tab, "Importar Dados")

        # 5. NOVA Aba de Edição de Competições
        self.edit_meet_tab = EditMeetTab(DB_PATH)
        self.tabs.addTab(self.edit_meet_tab, "Editar Dados") # <<< Adiciona a nova aba

        # 2. Aba de Visualização/Filtro Simples (ViewDataTab)
        self.view_data_tab = ViewDataTab(DB_PATH)
        self.tabs.addTab(self.view_data_tab, "Visualizar Dados")

        # 3. Aba de Filtro Avançado (FilterDataTab)
        #self.filter_data_tab = FilterDataTab(DB_PATH)
        #self.tabs.addTab(self.filter_data_tab, "Filtrar Dados")

        # <<< NOVA Aba de Resumo da Competição >>>
        self.meet_summary_tab = MeetSummaryTab(DB_PATH)
        self.tabs.addTab(self.meet_summary_tab, "Análise de Competição")

        self.athlete_report_tab = AthleteReportTab(DB_PATH)
        self.tabs.addTab(self.athlete_report_tab, "Análise de Atleta")

        # --- Aba Relatório por Estilo ---
        self.stroke_report_tab = StrokeReportTab(DB_PATH) # <<< ADICIONAR
        self.tabs.addTab(self.stroke_report_tab, "Análise de Estilo") # <<< CORRIGIDO de tab_widget para tabs

        # 4. Aba de Análise (AnalysisTab)
        self.analysis_tab = AnalysisTab(DB_PATH)
        self.tabs.addTab(self.analysis_tab, "Gráficos")


        # --- Aba Sobre ---
        self.about_tab = AboutTab() # <<< ADICIONAR
        self.tabs.addTab(self.about_tab, "Sobre") # <<< ADICIONAR

        # --- Conectar Sinais ---
        # Conecta o sinal de sucesso da importação aos slots de refresh das outras abas
        self.import_tab.import_success.connect(self.view_data_tab.refresh_data)
        #self.import_tab.import_success.connect(self.filter_data_tab.refresh_data)
        self.import_tab.import_success.connect(self.analysis_tab.refresh_data)
        self.import_tab.import_success.connect(self.edit_meet_tab.refresh_data)
        self.import_tab.import_success.connect(self.meet_summary_tab.refresh_data)
        self.import_tab.import_success.connect(self.athlete_report_tab.refresh_data) # <<< Conecta o sinal
        self.import_tab.import_success.connect(self.stroke_report_tab.refresh_data) # <<< CORRIGIDO - Conectar ao sinal import_success


    # Opcional: Método closeEvent para garantir fechamento limpo
    # def closeEvent(self, event):
    #     # Adicionar lógica se necessário para fechar conexões ou threads
    #     print("Fechando NadosApp...")
    #     # Se houver conexões persistentes, fechá-las aqui
    #     event.accept()

# O código em main.py para iniciar a aplicação permanece o mesmo

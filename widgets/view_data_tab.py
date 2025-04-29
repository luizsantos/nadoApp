# NadosApp/widgets/view_data_tab.py
import sys
import os
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QTableWidget,
                               QTableWidgetItem, QAbstractItemView, QMessageBox,
                               QPushButton) # Adicionado QPushButton
from PySide6.QtCore import Slot
import sqlite3

# Adiciona o diretório pai ao sys.path para encontrar 'core'
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

# Importa funções do core.database
from core.database import get_db_connection

class ViewDataTab(QWidget):
    def __init__(self, db_path, parent=None):
        super().__init__(parent)
        self.db_path = db_path

        # --- Layout Principal ---
        self.main_layout = QVBoxLayout(self)

        # --- Botão de Atualizar ---
        # Adiciona um botão para recarregar os dados manualmente
        self.btn_refresh = QPushButton("Atualizar Dados")
        self.btn_refresh.clicked.connect(self.refresh_data)
        self.main_layout.addWidget(self.btn_refresh)

        # --- Tabela de Resultados ---
        self.table_widget = QTableWidget()
        self.table_widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_widget.setAlternatingRowColors(True)
        self.table_widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_widget.setSortingEnabled(True)
        self.main_layout.addWidget(QLabel("Todos os Resultados Importados:"))
        self.main_layout.addWidget(self.table_widget)

        self.setLayout(self.main_layout)

        # --- Inicialização ---
        self.refresh_data() # Carrega os dados ao iniciar

    @Slot()
    def refresh_data(self):
        """Busca todos os resultados e atualiza a tabela."""
        print("ViewDataTab: Executando refresh_data...") # Debug
        # Query simplificada para buscar todos os dados (JOIN correto)
        query_string = """
            SELECT
                am.first_name || ' ' || am.last_name AS Atleta,
                SUBSTR(am.birthdate, 1, 4) AS AnoNasc,
                e.prova_desc AS Prova,
                m.pool_size_desc AS Piscina,
                r.swim_time AS Tempo,
                r.place AS Colocacao,
                r.status AS Status,
                m.name AS NomeCompeticao,
                m.city AS CidadeCompeticao,
                m.start_date AS Data
            FROM ResultCM r
            JOIN AthleteMeetLink aml ON r.link_id = aml.link_id
            JOIN AthleteMaster am ON aml.license = am.license
            JOIN Meet m ON r.meet_id = m.meet_id
            JOIN Event e ON r.event_db_id = e.event_db_id -- JOIN CORRETO
            ORDER BY m.start_date DESC, Atleta, e.number
        """
        params = [] # Sem parâmetros para buscar tudo
        conn = None
        try:
            conn = get_db_connection(self.db_path)
            if not conn:
                QMessageBox.critical(self, "Erro de Banco de Dados",
                                     f"Não foi possível conectar ao banco:\n{self.db_path}")
                self._clear_table()
                return

            cursor = conn.cursor()
            print(f"ViewDataTab: Executando query: {query_string}") # Debug
            cursor.execute(query_string, params)

            headers = [description[0] for description in cursor.description]
            data = cursor.fetchall()
            print(f"ViewDataTab: Query retornou {len(data)} linhas.") # Debug

            # Atualiza a tabela
            self._clear_table()
            self.table_widget.setColumnCount(len(headers))
            self.table_widget.setHorizontalHeaderLabels(headers)
            self.table_widget.setRowCount(len(data))

            for row_idx, row_data in enumerate(data):
                for col_idx, cell_data in enumerate(row_data):
                    item = QTableWidgetItem(str(cell_data) if cell_data is not None else "")
                    self.table_widget.setItem(row_idx, col_idx, item)

            self.table_widget.resizeColumnsToContents()

            if not data:
                 print("ViewDataTab: Tabela ficou vazia.") # Debug

        except sqlite3.Error as e:
            QMessageBox.critical(self, "Erro de Consulta", f"Erro ao buscar dados para ViewDataTab:\n{e}\nQuery: {query_string}")
            self._clear_table()
        except Exception as e:
             QMessageBox.critical(self, "Erro Inesperado", f"Ocorreu um erro inesperado em ViewDataTab:\n{e}")
             self._clear_table()
        finally:
            if conn:
                conn.close()

    def _clear_table(self):
        """Limpa a tabela de resultados."""
        self.table_widget.setRowCount(0)
        self.table_widget.setColumnCount(0)


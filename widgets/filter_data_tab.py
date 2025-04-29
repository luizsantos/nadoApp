# NadosApp/widgets/filter_data_tab.py
import sys
import os
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QGridLayout, QLabel,
                               QComboBox, QPushButton, QTableWidget, QTableWidgetItem,
                               QAbstractItemView, QMessageBox, QSpacerItem, QSizePolicy)
from PySide6.QtCore import Slot, Qt
import sqlite3
from collections import defaultdict
from PySide6.QtGui import QFont # Import QFont

# Adiciona o diretório pai ao sys.path para encontrar 'core'
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

# Importa funções do core.database (usando a estrutura existente)
from core.database import get_db_connection

# Constante para a opção "Todos"
ALL_FILTER = "Todos"

class FilterDataTab(QWidget):
    def __init__(self, db_path, parent=None):
        super().__init__(parent)
        self.db_path = db_path

        # --- Layout Principal ---
        self.main_layout = QVBoxLayout(self)

        # --- Layout dos Filtros ---
        filter_group = QWidget()
        filter_layout = QGridLayout(filter_group)
        filter_layout.setContentsMargins(0, 0, 0, 10)
        # ... (definição dos widgets de filtro - sem alterações) ...
        # Labels
        lbl_athlete = QLabel("Atleta:")
        lbl_meet = QLabel("Competição:")
        lbl_event = QLabel("Tipo de Prova:")
        lbl_course = QLabel("Piscina:")
        lbl_birth_year = QLabel("Ano Nasc.:")
        # Combo Boxes (Scroll Boxes)
        self.combo_athlete = QComboBox()
        self.combo_meet = QComboBox()
        self.combo_event = QComboBox()
        self.combo_course = QComboBox()
        self.combo_birth_year = QComboBox()
        # Botão de Aplicar Filtro
        self.btn_apply_filter = QPushButton("Aplicar Filtros")
        self.btn_apply_filter.clicked.connect(self._apply_filters)
        # Adicionar widgets ao layout de filtros (Grid)
        filter_layout.addWidget(lbl_athlete, 0, 0); filter_layout.addWidget(self.combo_athlete, 0, 1)
        filter_layout.addWidget(lbl_meet, 0, 2); filter_layout.addWidget(self.combo_meet, 0, 3)
        filter_layout.addWidget(lbl_event, 1, 0); filter_layout.addWidget(self.combo_event, 1, 1)
        filter_layout.addWidget(lbl_course, 1, 2); filter_layout.addWidget(self.combo_course, 1, 3)
        filter_layout.addWidget(lbl_birth_year, 2, 0); filter_layout.addWidget(self.combo_birth_year, 2, 1)
        filter_layout.addItem(QSpacerItem(20, 10, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum), 2, 2, 1, 2)
        filter_layout.addWidget(self.btn_apply_filter, 3, 0, 1, 4)

        self.main_layout.addWidget(filter_group)

        # --- Tabela de Resultados Filtrados ---
        self.table_widget = QTableWidget()
        self.table_widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_widget.setAlternatingRowColors(True)
        self.table_widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_widget.setSortingEnabled(True)
        self.main_layout.addWidget(QLabel("Resultados Filtrados:"))
        self.main_layout.addWidget(self.table_widget)

        self.setLayout(self.main_layout)

        # --- Inicialização ---
        self._populate_filters()
        # Não aplica filtros automaticamente aqui

    # _populate_filters: Sem alterações necessárias aqui
    def _populate_filters(self):
        """Busca valores distintos no DB e popula os ComboBoxes."""
        conn = None
        try:
            conn = get_db_connection(self.db_path)
            if not conn: return
            cursor = conn.cursor()
            combos = [self.combo_athlete, self.combo_meet, self.combo_event, self.combo_course, self.combo_birth_year]
            for combo in combos: combo.blockSignals(True); combo.clear(); combo.addItem(ALL_FILTER); combo.blockSignals(False)
            # Atletas
            cursor.execute("SELECT license, first_name || ' ' || last_name FROM AthleteMaster ORDER BY last_name, first_name")
            self.combo_athlete.blockSignals(True)
            for license_id, name in cursor.fetchall():
                if name and license_id: self.combo_athlete.addItem(name.strip(), userData=license_id)
            self.combo_athlete.blockSignals(False)
            # Competições
            cursor.execute("SELECT meet_id, name, city FROM Meet ORDER BY name, city")
            self.combo_meet.blockSignals(True)
            for meet_id, name, city in cursor.fetchall():
                if name and meet_id:
                    display_text = name.strip() + (f" ({city.strip()})" if city and city.strip() else "")
                    self.combo_meet.addItem(display_text, userData=meet_id)
            self.combo_meet.blockSignals(False)
            # Provas
            cursor.execute("SELECT DISTINCT prova_desc FROM Event WHERE prova_desc IS NOT NULL ORDER BY prova_desc")
            self.combo_event.blockSignals(True)
            for (prova_desc,) in cursor.fetchall():
                 if prova_desc: self.combo_event.addItem(prova_desc.strip())
            self.combo_event.blockSignals(False)
            # Piscinas
            cursor.execute("SELECT DISTINCT pool_size_desc FROM Meet WHERE pool_size_desc IS NOT NULL AND pool_size_desc != '' ORDER BY pool_size_desc")
            self.combo_course.blockSignals(True)
            for (course_desc,) in cursor.fetchall():
                if course_desc: self.combo_course.addItem(course_desc.strip())
            self.combo_course.blockSignals(False)
            # Ano Nasc.
            cursor.execute("SELECT DISTINCT SUBSTR(birthdate, 1, 4) FROM AthleteMaster WHERE birthdate IS NOT NULL AND LENGTH(birthdate) >= 4 ORDER BY SUBSTR(birthdate, 1, 4) DESC")
            self.combo_birth_year.blockSignals(True)
            for (year,) in cursor.fetchall():
                if year: self.combo_birth_year.addItem(year)
            self.combo_birth_year.blockSignals(False)
        except sqlite3.Error as e: QMessageBox.warning(self, "Erro ao Popular Filtros", f"Não foi possível buscar dados para os filtros:\n{e}")
        finally:
            if conn: conn.close()

    # --- MODIFICAÇÃO AQUI ---
    def _build_query_and_params(self):
        """Constrói a query SQL principal e parâmetros, incluindo IDs e dados do resultado para lookup do Top3."""
        base_query = """
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
                m.start_date AS Data,
                -- IDs e dados do resultado necessários para buscar/comparar com o Top 3 correspondente
                r.meet_id AS ResultMeetID,
                r.event_db_id AS ResultEventDBID,
                r.agegroup_db_id AS ResultAgeGroupDBID,
                r.place AS ResultPlace, -- Adicionado a colocação do resultado
                r.swim_time AS ResultSwimTime -- Adicionado o tempo do resultado
            FROM ResultCM r
            JOIN AthleteMeetLink aml ON r.link_id = aml.link_id
            JOIN AthleteMaster am ON aml.license = am.license
            JOIN Meet m ON r.meet_id = m.meet_id
            JOIN Event e ON r.event_db_id = e.event_db_id -- JOIN CORRETO
        """
        filters = []
        params = []

        # Filtros (sem alterações na lógica de adicionar filtros)
        athlete_license = self.combo_athlete.currentData(); meet_id = self.combo_meet.currentData()
        event_desc = self.combo_event.currentText(); course_desc = self.combo_course.currentText()
        birth_year = self.combo_birth_year.currentText()
        if athlete_license is not None: filters.append("am.license = ?"); params.append(athlete_license)
        if meet_id is not None: filters.append("m.meet_id = ?"); params.append(meet_id)
        if event_desc != ALL_FILTER: filters.append("e.prova_desc = ?"); params.append(event_desc)
        if course_desc != ALL_FILTER: filters.append("m.pool_size_desc = ?"); params.append(course_desc)
        if birth_year != ALL_FILTER: filters.append("SUBSTR(am.birthdate, 1, 4) = ?"); params.append(birth_year)

        # Montar a query final
        query_string = base_query
        if filters: query_string += " WHERE " + " AND ".join(filters)
        query_string += " ORDER BY m.start_date DESC, Atleta, e.number" # Mantém a ordenação

        return query_string, params
    # --- FIM DA MODIFICAÇÃO ---

    # --- MODIFICAÇÃO AQUI ---
    @Slot()
    def _apply_filters(self):
        """Executa a query filtrada, busca Top3 e atualiza a tabela."""
        query_string, params = self._build_query_and_params()
        conn = None
        top3_lookup = defaultdict(dict) # Dicionário para guardar { (meet,event,ag): {place: time} }
        data = []
        original_headers = [] # Para guardar os cabeçalhos da query principal

        try:
            conn = get_db_connection(self.db_path)
            if not conn:
                QMessageBox.critical(self, "Erro DB", f"Não foi possível conectar: {self.db_path}")
                self._clear_table(); return

            cursor = conn.cursor()
            print(f"--- {self.__class__.__name__} ---")
            print(f"Executando Query Principal: {query_string}")
            print(f"Com Parâmetros: {params}")
            cursor.execute(query_string, params)

            # Pega cabeçalhos originais (incluindo os IDs e dados do resultado adicionados)
            original_headers = [description[0] for description in cursor.description]
            data = cursor.fetchall()
            print(f"Query Principal retornou: {len(data)} linhas")

            # Se houver resultados, busca os dados do Top 3 correspondentes
            if data:
                # Encontra os índices das colunas de ID e dados do resultado na query principal
                try:
                    meet_id_idx = original_headers.index('ResultMeetID')
                    event_id_idx = original_headers.index('ResultEventDBID')
                    agegroup_id_idx = original_headers.index('ResultAgeGroupDBID')
                    # Novos índices para a colocação e tempo do resultado do atleta
                    result_place_idx = original_headers.index('ResultPlace')
                    result_swim_time_idx = original_headers.index('ResultSwimTime')

                except ValueError:
                    QMessageBox.critical(self, "Erro Interno", "Não foi possível encontrar colunas de ID/Resultado nos resultados da query principal.")
                    self._clear_table(); return

                # Pega os meet_ids únicos dos resultados encontrados
                meet_ids_in_results = list(set(row[meet_id_idx] for row in data))

                if meet_ids_in_results:
                    # Busca todos os Top3 para os meets relevantes
                    placeholders = ', '.join('?' * len(meet_ids_in_results))
                    top3_query = f"""
                        SELECT meet_id, event_db_id, agegroup_db_id, place, swim_time
                        FROM Top3Result
                        WHERE meet_id IN ({placeholders})
                        ORDER BY place
                    """
                    print(f"Executando Query Top3 para meets: {meet_ids_in_results}")
                    cursor.execute(top3_query, meet_ids_in_results)
                    top3_data = cursor.fetchall()
                    print(f"Query Top3 retornou: {len(top3_data)} linhas")

                    # Constrói o dicionário de lookup
                    for t3_meet, t3_event, t3_ag, t3_place, t3_time in top3_data:
                        # A chave usa None se agegroup_db_id for NULL no banco
                        key = (t3_meet, t3_event, t3_ag)
                        top3_lookup[key][t3_place] = t3_time

            # Define os cabeçalhos FINAIS para a tabela (sem os IDs/dados do resultado, com Top 1/2/3)
            headers_to_display = [h for h in original_headers if h not in ('ResultMeetID', 'ResultEventDBID', 'ResultAgeGroupDBID', 'ResultPlace', 'ResultSwimTime')]
            headers_to_display.extend(["Top 1", "Top 2", "Top 3"]) # Adiciona novas colunas

            # Atualiza a tabela
            self._clear_table()
            self.table_widget.setColumnCount(len(headers_to_display))
            self.table_widget.setHorizontalHeaderLabels(headers_to_display)
            self.table_widget.setRowCount(len(data))

            # Cria uma fonte em negrito
            bold_font = QFont()
            bold_font.setBold(True)

            for row_idx, row_data in enumerate(data):
                # Pega os IDs e dados do resultado desta linha
                current_meet_id = row_data[meet_id_idx]
                current_event_id = row_data[event_id_idx]
                current_agegroup_id = row_data[agegroup_id_idx] # Pode ser None
                athlete_place = row_data[result_place_idx] # Colocação do atleta nesta prova
                athlete_time = row_data[result_swim_time_idx] # Tempo do atleta nesta prova

                # Cria a chave para o lookup do Top3
                lookup_key = (current_meet_id, current_event_id, current_agegroup_id)

                # Busca os tempos do Top 3 no dicionário
                top3_times = top3_lookup.get(lookup_key, {}) # Retorna {} se não encontrar
                top1_time = top3_times.get(1, "") # Retorna "" se não houver tempo para o lugar
                top2_time = top3_times.get(2, "")
                top3_time = top3_times.get(3, "")

                # Popula as colunas originais (exceto os IDs e dados do resultado)
                col_idx_display = 0
                for col_idx_orig, cell_data in enumerate(row_data):
                    # Pula as colunas de ID e dados do resultado que não serão exibidas
                    if original_headers[col_idx_orig] in ('ResultMeetID', 'ResultEventDBID', 'ResultAgeGroupDBID', 'ResultPlace', 'ResultSwimTime'):
                        continue
                    item = QTableWidgetItem(str(cell_data) if cell_data is not None else "")
                    self.table_widget.setItem(row_idx, col_idx_display, item)
                    col_idx_display += 1

                # Popula e formata as novas colunas Top 1, Top 2, Top 3
                # Top 1
                item_top1 = QTableWidgetItem(top1_time)
                # Verifica se o atleta é o 1º e o tempo dele bate com o Top 1
                if athlete_place == 1 and athlete_time == top1_time and top1_time != "":
                     item_top1.setFont(bold_font)
                self.table_widget.setItem(row_idx, col_idx_display, item_top1)

                # Top 2
                item_top2 = QTableWidgetItem(top2_time)
                # Verifica se o atleta é o 2º e o tempo dele bate com o Top 2
                if athlete_place == 2 and athlete_time == top2_time and top2_time != "":
                     item_top2.setFont(bold_font)
                self.table_widget.setItem(row_idx, col_idx_display + 1, item_top2)

                # Top 3
                item_top3 = QTableWidgetItem(top3_time)
                # Verifica se o atleta é o 3º e o tempo dele bate com o Top 3
                if athlete_place == 3 and athlete_time == top3_time and top3_time != "":
                     item_top3.setFont(bold_font)
                self.table_widget.setItem(row_idx, col_idx_display + 2, item_top3)


            self.table_widget.resizeColumnsToContents()

        except sqlite3.Error as e:
            QMessageBox.critical(self, "Erro de Consulta", f"Erro ao executar consulta:\n{e}")
            self._clear_table()
        except Exception as e:
             QMessageBox.critical(self, "Erro Inesperado", f"Ocorreu um erro inesperado:\n{e}")
             import traceback
             print(traceback.format_exc()) # Imprime traceback detalhado no console
             self._clear_table()
        finally:
            if conn:
                conn.close()
    # --- FIM DA MODIFICAÇÃO ---

    # refresh_data: Sem alterações necessárias aqui
    @Slot()
    def refresh_data(self):
        """Atualiza os filtros e reaplica a filtragem atual."""
        print("FilterDataTab: Recebido sinal para refresh_data.")
        current_filters = { 'athlete': self.combo_athlete.currentData(), 'meet': self.combo_meet.currentData(), 'event': self.combo_event.currentText(), 'course': self.combo_course.currentText(), 'birth_year': self.combo_birth_year.currentText(), }
        self._populate_filters()
        # Restaura seleção
        if current_filters['athlete'] is not None: idx_athlete = self.combo_athlete.findData(current_filters['athlete']); self.combo_athlete.setCurrentIndex(idx_athlete if idx_athlete != -1 else 0)
        else: self.combo_athlete.setCurrentIndex(0)
        if current_filters['meet'] is not None: idx_meet = self.combo_meet.findData(current_filters['meet']); self.combo_meet.setCurrentIndex(idx_meet if idx_meet != -1 else 0)
        else: self.combo_meet.setCurrentIndex(0)
        idx_event = self.combo_event.findText(current_filters['event']); self.combo_event.setCurrentIndex(idx_event if idx_event != -1 else 0)
        idx_course = self.combo_course.findText(current_filters['course']); self.combo_course.setCurrentIndex(idx_course if idx_course != -1 else 0)
        idx_birth = self.combo_birth_year.findText(current_filters['birth_year']); self.combo_birth_year.setCurrentIndex(idx_birth if idx_birth != -1 else 0)
        # Re-aplica filtros
        self._apply_filters()

    # _clear_table: Sem alterações
    def _clear_table(self):
        """Limpa a tabela de resultados."""
        self.table_widget.setRowCount(0)
        self.table_widget.setColumnCount(0)


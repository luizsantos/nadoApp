# NadosApp/widgets/view_data_tab.py
import sys
import os
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QGridLayout, QLabel,
                               QComboBox, QPushButton, QTableWidget, QTableWidgetItem,
                               QAbstractItemView, QMessageBox, QSpacerItem, QSizePolicy)
from PySide6.QtCore import Slot, Qt
from PySide6.QtGui import QFont
import sqlite3
from collections import defaultdict, Counter
import re
import statistics
import math

# Adiciona o diretório pai
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

# Importa funções do core.database
from core.database import (get_db_connection, fetch_top3_for_meet,
                           fetch_splits_for_meet)

# Constante para a opção "Todos"
ALL_FILTER = "Todos"

# --- Funções Auxiliares ---
def time_to_seconds(time_str):
    if not time_str: return None; time_str = time_str.strip()
    match_hr = re.match(r'(\d{1,2}):(\d{2}):(\d{2})\.(\d{1,2})$', time_str)
    match_min = re.match(r'(\d{1,2}):(\d{2})\.(\d{1,2})$', time_str)
    match_sec = re.match(r'(\d{1,2})\.(\d{1,2})$', time_str)
    match_sec_only = re.match(r'(\d+)$', time_str)
    try:
        if match_hr: h = int(match_hr.group(1)); m = int(match_hr.group(2)); s = int(match_hr.group(3)); c = int(match_hr.group(4).ljust(2, '0')); return h * 3600 + m * 60 + s + c / 100.0
        elif match_min: m = int(match_min.group(1)); s = int(match_min.group(2)); c = int(match_min.group(3).ljust(2, '0')); return m * 60 + s + c / 100.0
        elif match_sec: s = int(match_sec.group(1)); c = int(match_sec.group(2).ljust(2, '0')); return s + c / 100.0
        elif match_sec_only: return float(match_sec_only.group(1))
        else: return None
    except (ValueError, TypeError): return None

def format_time_diff(diff_seconds):
    if diff_seconds is None: return "N/A"
    if abs(diff_seconds) < 0.001: return "0.00s"
    sign = "+" if diff_seconds >= 0 else "-"; return f"{sign}{abs(diff_seconds):.2f}s"
# --- Fim das Funções Auxiliares ---


class ViewDataTab(QWidget):
    def __init__(self, db_path, parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self.main_layout = QVBoxLayout(self)
        filter_group = QWidget(); filter_layout = QGridLayout(filter_group); filter_layout.setContentsMargins(0, 0, 0, 10)
        lbl_athlete = QLabel("Atleta:"); lbl_meet = QLabel("Competição:"); lbl_event = QLabel("Tipo de Prova:")
        lbl_course = QLabel("Piscina:"); lbl_birth_year = QLabel("Ano Nasc.:")
        self.combo_athlete = QComboBox(); self.combo_meet = QComboBox(); self.combo_event = QComboBox()
        self.combo_course = QComboBox(); self.combo_birth_year = QComboBox()
        self.btn_apply_filter = QPushButton("Aplicar Filtros"); self.btn_apply_filter.clicked.connect(self._apply_filters)
        filter_layout.addWidget(lbl_athlete, 0, 0); filter_layout.addWidget(self.combo_athlete, 0, 1)
        filter_layout.addWidget(lbl_meet, 0, 2); filter_layout.addWidget(self.combo_meet, 0, 3)
        filter_layout.addWidget(lbl_event, 1, 0); filter_layout.addWidget(self.combo_event, 1, 1)
        filter_layout.addWidget(lbl_course, 1, 2); filter_layout.addWidget(self.combo_course, 1, 3)
        filter_layout.addWidget(lbl_birth_year, 2, 0); filter_layout.addWidget(self.combo_birth_year, 2, 1)
        filter_layout.addItem(QSpacerItem(20, 10, QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Minimum), 2, 2, 1, 2)
        filter_layout.addWidget(self.btn_apply_filter, 3, 0, 1, 4); self.main_layout.addWidget(filter_group)
        self.table_widget = QTableWidget(); self.table_widget.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table_widget.setAlternatingRowColors(True); self.table_widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table_widget.setSortingEnabled(True); self.main_layout.addWidget(QLabel("Resultados Filtrados:"))
        self.main_layout.addWidget(self.table_widget); self.setLayout(self.main_layout); self._populate_filters()

    def _populate_filters(self):
        conn = None
        try:
            conn = get_db_connection(self.db_path);
            if not conn: QMessageBox.critical(self, "Erro DB", f"Erro ao conectar: {self.db_path}"); return
            cursor = conn.cursor()
            combos = [self.combo_athlete, self.combo_meet, self.combo_event, self.combo_course, self.combo_birth_year]
            for combo in combos: combo.blockSignals(True); combo.clear(); combo.addItem(ALL_FILTER); combo.blockSignals(False)
            cursor.execute("SELECT license, first_name || ' ' || last_name FROM AthleteMaster ORDER BY last_name, first_name")
            self.combo_athlete.blockSignals(True);
            for license_id, name in cursor.fetchall():
                if name and license_id: self.combo_athlete.addItem(name.strip(), userData=license_id)
            self.combo_athlete.blockSignals(False)
            cursor.execute("SELECT meet_id, name, city FROM Meet ORDER BY name, city")
            self.combo_meet.blockSignals(True);
            for meet_id, name, city in cursor.fetchall():
                if name and meet_id: display_text = name.strip() + (f" ({city.strip()})" if city and city.strip() else ""); self.combo_meet.addItem(display_text, userData=meet_id)
            self.combo_meet.blockSignals(False)
            cursor.execute("SELECT DISTINCT prova_desc FROM Event WHERE prova_desc IS NOT NULL ORDER BY prova_desc")
            self.combo_event.blockSignals(True);
            for (prova_desc,) in cursor.fetchall():
                 if prova_desc: self.combo_event.addItem(prova_desc.strip())
            self.combo_event.blockSignals(False)
            cursor.execute("SELECT DISTINCT pool_size_desc FROM Meet WHERE pool_size_desc IS NOT NULL AND pool_size_desc != '' ORDER BY pool_size_desc")
            self.combo_course.blockSignals(True);
            for (course_desc,) in cursor.fetchall():
                if course_desc: self.combo_course.addItem(course_desc.strip())
            self.combo_course.blockSignals(False)
            cursor.execute("SELECT DISTINCT SUBSTR(birthdate, 1, 4) FROM AthleteMaster WHERE birthdate IS NOT NULL AND LENGTH(birthdate) >= 4 ORDER BY SUBSTR(birthdate, 1, 4) DESC")
            self.combo_birth_year.blockSignals(True);
            for (year,) in cursor.fetchall():
                if year: self.combo_birth_year.addItem(year)
            self.combo_birth_year.blockSignals(False)
        except sqlite3.Error as e: QMessageBox.warning(self, "Erro Filtros", f"Erro ao popular filtros:\n{e}")
        finally:
            if conn: conn.close()

    def _build_query_and_params(self):
        base_query = """
            SELECT
                am.first_name || ' ' || am.last_name AS Atleta, SUBSTR(am.birthdate, 1, 4) AS AnoNasc,
                e.prova_desc AS Prova, m.pool_size_desc AS Piscina, r.swim_time AS Tempo,
                r.place AS Colocacao, r.status AS Status, m.name AS NomeCompeticao,
                m.city AS CidadeCompeticao, m.start_date AS Data, r.meet_id,
                r.result_id_lenex, r.event_db_id, r.agegroup_db_id
            FROM ResultCM r
            JOIN AthleteMeetLink aml ON r.link_id = aml.link_id
            JOIN AthleteMaster am ON aml.license = am.license
            JOIN Meet m ON r.meet_id = m.meet_id
            JOIN Event e ON r.event_db_id = e.event_db_id
        """
        filters = []; params = []
        athlete_license = self.combo_athlete.currentData(); meet_id = self.combo_meet.currentData()
        event_desc = self.combo_event.currentText(); course_desc = self.combo_course.currentText()
        birth_year = self.combo_birth_year.currentText()
        if athlete_license is not None: filters.append("am.license = ?"); params.append(athlete_license)
        if meet_id is not None: filters.append("m.meet_id = ?"); params.append(meet_id)
        if event_desc != ALL_FILTER: filters.append("e.prova_desc = ?"); params.append(event_desc)
        if course_desc != ALL_FILTER: filters.append("m.pool_size_desc = ?"); params.append(course_desc)
        if birth_year != ALL_FILTER: filters.append("SUBSTR(am.birthdate, 1, 4) = ?"); params.append(birth_year)
        query_string = base_query
        if filters: query_string += " WHERE " + " AND ".join(filters)
        query_string += " ORDER BY m.start_date DESC, Atleta, e.number"
        return query_string, params

    @Slot()
    def _apply_filters(self):
        """Executa a query filtrada, busca dados adicionais, calcula (média/DP por VOLTA CORRETA, status na colocação) e atualiza a tabela."""
        query_string, params = self._build_query_and_params()
        conn = None
        final_table_data = []

        try:
            conn = get_db_connection(self.db_path)
            if not conn: QMessageBox.critical(self, "Erro DB", f"Erro ao conectar: {self.db_path}"); self._clear_table(); return

            cursor = conn.cursor()
            print(f"ViewDataTab: Executando Query Principal: {query_string}")
            print(f"ViewDataTab: Com Parâmetros: {params}")
            cursor.execute(query_string, params)

            query_headers = [description[0] for description in cursor.description]
            results_data = cursor.fetchall()
            print(f"ViewDataTab: Query Principal retornou: {len(results_data)} linhas")

            if not results_data: self._clear_table(); return

            # Encontrar índices
            try:
                result_id_idx = query_headers.index('result_id_lenex'); athlete_idx = query_headers.index('Atleta'); birth_idx = query_headers.index('AnoNasc'); event_idx = query_headers.index('Prova'); place_idx = query_headers.index('Colocacao'); time_idx = query_headers.index('Tempo'); status_idx = query_headers.index('Status'); event_db_id_idx = query_headers.index('event_db_id'); agegroup_db_id_idx = query_headers.index('agegroup_db_id'); meet_id_idx = query_headers.index('meet_id')
            except ValueError as e: QMessageBox.critical(self, "Erro Interno", f"Coluna não encontrada na query: {e}"); self._clear_table(); return

            # Buscar Dados Adicionais (Top3 e Parciais)
            meet_ids_in_results = list(set(row[meet_id_idx] for row in results_data)); result_ids_in_results = list(set(row[result_id_idx] for row in results_data))
            top3_lookup = defaultdict(dict); splits_lookup = defaultdict(list)
            if meet_ids_in_results:
                placeholders = ', '.join('?' * len(meet_ids_in_results)); top3_query = f"SELECT event_db_id, agegroup_db_id, place, swim_time FROM Top3Result WHERE meet_id IN ({placeholders})"
                cursor.execute(top3_query, meet_ids_in_results)
                for t3_event, t3_ag, t3_place, t3_time in cursor.fetchall(): top3_lookup[(t3_event, t3_ag)][t3_place] = t3_time
            if result_ids_in_results:
                placeholders = ', '.join('?' * len(result_ids_in_results)); splits_query = f"SELECT result_id_lenex, distance, swim_time FROM SplitCM WHERE result_id_lenex IN ({placeholders}) ORDER BY result_id_lenex, distance"
                cursor.execute(splits_query, result_ids_in_results)
                for split_res_id, _, split_time_str in cursor.fetchall():
                    split_sec = time_to_seconds(split_time_str)
                    if split_sec is not None: splits_lookup[split_res_id].append(split_sec)

            # --- Processar Resultados e Calcular ---
            for row in results_data:
                result_id = row[result_id_idx]; place = row[place_idx]; status = row[status_idx]; event_db_id = row[event_db_id_idx]; ag_db_id = row[agegroup_db_id_idx]; athlete_time_str = row[time_idx]

                # Calcular display_colocacao
                display_colocacao = "N/A"; is_valid_result = status is None or status.upper() == 'OK' or status.upper() == 'OFFICIAL'
                if not is_valid_result and status: display_colocacao = status.upper()
                elif place is not None: display_colocacao = str(place)

                # Calcular diferenças vs Top3
                top3_times_for_event = top3_lookup.get((event_db_id, ag_db_id), {}); top1_time_str = top3_times_for_event.get(1); top2_time_str = top3_times_for_event.get(2); top3_time_str = top3_times_for_event.get(3)
                athlete_secs = time_to_seconds(athlete_time_str); diff1_str = "N/A"; diff2_str = "N/A"; diff3_str = "N/A"
                if athlete_secs is not None:
                    top1_secs = time_to_seconds(top1_time_str); top2_secs = time_to_seconds(top2_time_str); top3_secs = time_to_seconds(top3_time_str)
                    if top1_secs is not None: diff1_str = format_time_diff(athlete_secs - top1_secs)
                    if top2_secs is not None: diff2_str = format_time_diff(athlete_secs - top2_secs)
                    if top3_secs is not None: diff3_str = format_time_diff(athlete_secs - top3_secs)

                # --- Calcular TEMPOS DE VOLTA (INCLUINDO ÚLTIMA), MÉDIA e DP ---
                cumulative_splits_sec = splits_lookup.get(result_id, [])
                lap_times_sec = []
                media_lap_str = "N/A"; dp_lap_str = "N/A"
                last_cumulative_split = 0.0

                print(f"DEBUG [ViewData]: Parciais Acumuladas (sec): {cumulative_splits_sec}") # DEBUG

                if cumulative_splits_sec:
                    previous_split_sec = 0.0
                    print("DEBUG [ViewData]: Calculando voltas intermediárias...") # DEBUG
                    for i, current_split_sec in enumerate(cumulative_splits_sec):
                        lap_time = current_split_sec - previous_split_sec
                        print(f"  DEBUG [ViewData]: Volta {i+1}: Acumulado={current_split_sec:.2f}, Anterior={previous_split_sec:.2f}, Tempo Volta={lap_time:.2f}") # DEBUG
                        if lap_time >= 0:
                            lap_times_sec.append(lap_time)
                        else:
                            print(f"  DEBUG [ViewData]: AVISO - Tempo de volta negativo ou zero ignorado: {lap_time:.2f}") # DEBUG
                        previous_split_sec = current_split_sec
                    last_cumulative_split = previous_split_sec
                    print(f"DEBUG [ViewData]: Última parcial acumulada (sec): {last_cumulative_split:.2f}") # DEBUG

                # Calcular a última volta
                print("DEBUG [ViewData]: Calculando última volta...") # DEBUG
                if athlete_secs is not None and last_cumulative_split >= 0 and cumulative_splits_sec:
                    last_lap_time = athlete_secs - last_cumulative_split
                    print(f"  DEBUG [ViewData]: Tempo Final={athlete_secs:.2f}, Última Parcial Acum.={last_cumulative_split:.2f}, Tempo Última Volta={last_lap_time:.2f}") # DEBUG
                    if last_lap_time >= 0:
                        lap_times_sec.append(last_lap_time)
                    else:
                        print(f"  DEBUG [ViewData]: AVISO - Tempo da última volta negativo ou zero ignorado: {last_lap_time:.2f}") # DEBUG
                elif not cumulative_splits_sec and athlete_secs is not None:
                     print(f"  DEBUG [ViewData]: Sem parciais, usando tempo final como única volta: {athlete_secs:.2f}") # DEBUG
                     lap_times_sec.append(athlete_secs)
                else:
                    print("  DEBUG [ViewData]: Não foi possível calcular a última volta (sem tempo final ou sem parciais anteriores).") # DEBUG

                print(f"DEBUG [ViewData]: Lista final de tempos de volta (sec): {lap_times_sec}") # DEBUG

                if lap_times_sec: # Calcula estatísticas sobre os tempos das voltas
                    try:
                        media = statistics.mean(lap_times_sec)
                        media_lap_str = f"{media:.2f}"
                        print(f"DEBUG [ViewData]: Média calculada: {media:.2f}") # DEBUG
                    except statistics.StatisticsError:
                        media_lap_str = "N/A"
                        print("DEBUG [ViewData]: Erro ao calcular média (StatisticsError)") # DEBUG

                    if len(lap_times_sec) >= 2:
                        try:
                            stdev = statistics.stdev(lap_times_sec);
                            if not math.isnan(stdev):
                                dp_lap_str = f"{stdev:.2f}"
                                print(f"DEBUG [ViewData]: DP calculado: {stdev:.2f}") # DEBUG
                            else:
                                dp_lap_str = "0.00"
                                print("DEBUG [ViewData]: DP é NaN, definido como 0.00") # DEBUG
                        except statistics.StatisticsError:
                            dp_lap_str = "N/A"
                            print("DEBUG [ViewData]: Erro ao calcular DP (StatisticsError)") # DEBUG
                    elif len(lap_times_sec) == 1:
                         dp_lap_str = "0.00"
                         print("DEBUG [ViewData]: Apenas 1 volta, DP definido como 0.00") # DEBUG
                else:
                    print("DEBUG [ViewData]: Lista de tempos de volta vazia, estatísticas definidas como N/A") # DEBUG
                # --- Fim do Cálculo ---

                # Montar dicionário para a linha da tabela final (sem Status)
                final_table_data.append({
                    "Atleta": row[athlete_idx], "AnoNasc": row[birth_idx], "Prova": row[event_idx],
                    "Colocação": display_colocacao,
                    "Tempo": athlete_time_str or "N/A",
                    "Média Lap": media_lap_str,
                    "DP Lap": dp_lap_str,
                    "vs Top3": diff3_str, "vs Top2": diff2_str, "vs Top1": diff1_str
                })
            # --- Fim do Processamento ---

            # --- Popular Tabela ---
            # Define os cabeçalhos finais (sem Status)
            display_headers = ["Atleta", "AnoNasc", "Prova", "Colocação", "Tempo",
                               "Média Lap", "DP Lap",
                               "vs Top3", "vs Top2", "vs Top1"]

            self._clear_table(); self.table_widget.setColumnCount(len(display_headers))
            self.table_widget.setHorizontalHeaderLabels(display_headers); self.table_widget.setRowCount(len(final_table_data))
            bold_font = QFont(); bold_font.setBold(True)

            for row_idx, row_dict in enumerate(final_table_data):
                col_idx = 0; athlete_place_str = row_dict.get("Colocação", "")
                for key in display_headers:
                    value = row_dict.get(key, ""); item = QTableWidgetItem(str(value))
                    # Aplica formatação
                    if key == "vs Top1" and athlete_place_str == "1": item.setFont(bold_font)
                    elif key == "vs Top2" and athlete_place_str == "2": item.setFont(bold_font)
                    elif key == "vs Top3" and athlete_place_str == "3": item.setFont(bold_font)
                    if key == "Colocação" and not value.isdigit() and value != "N/A": item.setForeground(Qt.GlobalColor.red)
                    self.table_widget.setItem(row_idx, col_idx, item); col_idx += 1
            # --- Fim da População ---

            self.table_widget.resizeColumnsToContents()

        except sqlite3.Error as e: QMessageBox.critical(self, "Erro de Consulta", f"Erro ao executar consulta/processamento:\n{e}"); self._clear_table()
        except Exception as e: QMessageBox.critical(self, "Erro Inesperado", f"Ocorreu um erro inesperado ao aplicar filtros:\n{e}"); import traceback; print(traceback.format_exc()); self._clear_table()
        finally:
            if conn: conn.close()

    @Slot()
    def refresh_data(self):
        """Atualiza os filtros e reaplica a filtragem atual."""
        print("ViewDataTab: Recebido sinal para refresh_data.")
        current_filters = {'athlete': self.combo_athlete.currentData(), 'meet': self.combo_meet.currentData(), 'event': self.combo_event.currentText(), 'course': self.combo_course.currentText(), 'birth_year': self.combo_birth_year.currentText(),}
        self._populate_filters()
        if current_filters['athlete'] is not None: idx = self.combo_athlete.findData(current_filters['athlete']); self.combo_athlete.setCurrentIndex(idx if idx != -1 else 0)
        else: self.combo_athlete.setCurrentIndex(0)
        if current_filters['meet'] is not None: idx = self.combo_meet.findData(current_filters['meet']); self.combo_meet.setCurrentIndex(idx if idx != -1 else 0)
        else: self.combo_meet.setCurrentIndex(0)
        idx = self.combo_event.findText(current_filters['event']); self.combo_event.setCurrentIndex(idx if idx != -1 else 0)
        idx = self.combo_course.findText(current_filters['course']); self.combo_course.setCurrentIndex(idx if idx != -1 else 0)
        idx = self.combo_birth_year.findText(current_filters['birth_year']); self.combo_birth_year.setCurrentIndex(idx if idx != -1 else 0)
        self._apply_filters()

    def _clear_table(self):
        self.table_widget.setRowCount(0); self.table_widget.setColumnCount(0)


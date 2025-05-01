# NadosApp/widgets/view_data_tab.py
import sys
import os
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QGridLayout, QLabel, # Adicionado QLabel
                               QComboBox, QPushButton, QTableWidget, QTableWidgetItem,
                               QAbstractItemView, QMessageBox, QSpacerItem, QSizePolicy,
                               QFileDialog, QHBoxLayout) # Adicionado QFileDialog, QHBoxLayout
from PySide6.QtCore import Slot, Qt
from PySide6.QtGui import QFont, QPixmap # Adicionado QPixmap
import sqlite3
from collections import defaultdict, Counter
import re
import statistics
import math
import io # Adicionado para buffer de imagem

# Tentar importar matplotlib
try:
    import matplotlib
    matplotlib.use('Agg') # Usar backend não interativo para evitar problemas de UI
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print("AVISO: Matplotlib não encontrado. Sparklines não estarão disponíveis.")
    # Definir plt como None para verificações posteriores
    plt = None

# Imports do ReportLab (similar ao meet_summary_tab)
try:
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    from reportlab.lib.units import inch, cm
    from reportlab.lib.pagesizes import A4, landscape # Importa landscape
    from reportlab.lib import colors
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
    # Definir classes dummy se necessário para evitar erros, mas a funcionalidade estará desabilitada
    class SimpleDocTemplate: pass; 
    class Paragraph: pass; 
    class Spacer: pass; 
    class Table: pass; landscape = lambda x: x # Dummy landscape
    class TableStyle: pass; 
    class Image: pass; 
    def getSampleStyleSheet(): return {}; colors = None; TA_LEFT=0; TA_CENTER=1; TA_RIGHT=2; cm=1; A4=(0,0)

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

# --- Funções Auxiliares (time_to_seconds, format_time_diff - sem alterações) ---
def time_to_seconds(time_str):
    # ... (código como antes) ...
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
    # ... (código como antes) ...
    if diff_seconds is None: return "N/A"
    if abs(diff_seconds) < 0.001: return "0.00s"
    sign = "+" if diff_seconds >= 0 else "-"; return f"{sign}{abs(diff_seconds):.2f}s"
# --- Fim das Funções Auxiliares ---


class ViewDataTab(QWidget):
    def __init__(self, db_path, parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self.current_table_data = [] # Para guardar os dados processados para exportação
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
        self.table_widget.setAlternatingRowColors(True); self.table_widget.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows);

        # --- Botão Exportar PDF ---
        export_layout = QHBoxLayout()
        self.btn_export_pdf = QPushButton("Exportar para PDF")
        self.btn_export_pdf.clicked.connect(self._export_to_pdf)
        self.btn_export_pdf.setEnabled(False) # Desabilitado inicialmente
        if not REPORTLAB_AVAILABLE or not MATPLOTLIB_AVAILABLE:
            self.btn_export_pdf.setEnabled(False)
            tooltip = ["Exportação PDF indisponível."]
            if not REPORTLAB_AVAILABLE: tooltip.append("- Biblioteca 'reportlab' não encontrada.")
            if not MATPLOTLIB_AVAILABLE: tooltip.append("- Biblioteca 'matplotlib' não encontrada.")
            self.btn_export_pdf.setToolTip("\n".join(tooltip))
        export_layout.addStretch(); export_layout.addWidget(self.btn_export_pdf); export_layout.addStretch()

        self.table_widget.setSortingEnabled(True); self.main_layout.addWidget(QLabel("Resultados Filtrados:"))
        self.main_layout.addWidget(self.table_widget)
        self.main_layout.addLayout(export_layout) # Adiciona layout do botão abaixo da tabela
        self.setLayout(self.main_layout); self._populate_filters()

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

    # --- NOVA FUNÇÃO: Gerar Sparkline ---
    def _generate_sparkline_pixmap(self, lap_times, width_px=80, height_px=20):
        """Gera um QPixmap de um sparkline para os tempos de volta."""
        if not MATPLOTLIB_AVAILABLE or not lap_times:
            return None

        try:
            # Criar figura pequena e sem bordas/padding
            fig, ax = plt.subplots(figsize=(width_px / 72, height_px / 72), dpi=72) # Ajustar DPI se necessário
            fig.subplots_adjust(left=0, right=1, top=1, bottom=0) # Remove padding

            # Plotar os tempos de volta
            ax.plot(range(len(lap_times)), lap_times, color='blue', linewidth=0.8)

            # Opcional: Adicionar linha da média
            if len(lap_times) > 0:
                mean_time = statistics.mean(lap_times)
                ax.axhline(mean_time, color='red', linestyle='--', linewidth=0.5)

            # Remover eixos e bordas
            ax.axis('off')

            # Salvar em buffer
            buf = io.BytesIO()
            fig.savefig(buf, format='png', transparent=True) # Fundo transparente
            buf.seek(0)

            # Criar QPixmap
            pixmap = QPixmap()
            pixmap.loadFromData(buf.read())

            plt.close(fig) # Fechar figura para liberar memória
            return pixmap

        except Exception as e:
            print(f"Erro ao gerar sparkline: {e}")
            # Tentar fechar a figura em caso de erro
            try:
                if 'fig' in locals() and fig:
                    plt.close(fig)
            except: pass # Ignora erros ao fechar
            return None
    # --- FIM DA NOVA FUNÇÃO ---

    # --- NOVA FUNÇÃO: Gerar Sparkline para PDF (copiada de meet_summary_tab) ---
    def _generate_sparkline_pdf_image(self, lap_times, width_px=80, height_px=20):
        """Gera dados de imagem PNG de um sparkline para o PDF."""
        if not MATPLOTLIB_AVAILABLE or not lap_times:
            return None
        try:
            fig, ax = plt.subplots(figsize=(width_px / 72, height_px / 72), dpi=72)
            fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
            ax.plot(range(len(lap_times)), lap_times, color='blue', linewidth=1.5) # Linha um pouco mais grossa para PDF
            if len(lap_times) > 0:
                mean_time = statistics.mean(lap_times)
                ax.axhline(mean_time, color='red', linestyle='--', linewidth=1.0) # Linha média um pouco mais grossa
            ax.axis('off')
            buf = io.BytesIO()
            fig.savefig(buf, format='png', transparent=True)
            plt.close(fig)
            buf.seek(0)
            return buf # Retorna o buffer BytesIO
        except Exception as e:
            print(f"Erro ao gerar sparkline para PDF: {e}")
            try:
                if 'fig' in locals() and fig: plt.close(fig)
            except: pass
            return None
    # --- FIM DA NOVA FUNÇÃO ---

    # --- NOVA FUNÇÃO AUXILIAR: Obter valor comparável para ordenação ---
    def _get_sort_value(self, item, key):
        """Retorna um valor comparável para ordenação a partir do dicionário e chave."""
        value = item.get(key)

        # Lida com None ou N/A - coloca no final por padrão
        if value is None: return float('inf')
        if isinstance(value, str) and value == "N/A": return float('inf')

        # Colunas de Tempo/Numéricas que podem ser string 'N/A' ou tempo formatado
        if key in ["Tempo", "Média Lap", "DP Lap", "vs Top1", "vs Top2", "vs Top3"]:
            if isinstance(value, (int, float)): return value # Já numérico
            if isinstance(value, str):
                # Tenta converter tempo para segundos, tratando o 's' opcional
                seconds = time_to_seconds(value.rstrip('s'))
                return seconds if seconds is not None else float('inf') # Converteu? Usa. Senão, final.
            return float('inf') # Tipo inesperado, coloca no final

        # Coluna AnoNasc
        elif key == "AnoNasc":
            try: return int(value)
            except (ValueError, TypeError): return float('inf') # Não numérico, coloca no final

        # Coluna Colocação (pode ser número ou string como 'DSQ')
        elif key == "Colocação":
            try: return int(value) # Tenta converter para int
            except (ValueError, TypeError): return str(value).lower() # Se falhar, trata como string minúscula

        # Default: Trata como string minúscula
        return str(value).lower()
    # --- FIM DA FUNÇÃO AUXILIAR ---

    @Slot()
    def _apply_filters(self):
        """Executa a query filtrada, calcula dados (incluindo sparkline) e atualiza a tabela."""
        query_string, params = self._build_query_and_params()
        conn = None
        self.current_table_data = [] # Limpa dados antigos antes de aplicar

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

            if not results_data: self._clear_table(); self.btn_export_pdf.setEnabled(False); return # Desabilita exportação se não há dados

            # Encontrar índices
            try:
                result_id_idx = query_headers.index('result_id_lenex'); athlete_idx = query_headers.index('Atleta'); birth_idx = query_headers.index('AnoNasc'); event_idx = query_headers.index('Prova'); place_idx = query_headers.index('Colocacao'); time_idx = query_headers.index('Tempo'); status_idx = query_headers.index('Status'); event_db_id_idx = query_headers.index('event_db_id'); agegroup_db_id_idx = query_headers.index('agegroup_db_id'); meet_id_idx = query_headers.index('meet_id'); city_idx = query_headers.index('CidadeCompeticao'); date_idx = query_headers.index('Data') # Adicionado city_idx e date_idx
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
                city = row[city_idx]; date = row[date_idx] # Pega cidade e data
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

                # Calcular TEMPOS DE VOLTA, MÉDIA e DP
                cumulative_splits_sec = splits_lookup.get(result_id, [])
                lap_times_sec = [] # <<< Armazenar tempos de volta aqui
                media_lap_str = "N/A"; dp_lap_str = "N/A"
                last_cumulative_split = 0.0

                if cumulative_splits_sec:
                    previous_split_sec = 0.0
                    for current_split_sec in cumulative_splits_sec:
                        lap_time = current_split_sec - previous_split_sec
                        if lap_time >= 0: lap_times_sec.append(lap_time)
                        previous_split_sec = current_split_sec
                    last_cumulative_split = previous_split_sec

                if athlete_secs is not None and last_cumulative_split >= 0 and cumulative_splits_sec:
                    last_lap_time = athlete_secs - last_cumulative_split
                    if last_lap_time >= 0: lap_times_sec.append(last_lap_time)
                elif not cumulative_splits_sec and athlete_secs is not None:
                     lap_times_sec.append(athlete_secs)

                if lap_times_sec:
                    try: media = statistics.mean(lap_times_sec); media_lap_str = f"{media:.2f}"
                    except statistics.StatisticsError: media_lap_str = "N/A"
                    if len(lap_times_sec) >= 2:
                        try:
                            stdev = statistics.stdev(lap_times_sec);
                            if not math.isnan(stdev): dp_lap_str = f"{stdev:.2f}"
                            else: dp_lap_str = "0.00"
                        except statistics.StatisticsError:
                            dp_lap_str = "N/A"
                    elif len(lap_times_sec) == 1: dp_lap_str = "0.00"

                # Montar dicionário para a linha da tabela final (com Lap Times)
                self.current_table_data.append({ # Adiciona ao atributo da instância
                    "Atleta": row[athlete_idx], "AnoNasc": row[birth_idx],
                    "Prova": row[event_idx], "Cidade": city, "Data": date, # Adicionado Cidade e Data
                    "Colocação": display_colocacao, "Tempo": athlete_time_str or "N/A",
                    "Média Lap": media_lap_str, "DP Lap": dp_lap_str,
                    "Lap Times": lap_times_sec, # <<< Armazena a lista de tempos
                    "vs Top3": diff3_str, "vs Top2": diff2_str, "vs Top1": diff1_str
                })
            # --- Fim do Processamento ---

            # --- Popular Tabela ---
            # Define os cabeçalhos finais (com Ritmo Sparkline)
            # Move "Cidade" e "Data" para o final
            display_headers = ["Atleta", "AnoNasc", "Prova", "Colocação", "Tempo",
                               "Média Lap", "DP Lap", "Ritmo", # <<< Novo Cabeçalho
                               "vs Top3", "vs Top2", "vs Top1", "Cidade", "Data"] # <<< Movido para o final

            # Limpa APENAS a exibição da tabela, sem limpar self.current_table_data aqui
            self.table_widget.setRowCount(0)
            self.table_widget.setColumnCount(0)
            self.btn_export_pdf.setEnabled(False) # Desabilita exportação temporariamente

            self.table_widget.setColumnCount(len(display_headers))
            self.table_widget.setHorizontalHeaderLabels(display_headers); self.table_widget.setRowCount(len(self.current_table_data))
            bold_font = QFont(); bold_font.setBold(True)

            # Mapeamento de cabeçalho para chave do dicionário
            header_to_key_map = {h: h for h in display_headers} # Inicializa
            header_to_key_map["Cidade"] = "Cidade" # Mapeia o cabeçalho "Cidade"
            header_to_key_map["Data"] = "Data"     # Mapeia o cabeçalho "Data"
            header_to_key_map["Ritmo"] = "Lap Times" # Coluna "Ritmo" usa dados de "Lap Times"

            for row_idx, row_dict in enumerate(self.current_table_data):
                col_idx = 0; athlete_place_str = row_dict.get("Colocação", "")
                for key in display_headers: # Itera sobre os cabeçalhos de exibição
                    dict_key = header_to_key_map[key] # Pega a chave correta
                    value = row_dict.get(dict_key, "") # Busca pelo valor usando a chave

                    # --- Lógica para Sparkline ---
                    if key == "Ritmo":
                        # Remove widget antigo, se houver
                        self.table_widget.setCellWidget(row_idx, col_idx, None)
                        lap_times = value # O valor aqui é a lista lap_times_sec
                        pixmap = self._generate_sparkline_pixmap(lap_times)
                        if pixmap:
                            label = QLabel()
                            label.setPixmap(pixmap)
                            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                            self.table_widget.setCellWidget(row_idx, col_idx, label)
                        else:
                            # Se não gerou pixmap, coloca N/A como texto
                            item = QTableWidgetItem("N/A")
                            item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                            self.table_widget.setItem(row_idx, col_idx, item)
                    # --- Fim da Lógica Sparkline ---
                    else:
                        # Para outras colunas, usa QTableWidgetItem
                        # Remove widget antigo, se houver (caso a coluna mude de tipo)
                        self.table_widget.setCellWidget(row_idx, col_idx, None)
                        item = QTableWidgetItem(str(value))
                        # Aplica formatação
                        if key == "vs Top1" and athlete_place_str == "1": item.setFont(bold_font)
                        elif key == "vs Top2" and athlete_place_str == "2": item.setFont(bold_font)
                        elif key == "vs Top3" and athlete_place_str == "3": item.setFont(bold_font)
                        if key == "Colocação" and not str(value).isdigit() and str(value) != "N/A": item.setForeground(Qt.GlobalColor.red)
                        self.table_widget.setItem(row_idx, col_idx, item)

                    col_idx += 1
            # --- Fim da População ---

            self.table_widget.resizeColumnsToContents()
            # Ajustar largura da coluna Sparkline manualmente se necessário
            try:
                sparkline_col_index = display_headers.index("Ritmo")
                self.table_widget.setColumnWidth(sparkline_col_index, 90) # Ajustar largura
            except ValueError:
                pass # Coluna não encontrada

            # Habilita botão de exportar se as libs estiverem ok
            if self.current_table_data: # Só habilita se realmente populou algo
                self.btn_export_pdf.setEnabled(REPORTLAB_AVAILABLE and MATPLOTLIB_AVAILABLE)

        except sqlite3.Error as e:
            QMessageBox.critical(self, "Erro de Consulta", f"Erro ao executar consulta/processamento:\n{e}")
            self._clear_table(); self.btn_export_pdf.setEnabled(False); self.current_table_data = []
        except Exception as e:
            QMessageBox.critical(self, "Erro Inesperado", f"Ocorreu um erro inesperado ao aplicar filtros:\n{e}")
            import traceback; print(traceback.format_exc()); self._clear_table(); self.btn_export_pdf.setEnabled(False); self.current_table_data = []
        finally:
            if conn: conn.close()

    @Slot()
    def _export_to_pdf(self):
        """Exporta os dados filtrados atuais (self.current_table_data) para PDF."""
        if not REPORTLAB_AVAILABLE or not MATPLOTLIB_AVAILABLE:
             tooltip = ["Exportação PDF indisponível."]
             if not REPORTLAB_AVAILABLE: tooltip.append("- Biblioteca 'reportlab' não encontrada.")
             if not MATPLOTLIB_AVAILABLE: tooltip.append("- Biblioteca 'matplotlib' não encontrada.")
             QMessageBox.warning(self, "Funcionalidade Indisponível", "\n".join(tooltip))
             return

        if not self.current_table_data:
            QMessageBox.warning(self, "Nenhum Dado", "Não há dados filtrados para exportar. Aplique os filtros primeiro.")
            return

        # --- Obter Informação de Ordenação da Tabela ---
        header = self.table_widget.horizontalHeader()
        sort_col_index = header.sortIndicatorSection()
        sort_order = header.sortIndicatorOrder()
        sort_dict_key = None
        key_func = None

        # Mapeamento de cabeçalho para chave do dicionário (necessário aqui para encontrar a chave de ordenação)
        pdf_headers = ["Atleta", "Nasc", "Prova", "Col", "Tempo", "Média Lap", "DP Lap", "Ritmo", "vs T3", "vs T2", "vs T1", "Cidade", "Data"]
        header_to_key_map_pdf = { # Mapeamento para chaves do dicionário self.current_table_data
            "Atleta": "Atleta", "Nasc": "AnoNasc", "Prova": "Prova", "Col": "Colocação", "Tempo": "Tempo",
            "Média Lap": "Média Lap", "DP Lap": "DP Lap", "Ritmo": "Lap Times", "vs T3": "vs Top3",
            "vs T2": "vs Top2", "vs T1": "vs Top1", "Cidade": "Cidade", "Data": "Data"
        }
        # Mapeamento reverso (índice da coluna visual -> chave do dicionário)
        current_display_headers = [self.table_widget.horizontalHeaderItem(i).text() for i in range(self.table_widget.columnCount())]
        header_to_key_map_display = {h: h for h in current_display_headers}
        header_to_key_map_display["Ritmo"] = "Lap Times" # Ajuste para coluna Ritmo
        header_to_key_map_display["Cidade"] = "Cidade"
        header_to_key_map_display["Data"] = "Data"

        if sort_col_index != -1 and 0 <= sort_col_index < len(current_display_headers):
            sort_header_text = current_display_headers[sort_col_index]
            sort_dict_key = header_to_key_map_display.get(sort_header_text)
            if sort_dict_key == "Lap Times": # Não ordenar pela lista de parciais diretamente
                sort_dict_key = None
            elif sort_dict_key:
                key_func = lambda item: self._get_sort_value(item, sort_dict_key)
        # --- Fim da Obtenção de Ordenação ---

        # --- Gerar Nome de Arquivo Descritivo ---
        athlete_filter = self.combo_athlete.currentText()
        meet_filter = self.combo_meet.currentText()
        event_filter = self.combo_event.currentText()
        course_filter = self.combo_course.currentText()
        year_filter = self.combo_birth_year.currentText()

        filename_parts = ["Resultados"]
        if athlete_filter != ALL_FILTER: filename_parts.append(athlete_filter.split(' ')[0]) # Primeiro nome
        if meet_filter != ALL_FILTER:
            meet_name_part = meet_filter.split('(')[0].strip() # Pega só o nome do meet
            # Limita o tamanho do nome do meet no filename
            max_meet_len = 20
            if len(meet_name_part) > max_meet_len: meet_name_part = meet_name_part[:max_meet_len] + "..."
            filename_parts.append(meet_name_part)
        if event_filter != ALL_FILTER: filename_parts.append(event_filter.replace(" ", "")) # Remove espaços do evento
        if year_filter != ALL_FILTER: filename_parts.append(year_filter)

        raw_filename = "_".join(filename_parts)
        # Sanitiza o nome do arquivo (remove caracteres inválidos)
        sanitized_filename = re.sub(r'[\\/*?:"<>|]', "", raw_filename)
        default_filename = f"{sanitized_filename}.pdf"
        # --- Fim da Geração do Nome ---

        fileName, _ = QFileDialog.getSaveFileName(self, "Salvar PDF com Resultados Filtrados", default_filename, "PDF (*.pdf)")
        if not fileName:
            return

        try:
            # --- Ordenar os dados ANTES de gerar o PDF ---
            pdf_data = list(self.current_table_data) # Cria uma cópia para ordenar
            if key_func:
                reverse_sort = (sort_order == Qt.DescendingOrder)
                try:
                    pdf_data.sort(key=key_func, reverse=reverse_sort)
                    print(f"PDF Export: Ordenando por '{sort_dict_key}', reverso={reverse_sort}")
                except Exception as e:
                    # Informa sobre erro na ordenação, mas continua com dados não ordenados
                    print(f"PDF Export: Erro durante a ordenação por chave '{sort_dict_key}': {e}. Exportando sem ordenação específica.")
            # --- Fim da Ordenação ---

            # Usa landscape(A4) para orientação horizontal
            page_width, page_height = landscape(A4)
            left_margin = 1.0*cm; right_margin = 1.0*cm; top_margin = 1.5*cm; bottom_margin = 1.5*cm
            doc = SimpleDocTemplate(fileName, pagesize=landscape(A4), leftMargin=left_margin, rightMargin=right_margin, topMargin=top_margin, bottomMargin=bottom_margin)
            styles = getSampleStyleSheet()
            story = []

            # Título
            title_style = styles['h1']; title_style.alignment = TA_CENTER
            story.append(Paragraph("Resultados Filtrados", title_style))
            story.append(Spacer(1, 0.5*cm))

            # --- Adicionar Informações de Filtragem ---
            filter_style = styles['Normal']; filter_style.fontSize = 9
            filter_lines = ["<b>Filtros Aplicados:</b>"]
            if athlete_filter != ALL_FILTER: filter_lines.append(f" - Atleta: {athlete_filter}")
            if meet_filter != ALL_FILTER: filter_lines.append(f" - Competição: {meet_filter}")
            if event_filter != ALL_FILTER: filter_lines.append(f" - Tipo de Prova: {event_filter}")
            if course_filter != ALL_FILTER: filter_lines.append(f" - Piscina: {course_filter}")
            if year_filter != ALL_FILTER: filter_lines.append(f" - Ano Nasc.: {year_filter}")

            if len(filter_lines) > 1: # Se algum filtro foi aplicado
                for line in filter_lines: story.append(Paragraph(line, filter_style))
            # --- Fim das Informações de Filtragem ---
            story.append(Spacer(1, 0.5*cm))

            # Tabela de Dados
            table_content = []
            # Usa pdf_headers e header_to_key_map_pdf definidos anteriormente

            header_style = styles['Normal']; 
            header_style.fontSize = 7; 
            header_style.alignment = TA_CENTER
            table_content.append([Paragraph(f"<b>{h}</b>", header_style) for h in pdf_headers])
            
            body_style = styles['Normal']; 
            body_style.fontSize = 6 # Diminuído de 7 para 6
            sparkline_pdf_width = 1.8*cm; sparkline_pdf_height = 0.4*cm # Tamanho da imagem no PDF

            for row_dict in pdf_data: # <<< USA A LISTA ORDENADA (ou a cópia original se ordenação falhou)
                row_list = []
                athlete_place_str = row_dict.get("Colocação", "")
                for h in pdf_headers:
                    dict_key = header_to_key_map_pdf[h]; value = row_dict.get(dict_key, "") # <<< CORREÇÃO AQUI
                    if h == "Ritmo":
                        lap_times = value # Lista de tempos
                        image_buffer = self._generate_sparkline_pdf_image(lap_times, width_px=int(sparkline_pdf_width / cm * 72), height_px=int(sparkline_pdf_height / cm * 72))
                        if image_buffer:
                            img = Image(image_buffer, width=sparkline_pdf_width, height=sparkline_pdf_height)
                            row_list.append(img)
                        else:
                            row_list.append(Paragraph("N/A", body_style))
                    else:
                        cell_text = str(value)
                        is_bold = False
                        if (h == "vs T1" and athlete_place_str == "1") or \
                           (h == "vs T2" and athlete_place_str == "2") or \
                           (h == "vs T3" and athlete_place_str == "3"):
                            is_bold = True
                        # Alinhamento padrão central, exceto para Atleta e Prova
                        align_style = Paragraph(f"<b>{cell_text}</b>" if is_bold else cell_text, body_style)
                        if h in ["Atleta", "Prova", "Cidade"]: align_style.style.alignment = TA_LEFT
                        else: align_style.style.alignment = TA_CENTER
                        row_list.append(align_style)
                table_content.append(row_list)

            if len(table_content) > 1: # Se tiver mais que o cabeçalho
                # A largura disponível agora é a altura da página A4 menos as margens
                available_width = page_width - left_margin - right_margin
                # Definir larguras (ajustadas para aproveitar mais espaço horizontal)
                col_widths = [ #"Atleta", "Nasc", "Prova", "Col", "Tempo", "Média Lap", "DP Lap", "Ritmo", "vs T3", "vs T2", "vs T1", "Cidade", "Data"
                    3.5*cm, # Atleta (mais espaço)
                    1*cm,   # Nasc
                    3.0*cm, # Prova (mais espaço)
                    1.0*cm, # Col
                    1.8*cm, # Tempo
                    1.2*cm, # Média lap
                    1*cm,   # DP lap
                    sparkline_pdf_width + 0.1*cm, # Ritmo
                    1.5*cm, # vs T3 (um pouco mais)
                    1.5*cm, # vs T2 (um pouco mais)
                    1.2*cm, # vs T1
                    2.0*cm, # Cidade
                    1.8*cm  # Data
                    ]
                if sum(col_widths) > available_width: scale = available_width / sum(col_widths); col_widths = [w * scale for w in col_widths]
                table = Table(table_content, colWidths=col_widths, repeatRows=1)
                style = TableStyle([('BACKGROUND', (0, 0), (-1, 0), colors.grey), ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke), ('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), ('BOTTOMPADDING', (0, 0), (-1, 0), 5), ('TOPPADDING', (0, 0), (-1, 0), 5), ('GRID', (0, 0), (-1, -1), 0.5, colors.black), ('TOPPADDING', (0, 1), (-1, -1), 1), ('BOTTOMPADDING', (0, 1), (-1, -1), 1)])
                for i in range(1, len(table_content)):
                    if i % 2 == 0: style.add('BACKGROUND', (0, i), (-1, i), colors.whitesmoke) # Linhas alternadas mais claras
                table.setStyle(style); story.append(table)

            # Construir PDF
            # Adiciona chamada para desenhar o rodapé
            doc.build(story, onFirstPage=self._draw_footer, onLaterPages=self._draw_footer)
            QMessageBox.information(self, "Exportação Concluída", f"Resultados filtrados salvos com sucesso em:\n{fileName}")

        except Exception as e:
            QMessageBox.critical(self, "Erro ao Exportar PDF", f"Ocorreu um erro ao gerar o arquivo PDF:\n{e}")
            import traceback; print(traceback.format_exc())

    # --- NOVO MÉTODO: Copiado de meet_summary_tab.py ---
    def _draw_footer(self, canvas, doc):
        canvas.saveState(); canvas.setFont('Helvetica', 7); canvas.setFillColor(colors.grey)
        footer_text = "Luiz Arthur Feitosa dos Santos - luizsantos@utfpr.edu.br"
        page_width = doc.pagesize[0]; bottom_margin = doc.bottomMargin
        canvas.drawCentredString(page_width / 2.0, bottom_margin * 0.75, footer_text); canvas.restoreState()

    @Slot()
    def refresh_data(self):
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
        self.table_widget.setRowCount(0); self.table_widget.setColumnCount(0);
        self.current_table_data = [] # Limpa os dados guardados
        self.btn_export_pdf.setEnabled(False) # Desabilita exportação ao limpar

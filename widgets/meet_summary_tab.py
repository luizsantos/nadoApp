# NadosApp/widgets/meet_summary_tab.py
import sys
import os
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, # Adicionado QLabel
                               QComboBox, QTableWidget, QTableWidgetItem,
                               QAbstractItemView, QMessageBox, QSpacerItem,
                               QSizePolicy, QTextEdit, QPushButton, QDialog, # Adicionado QDialog
                               QFileDialog, QScrollArea) # Adicionado QScrollArea
from PySide6.QtCore import Slot, Qt
from PySide6.QtGui import QFont, QPixmap # Adicionado QPixmap
import sqlite3
from collections import defaultdict, Counter
import re
import statistics
import math
import io # Adicionado para buffer de imagem
from datetime import datetime # Garante que o import está aqui
import numpy as np # Adicionado para gráfico de radar

# Tentar importar matplotlib
try:
    import matplotlib
    matplotlib.use('Agg') # Usar backend não interativo
    import matplotlib.pyplot as plt
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False
    print("AVISO: Matplotlib não encontrado. Sparklines não estarão disponíveis.")
    plt = None

# --- Matplotlib Imports para Gráfico Principal (similar a AnalysisTab) ---
try:
    # Usa Agg para sparklines, mas precisamos de QtAgg para o canvas principal
    matplotlib.use('QtAgg') # Tenta usar backend QtAgg
    import matplotlib.pyplot as plt # Reimporta com novo backend
    from matplotlib.figure import Figure
    from matplotlib.ticker import MaxNLocator # Para ajustar ticks de idade
    from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg as FigureCanvas
    from matplotlib.backends.backend_qtagg import NavigationToolbar2QT as NavigationToolbar
    MATPLOTLIB_QT_AVAILABLE = True
except ImportError:
    MATPLOTLIB_QT_AVAILABLE = False
    print("AVISO: Backend QtAgg do Matplotlib não encontrado. Gráfico principal não funcionará.")


# Imports do ReportLab
try:
    from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image, PageBreak # Adicionado Image e PageBreak
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.enums import TA_LEFT, TA_CENTER, TA_RIGHT
    from reportlab.lib.units import inch, cm
    from reportlab.lib.pagesizes import A4
    from reportlab.lib import colors
    REPORTLAB_AVAILABLE = True
except ImportError:
    REPORTLAB_AVAILABLE = False
    # Definir classes dummy
    class SimpleDocTemplate: pass; 
    class Paragraph: pass; 
    class Spacer: pass; 
    class Table: pass
    class TableStyle: pass; 
    class Image: pass; 
    def getSampleStyleSheet(): return {}
    TA_LEFT = 0; TA_CENTER = 1; TA_RIGHT = 2; inch = 72; cm = inch / 2.54; A4 = (0,0); colors = None

# Adiciona o diretório pai
script_dir = os.path.dirname(os.path.abspath(__file__)); parent_dir = os.path.dirname(script_dir)
if parent_dir not in sys.path: sys.path.append(parent_dir)

# Importa funções do core.database
from core.database import (get_db_connection, fetch_all_meets_for_edit,
                           fetch_results_for_meet_summary, fetch_top3_for_meet,
                           fetch_splits_for_meet)

# Constante SELECT_PROMPT
SELECT_PROMPT = "--- Selecione uma Competição ---"

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

# --- NOVA CLASSE PARA POP-UP DO GRÁFICO ---
class GraphPopupDialog(QDialog):
    """Um diálogo simples para exibir um gráfico Matplotlib com toolbar."""
    def __init__(self, figure, window_title="Gráfico", parent=None):
        super().__init__(parent)
        self.setWindowTitle(window_title)
        # self.setMinimumSize(1200, 900) # Remove o tamanho mínimo fixo

        layout = QVBoxLayout(self)

        # Cria o canvas e a toolbar DENTRO do diálogo
        self.canvas = FigureCanvas(figure)
        self.toolbar = NavigationToolbar(self.canvas, self)

        layout.addWidget(self.toolbar)
        layout.addWidget(self.canvas)

        self.setLayout(layout)
        self.setAttribute(Qt.WA_DeleteOnClose) # Garante que a janela seja destruída ao fechar



class MeetSummaryTab(QWidget):
    # __init__, _populate_meet_combo, _on_meet_selected (sem alterações)
    def __init__(self, db_path, parent=None):
        super().__init__(parent)
        self.db_path = db_path; self.current_meet_id = None; self.last_summary_data = None; self.last_meet_name = ""
        self.main_layout = QVBoxLayout(self); top_bar_layout = QHBoxLayout(); select_layout = QHBoxLayout()
        select_layout.addWidget(QLabel("Selecionar Competição:")); self.combo_select_meet = QComboBox()
        self.combo_select_meet.addItem(SELECT_PROMPT, userData=None); self.combo_select_meet.currentIndexChanged.connect(self._on_meet_selected)
        select_layout.addWidget(self.combo_select_meet, 1); self.btn_export_pdf = QPushButton("Exportar para PDF")
        self.btn_export_pdf.clicked.connect(self._export_to_pdf); self.btn_export_pdf.setEnabled(False)
        if not REPORTLAB_AVAILABLE or not MATPLOTLIB_AVAILABLE: # Desabilita exportação se faltar algo
             self.btn_export_pdf.setEnabled(False)
             tooltip = []
             if not REPORTLAB_AVAILABLE: tooltip.append("'reportlab' não encontrada.")
             if not MATPLOTLIB_AVAILABLE: tooltip.append("'matplotlib' não encontrado.")
             self.btn_export_pdf.setToolTip("\n".join(tooltip))

        top_bar_layout.addLayout(select_layout, 4); top_bar_layout.addWidget(self.btn_export_pdf, 1); self.main_layout.addLayout(top_bar_layout)
        
        summary_grid = QGridLayout(); summary_grid.setContentsMargins(10, 10, 10, 10); summary_grid.setSpacing(15)
        summary_grid.addWidget(QLabel("<b>Medalhas Totais (Clube):</b>"), 0, 0, Qt.AlignmentFlag.AlignTop)
        self.lbl_medals_gold = QLabel("Ouro: 0"); self.lbl_medals_silver = QLabel("Prata: 0"); self.lbl_medals_bronze = QLabel("Bronze: 0")
        medals_layout = QVBoxLayout(); medals_layout.addWidget(self.lbl_medals_gold); medals_layout.addWidget(self.lbl_medals_silver); medals_layout.addWidget(self.lbl_medals_bronze); medals_layout.addStretch()
        summary_grid.addLayout(medals_layout, 0, 1, Qt.AlignmentFlag.AlignTop)
        summary_grid.addWidget(QLabel("<b>Atletas por Prova:</b>"), 1, 0, Qt.AlignmentFlag.AlignTop)
        self.txt_athletes_per_event = QTextEdit(); self.txt_athletes_per_event.setReadOnly(True); self.txt_athletes_per_event.setMaximumHeight(120)
        summary_grid.addWidget(self.txt_athletes_per_event, 1, 1, Qt.AlignmentFlag.AlignTop)
        summary_grid.addWidget(QLabel("<b>Medalhas por Prova:</b>"), 0, 2, Qt.AlignmentFlag.AlignTop)
        self.txt_medals_per_event = QTextEdit(); self.txt_medals_per_event.setReadOnly(True); self.txt_medals_per_event.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        summary_grid.addWidget(self.txt_medals_per_event, 0, 3, 2, 1, Qt.AlignmentFlag.AlignTop)
        summary_grid.setColumnStretch(1, 1); summary_grid.setColumnStretch(3, 2); 
        # self.main_layout.addLayout(summary_grid) # Movido para dentro do scroll
        
        self.table_athletes = QTableWidget(); self.table_athletes.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers); self.table_athletes.setAlternatingRowColors(True)
        self.table_athletes.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows); self.table_athletes.setSortingEnabled(True)
        # self.main_layout.addWidget(QLabel("<b>Detalhes dos Atletas na Competição:</b>")); self.main_layout.addWidget(self.table_athletes, 1) # Movido para dentro do scroll
        
        # --- Container Widget para o conteúdo rolável ---
        scroll_content_widget = QWidget()
        scroll_content_layout = QVBoxLayout(scroll_content_widget)
        scroll_content_layout.addLayout(summary_grid) # Adiciona grid do resumo
        scroll_content_layout.addWidget(QLabel("<b>Detalhes dos Atletas na Competição:</b>"))
        # Define uma altura mínima para a tabela para ajudar a forçar o scroll
        self.table_athletes.setMinimumHeight(300) 
        # Adiciona tabela SEM stretch factor para que ela não encolha demais
        scroll_content_layout.addWidget(self.table_athletes, 1) # Adiciona tabela (stretch factor 1)
        
        self.setLayout(self.main_layout); self._populate_meet_combo()

        # --- Seção do Gráfico Comparativo por Prova ---
        graph_section_layout = QVBoxLayout()
        graph_controls_layout = QHBoxLayout()
        graph_controls_layout.addWidget(QLabel("Visualizar Gráfico da Prova:"))
        self.combo_event_graph = QComboBox()
        self.combo_event_graph.addItem("--- Selecione Prova ---", userData=None)
        self.combo_event_graph.setEnabled(False)
        self.combo_event_graph.currentIndexChanged.connect(self._on_event_graph_selected)
        graph_controls_layout.addWidget(self.combo_event_graph, 1)
        self.btn_generate_event_graph = QPushButton("Gerar Gráfico")
        self.btn_generate_event_graph.setEnabled(False)
        self.btn_generate_event_graph.clicked.connect(self._generate_event_graph)
        graph_controls_layout.addWidget(self.btn_generate_event_graph)
        graph_section_layout.addLayout(graph_controls_layout)

        # Área do Gráfico
        # self.event_graph_widget = QWidget()
        # self.event_graph_layout = QVBoxLayout(self.event_graph_widget)
        # self.event_graph_layout.setContentsMargins(0,0,0,0)
        # self.event_graph_canvas = None
        self.event_graph_toolbar = None
        self.event_graph_figure = None
        self.event_graph_ax = None

        if MATPLOTLIB_QT_AVAILABLE:
            self.event_graph_figure = Figure(figsize=(8, 6), dpi=100) # Aumenta o tamanho padrão da figura
            self.event_graph_ax = self.event_graph_figure.add_subplot(111) # Cria os eixos
            # self.event_graph_canvas = FigureCanvas(self.event_graph_figure)
            # self.event_graph_toolbar = NavigationToolbar(self.event_graph_canvas, self)
            # self.event_graph_layout.addWidget(self.event_graph_toolbar)
            # self.event_graph_layout.addWidget(self.event_graph_canvas)
            self._clear_event_graph(show_placeholder=True) # Placeholder inicial
        # else:
        #     error_label = QLabel("Gráfico indisponível (Matplotlib Qt backend não encontrado).")
        #     error_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        #     self.event_graph_layout.addWidget(error_label)

        # Define uma altura mínima para o widget do gráfico
        # self.event_graph_widget.setMinimumHeight(600) # Aumentado de 400 para 600
        # graph_section_layout.addWidget(self.event_graph_widget)
        # self.main_layout.addLayout(graph_section_layout) # Movido para dentro do scroll
        scroll_content_layout.addLayout(graph_section_layout) # Adiciona seção do gráfico

        # --- Seção do Gráfico de Dispersão (Idade vs Tempo) ---
        scatter_section_layout = QVBoxLayout()
        scatter_controls_layout = QHBoxLayout()
        scatter_controls_layout.addWidget(QLabel("Visualizar Dispersão Idade x Tempo:"))
        self.combo_scatter_event = QComboBox()
        self.combo_scatter_event.addItem("--- Selecione Prova ---", userData=None)
        self.combo_scatter_event.setEnabled(False)
        self.combo_scatter_event.currentIndexChanged.connect(self._on_scatter_event_selected)
        scatter_controls_layout.addWidget(self.combo_scatter_event, 1)
        self.btn_generate_scatter = QPushButton("Gerar Gráfico Dispersão")
        self.btn_generate_scatter.setEnabled(False)
        self.btn_generate_scatter.clicked.connect(self._generate_scatter_plot)
        scatter_controls_layout.addWidget(self.btn_generate_scatter)
        scatter_section_layout.addLayout(scatter_controls_layout)

        # Área do Gráfico de Dispersão
        # self.scatter_plot_widget = QWidget()
        # self.scatter_plot_layout = QVBoxLayout(self.scatter_plot_widget)
        # self.scatter_plot_layout.setContentsMargins(0,0,0,0)
        # self.scatter_plot_canvas = None
        self.scatter_plot_toolbar = None
        self.scatter_plot_figure = None
        self.scatter_plot_ax = None

        if MATPLOTLIB_QT_AVAILABLE:
            self.scatter_plot_figure = Figure(figsize=(8, 6), dpi=100) # Aumenta o tamanho padrão da figura
            self.scatter_plot_ax = self.scatter_plot_figure.add_subplot(111) # Cria os eixos
            # self.scatter_plot_canvas = FigureCanvas(self.scatter_plot_figure)
            # self.scatter_plot_toolbar = NavigationToolbar(self.scatter_plot_canvas, self)
            # self.scatter_plot_layout.addWidget(self.scatter_plot_toolbar)
            # self.scatter_plot_layout.addWidget(self.scatter_plot_canvas)
            self._clear_scatter_plot(show_placeholder=True) # Placeholder inicial
        # (Não precisa de else aqui, pois já foi tratado no gráfico anterior)
        # Define uma altura mínima maior para o widget do gráfico de dispersão
        #self.scatter_plot_widget.setMinimumHeight(600) # Definindo altura mínima (ajuste conforme necessário)
        #scatter_section_layout.addWidget(self.scatter_plot_widget)
        scroll_content_layout.addLayout(scatter_section_layout) # Adiciona seção do scatter
    

        # --- Configuração da QScrollArea ---
        scroll_area = QScrollArea()
        scroll_area.setWidgetResizable(True) # Permite que o widget interno redimensione
        scroll_area.setWidget(scroll_content_widget) # Define o widget com todo o conteúdo

        self.main_layout.addWidget(scroll_area, 1) # Adiciona a área de scroll ao layout principal (stretch factor 1)


    def _populate_meet_combo(self):
        conn = None
        try:
            conn = get_db_connection(self.db_path); meets = fetch_all_meets_for_edit(conn)
            self.combo_select_meet.blockSignals(True); previous_id = self.combo_select_meet.currentData()
            self.combo_select_meet.clear(); self.combo_select_meet.addItem(SELECT_PROMPT, userData=None)
            for meet_id, name, city, date in meets: display_text = f"{name or 'Sem Nome'} ({city or 'Sem Cidade'}) - {date or 'Sem Data'}"; self.combo_select_meet.addItem(display_text, userData=meet_id)
            idx_to_restore = self.combo_select_meet.findData(previous_id) if previous_id is not None else -1
            self.combo_select_meet.setCurrentIndex(idx_to_restore if idx_to_restore != -1 else 0); self.combo_select_meet.blockSignals(False)
            if self.combo_select_meet.currentIndex() > 0: self._on_meet_selected(self.combo_select_meet.currentIndex())
        except Exception as e: QMessageBox.warning(self, "Erro", f"Erro ao carregar competições:\n{e}")
        finally:
            if conn: conn.close()

    @Slot(int)
    def _on_meet_selected(self, index):
        self.current_meet_id = self.combo_select_meet.itemData(index); self.last_meet_name = self.combo_select_meet.itemText(index)
        if self.current_meet_id is None: self._clear_summary(); self.btn_export_pdf.setEnabled(False); return
        print(f"MeetSummaryTab: Selecionado Meet ID: {self.current_meet_id}")
        summary_generated = self._generate_and_display_summary()
        if summary_generated:
            self._populate_event_graph_combo() # Popula combo de eventos para gráfico
            self._populate_scatter_event_combo() # Popula combo de eventos para scatter
        
        
        # Habilita exportação apenas se ambas as bibliotecas estiverem disponíveis
        self.btn_export_pdf.setEnabled(REPORTLAB_AVAILABLE and MATPLOTLIB_AVAILABLE)


    def _generate_and_display_summary(self):
        """Busca dados, processa (incluindo média/DP por VOLTA, status na colocação) e exibe o resumo."""
        if self.current_meet_id is None: return
        self.last_summary_data = None; conn = None
        try:
            conn = get_db_connection(self.db_path)
            if not conn: QMessageBox.critical(self, "Erro DB", f"Não foi possível conectar: {self.db_path}"); return

            # 1. Buscar dados
            headers, results_data = fetch_results_for_meet_summary(conn, self.current_meet_id)
            top3_raw_data = fetch_top3_for_meet(conn, self.current_meet_id)
            splits_raw_data = fetch_splits_for_meet(conn, self.current_meet_id)

            if not headers: self._clear_summary(); return

            # Encontrar índices
            try:
                result_id_idx = headers.index('result_id_lenex'); athlete_idx = headers.index('Atleta'); birth_idx = headers.index('AnoNasc'); event_idx = headers.index('Prova'); place_idx = headers.index('Colocacao'); time_idx = headers.index('Tempo'); status_idx = headers.index('Status'); event_db_id_idx = headers.index('event_db_id'); agegroup_db_id_idx = headers.index('agegroup_db_id')
            except ValueError as e: QMessageBox.critical(self, "Erro Interno", f"Coluna não encontrada: {e}"); self._clear_summary(); return

            # 2. Processar Dados
            gold_count = 0; silver_count = 0; bronze_count = 0
            athletes_per_event = Counter(); medals_per_event = defaultdict(lambda: defaultdict(int))
            athlete_table_data = []; top3_lookup = defaultdict(dict)

            # Construir lookup do Top3
            for t3_event, t3_ag, t3_place, t3_time in top3_raw_data: top3_lookup[(t3_event, t3_ag)][t3_place] = t3_time

            # Processar Parciais (tempos acumulados em segundos)
            splits_lookup = defaultdict(list)
            for split_res_id, _, split_time_str in splits_raw_data:
                split_sec = time_to_seconds(split_time_str)
                if split_sec is not None: splits_lookup[split_res_id].append(split_sec)

            # Iterar sobre os resultados do clube
            for row_idx, row in enumerate(results_data):
                result_id = row[result_id_idx]; place = row[place_idx]; status = row[status_idx]; event_desc = row[event_idx]; event_db_id = row[event_db_id_idx]; ag_db_id = row[agegroup_db_id_idx]; athlete_time_str = row[time_idx]; athlete_name = row[athlete_idx]

                # Determinar valor da Colocação/Status
                display_colocacao = "N/A"; is_valid_result = status is None or status.upper() == 'OK' or status.upper() == 'OFFICIAL'
                if not is_valid_result and status: display_colocacao = status.upper()
                elif place is not None: display_colocacao = str(place)

                # Contagens
                if is_valid_result:
                    if place == 1: gold_count += 1
                    elif place == 2: silver_count += 1
                    elif place == 3: bronze_count += 1
                if event_desc: athletes_per_event[event_desc] += 1
                if is_valid_result and event_desc and place in [1, 2, 3]: medals_per_event[event_desc][place] += 1

                # Lookup Top3 e cálculo de diferenças
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

                # Adiciona os dados ao dicionário (com Lap Times)
                athlete_table_data.append({
                    "Atleta": athlete_name, "AnoNasc": row[birth_idx], "Prova": event_desc,
                    "Colocação": display_colocacao,
                    "Tempo": athlete_time_str or "N/A",
                    "Média Lap": media_lap_str,
                    "DP Lap": dp_lap_str,
                    "Lap Times": lap_times_sec, # <<< Armazena a lista de tempos
                    "vs Top3": diff3_str, "vs Top2": diff2_str, "vs Top1": diff1_str
                })

            # 3. Atualizar a UI
            self.lbl_medals_gold.setText(f"Ouro: {gold_count}"); self.lbl_medals_silver.setText(f"Prata: {silver_count}"); self.lbl_medals_bronze.setText(f"Bronze: {bronze_count}")
            athletes_event_str = "\n".join([f"{count} - {event}" for event, count in athletes_per_event.most_common()]); self.txt_athletes_per_event.setPlainText(athletes_event_str or "Nenhum atleta encontrado.")
            medals_event_str = "";
            for event, medals in sorted(medals_per_event.items()): g = medals.get(1, 0); s = medals.get(2, 0); b = medals.get(3, 0);
            if g > 0 or s > 0 or b > 0: medals_event_str += f"{event}: {g} Ouro, {s} Prata, {b} Bronze\n"
            self.txt_medals_per_event.setPlainText(medals_event_str or "Nenhuma medalha encontrada.")
            
            # --- VERIFIQUE/RESTAURE ESTA SEÇÃO ---
            medals_event_str = "";
            for event, medals in sorted(medals_per_event.items()):
                g = medals.get(1, 0); s = medals.get(2, 0); b = medals.get(3, 0);
                if g > 0 or s > 0 or b > 0:
                     medals_event_str += f"{event}: {g} Ouro, {s} Prata, {b} Bronze\n"
            # Certifique-se que a linha abaixo existe e está correta:
            self.txt_medals_per_event.setPlainText(medals_event_str or "Nenhuma medalha encontrada.")
            # --- FIM DA VERIFICAÇÃO ---
            
            self._update_athlete_table(athlete_table_data) # Chama o método atualizado

            # Guarda os dados processados para exportação
            self.last_summary_data = {"gold": gold_count, "silver": silver_count, "bronze": bronze_count, "athletes_per_event_str": athletes_event_str or "Nenhum atleta encontrado.", "medals_per_event_str": medals_event_str or "Nenhuma medalha encontrada.", "athlete_details": athlete_table_data}
            return True # Indica sucesso

        except sqlite3.Error as e: QMessageBox.critical(self, "Erro DB", f"Erro ao gerar resumo:\n{e}"); self._clear_summary()
        except Exception as e: QMessageBox.critical(self, "Erro", f"Erro inesperado ao gerar resumo:\n{e}"); import traceback; print(traceback.format_exc()); self._clear_summary()
        finally:
            if conn: conn.close()
        
        return False # Indica falha

    # --- NOVA FUNÇÃO: Gerar Sparkline (copiada de view_data_tab) ---
    def _generate_sparkline_pixmap(self, lap_times, width_px=80, height_px=20):
        """Gera um QPixmap de um sparkline para os tempos de volta."""
        if not MATPLOTLIB_AVAILABLE or not lap_times:
            return None
        try:
            fig, ax = plt.subplots(figsize=(width_px / 72, height_px / 72), dpi=72)
            fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
            ax.plot(range(len(lap_times)), lap_times, color='blue', linewidth=1.0)
            if len(lap_times) > 0:
                mean_time = statistics.mean(lap_times)
                ax.axhline(mean_time, color='red', linestyle='--', linewidth=0.5)
            ax.axis('off')
            buf = io.BytesIO()
            fig.savefig(buf, format='png', transparent=True)
            buf.seek(0)
            pixmap = QPixmap()
            pixmap.loadFromData(buf.read())
            plt.close(fig)
            return pixmap
        except Exception as e:
            print(f"Erro ao gerar sparkline: {e}")
            try:
                if 'fig' in locals() and fig: plt.close(fig)
            except: pass
            return None
    # --- FIM DA NOVA FUNÇÃO ---

    def _update_athlete_table(self, table_data):
        """Popula a tabela de detalhes dos atletas, incluindo sparkline."""
        self.table_athletes.setRowCount(0);
        if not table_data: return
        # Cabeçalhos com "Ritmo"
        headers = ["Atleta", "AnoNasc", "Prova", "Colocação", "Tempo",
                   "Média Lap", "DP Lap", "Ritmo", "Parciais", # <<< Novos Cabeçalhos
                   "vs Top3", "vs Top2", "vs Top1"]
        self.table_athletes.setColumnCount(len(headers)); self.table_athletes.setHorizontalHeaderLabels(headers)
        self.table_athletes.setRowCount(len(table_data)); bold_font = QFont(); bold_font.setBold(True)

        # Mapeamento de cabeçalho para chave do dicionário
        # Mapeia "Ritmo" e "Parciais" para a mesma fonte de dados "Lap Times"
        header_to_key_map = {h: h for h in headers}
        header_to_key_map["Ritmo"] = "Lap Times"
        header_to_key_map["Parciais"] = "Lap Times" # <<< ADICIONAR ESTA LINHA

        for row_idx, row_dict in enumerate(table_data):
            col_idx = 0; athlete_place_str = row_dict.get("Colocação", "")
            for key in headers:
                dict_key = header_to_key_map[key]
                value = row_dict.get(dict_key, "")

                # --- Lógica para Sparkline ---
                if key == "Ritmo":
                    self.table_athletes.setCellWidget(row_idx, col_idx, None) # Limpa célula
                    lap_times = value # Lista de tempos
                    pixmap = self._generate_sparkline_pixmap(lap_times)
                    if pixmap:
                        label = QLabel()
                        label.setPixmap(pixmap)
                        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                        self.table_athletes.setCellWidget(row_idx, col_idx, label)
                    else:
                        item = QTableWidgetItem("N/A")
                        item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                        self.table_athletes.setItem(row_idx, col_idx, item)
                # --- Lógica para Parciais (Texto) ---
                elif key == "Parciais":
                    self.table_athletes.setCellWidget(row_idx, col_idx, None) # Limpa célula
                    lap_times = value # Lista de tempos
                    if lap_times:
                        # Formata a lista como string: "30.12, 32.50, ..."
                        parciais_str = "; ".join([f"{t:.2f}" for t in lap_times])
                        item = QTableWidgetItem(parciais_str)
                    else:
                        item = QTableWidgetItem("N/A")
                    self.table_athletes.setItem(row_idx, col_idx, item)
                # --- Fim da Lógica Sparkline ---
                else:
                    # Outras colunas
                    self.table_athletes.setCellWidget(row_idx, col_idx, None) # Limpa célula
                    item = QTableWidgetItem(str(value))
                    # Formatação
                    if key == "vs Top1" and athlete_place_str == "1": item.setFont(bold_font)
                    elif key == "vs Top2" and athlete_place_str == "2": item.setFont(bold_font)
                    elif key == "vs Top3" and athlete_place_str == "3": item.setFont(bold_font)
                    if key == "Colocação" and not str(value).isdigit() and str(value) != "N/A": item.setForeground(Qt.GlobalColor.red)
                    self.table_athletes.setItem(row_idx, col_idx, item)

                col_idx += 1

        self.table_athletes.resizeColumnsToContents()
        # Ajustar largura da coluna Sparkline
        try:
            sparkline_col_index = headers.index("Ritmo")
            self.table_athletes.setColumnWidth(sparkline_col_index, 90)
            # Ajustar largura da coluna Parciais também
            parciais_col_index = headers.index("Parciais")
            # Pode precisar de mais largura dependendo do número de parciais
            self.table_athletes.setColumnWidth(parciais_col_index, 120)
        except ValueError: pass

    def _clear_summary(self):
        self.lbl_medals_gold.setText("Ouro: 0"); self.lbl_medals_silver.setText("Prata: 0"); self.lbl_medals_bronze.setText("Bronze: 0")
        self.txt_athletes_per_event.clear(); self.txt_medals_per_event.clear(); self.table_athletes.setRowCount(0); self.table_athletes.setColumnCount(0)
        self.last_summary_data = None; self.last_meet_name = ""
        # Limpa também a seção do gráfico de evento
        self.combo_event_graph.clear(); self.combo_event_graph.addItem("--- Selecione Prova ---"); self.combo_event_graph.setEnabled(False)
        self.btn_generate_event_graph.setEnabled(False)
        self._clear_event_graph(show_placeholder=True)
        # Limpa também o scatter plot
        self._clear_scatter_plot(show_placeholder=True)



    @Slot()
    def refresh_data(self):
        print("MeetSummaryTab: Recebido sinal para refresh_data."); self._populate_meet_combo()

    # --- NOVA FUNÇÃO: Gerar Sparkline para PDF ---
    def _generate_sparkline_pdf_image(self, lap_times, width_px=80, height_px=20):
        """Gera dados de imagem PNG de um sparkline para o PDF."""
        if not MATPLOTLIB_AVAILABLE or not lap_times:
            return None
        try:
            fig, ax = plt.subplots(figsize=(width_px / 72, height_px / 72), dpi=72)
            fig.subplots_adjust(left=0, right=1, top=1, bottom=0)
            ax.plot(range(len(lap_times)), lap_times, color='blue', linewidth=2)
            if len(lap_times) > 0:
                mean_time = statistics.mean(lap_times)
                ax.axhline(mean_time, color='red', linestyle='--', linewidth=1.5)
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

    # --- NOVAS FUNÇÕES PARA GRÁFICO DE EVENTO ---
    def _populate_event_graph_combo(self):
        """Popula o ComboBox com as provas presentes no resumo atual."""
        self.combo_event_graph.blockSignals(True)
        self.combo_event_graph.clear()
        self.combo_event_graph.addItem("--- Selecione Prova ---", userData=None)
        self.combo_event_graph.setEnabled(False)
        self.btn_generate_event_graph.setEnabled(False)

        if self.last_summary_data and 'athlete_details' in self.last_summary_data:
            events = sorted(list(set(item['Prova'] for item in self.last_summary_data['athlete_details'] if item.get('Prova'))))
            if events:
                for event_name in events:
                    self.combo_event_graph.addItem(event_name)
                self.combo_event_graph.setEnabled(True)

        self.combo_event_graph.blockSignals(False)
        self._clear_event_graph(show_placeholder=True) # Limpa gráfico ao trocar de meet

    @Slot(int)
    def _on_event_graph_selected(self, index):
        """Habilita o botão de gerar gráfico se uma prova válida for selecionada."""
        event_name = self.combo_event_graph.itemData(index) # userData é None para o prompt
        is_valid_selection = (index > 0) # Índice 0 é o prompt
        self.btn_generate_event_graph.setEnabled(is_valid_selection)
    
    def _populate_scatter_event_combo(self):
        """Popula o ComboBox com as provas para o gráfico de dispersão."""
        self.combo_scatter_event.blockSignals(True)
        self.combo_scatter_event.clear()
        self.combo_scatter_event.addItem("--- Selecione Prova ---", userData=None)
        self.combo_scatter_event.setEnabled(False)
        self.btn_generate_scatter.setEnabled(False)

        if self.last_summary_data and 'athlete_details' in self.last_summary_data:
            events = sorted(list(set(item['Prova'] for item in self.last_summary_data['athlete_details'] if item.get('Prova'))))
            if events:
                for event_name in events:
                    self.combo_scatter_event.addItem(event_name)
                self.combo_scatter_event.setEnabled(True)

        self.combo_scatter_event.blockSignals(False)
        self._clear_scatter_plot(show_placeholder=True)


    def _clear_event_graph(self, show_placeholder=False):
        """Limpa a área do gráfico de evento."""
        if not self.event_graph_ax:
             if MATPLOTLIB_QT_AVAILABLE and self.event_graph_figure:
                 self.event_graph_ax = self.event_graph_figure.add_subplot(111)
             else:
                 return # Não pode limpar se não existe

        self.event_graph_ax.clear()
        # if show_placeholder:
        #      self.event_graph_ax.text(0.5, 0.5, 'Selecione uma prova e clique em "Gerar Gráfico"',
        #                               horizontalalignment='center', verticalalignment='center',
        #                               transform=self.event_graph_ax.transAxes, wrap=True)
        # self.event_graph_ax.set_xticks([])
        # self.event_graph_ax.set_yticks([])
        # if self.event_graph_canvas:
        #     try:
        #         self.event_graph_figure.tight_layout()
        #     except Exception: pass
        #     self.event_graph_canvas.draw()

    @Slot()
    def _generate_scatter_plot(self):
        """Gera o gráfico de dispersão Idade vs Tempo."""
        if not MATPLOTLIB_QT_AVAILABLE: return
        if not self.last_summary_data or 'athlete_details' not in self.last_summary_data: return

        selected_event = self.combo_scatter_event.currentText()
        if selected_event == "--- Selecione Prova ---": return

        # Filtra os dados para a prova selecionada
        event_data = [item for item in self.last_summary_data['athlete_details'] if item.get('Prova') == selected_event]
        print(f"Scatter Plot: Found {len(event_data)} results for event '{selected_event}'") # DEBUG

        # Extrai dados para plotagem (Idade vs Tempo)
        plot_data = []
        current_year = datetime.now().year # Aproximação da idade
        for item in event_data:
            try:
                birth_year_str = item.get('AnoNasc')
                time_sec = time_to_seconds(item.get('Tempo'))
                if birth_year_str and time_sec is not None:
                    birth_year = int(birth_year_str)
                    age = current_year - birth_year # Idade aproximada no ano atual
                    plot_data.append({'age': age, 'time': time_sec, 'athlete': item.get('Atleta', '')})
            except (ValueError, TypeError):
                continue # Ignora se ano de nasc. não for numérico

        print(f"Scatter Plot: Extracted {len(plot_data)} valid data points (age, time)") # DEBUG
        self._clear_scatter_plot() # Limpa antes de plotar

        if not plot_data:
            self.scatter_plot_ax.text(0.5, 0.5, f'Nenhum dado válido (idade e tempo)\npara {selected_event}', horizontalalignment='center', verticalalignment='center', transform=self.scatter_plot_ax.transAxes, wrap=True, color='red')
        else:
            ages = [item['age'] for item in plot_data]
            times = [item['time'] for item in plot_data]
            print(f"Scatter Plot: Plotting {len(ages)} points.") # DEBUG

            self.scatter_plot_ax.scatter(ages, times, alpha=0.7)

            # Adiciona nome do atleta ao lado dos pontos (opcional, pode poluir)
            # Descomentado para adicionar o primeiro nome
            for item in plot_data:
                 self.scatter_plot_ax.text(item['age'], item['time'], f" {item['athlete'].split()[0]}", fontsize=7, va='bottom')

            self.scatter_plot_ax.set_title(f'Dispersão Idade vs Tempo - {selected_event}')
            self.scatter_plot_ax.set_xlabel('Idade (aproximada)')
            self.scatter_plot_ax.set_ylabel('Tempo (segundos)')
            self.scatter_plot_ax.grid(True, linestyle=':', alpha=0.7)
            # self.scatter_plot_ax.invert_yaxis() # Opcional: inverter eixo Y

            # Garante que o eixo X (idade) mostre apenas inteiros
            self.scatter_plot_ax.xaxis.set_major_locator(MaxNLocator(integer=True))

        # Redesenha
        try:
            self.scatter_plot_figure.tight_layout()
        except Exception as e:
             print(f"Scatter Plot: Warning during tight_layout: {e}") # DEBUG
        # Cria e mostra o diálogo pop-up
        dialog = GraphPopupDialog(self.scatter_plot_figure, f"Dispersão - {selected_event}", self)
        dialog.show()


    @Slot(int)
    def _on_scatter_event_selected(self, index):
        """Habilita o botão de gerar gráfico de dispersão."""
        is_valid_selection = (index > 0)
        self.btn_generate_scatter.setEnabled(is_valid_selection)

    def _clear_scatter_plot(self, show_placeholder=False):
        """Limpa a área do gráfico de dispersão."""
        if not self.scatter_plot_ax:
             if MATPLOTLIB_QT_AVAILABLE and self.scatter_plot_figure:
                 self.scatter_plot_ax = self.scatter_plot_figure.add_subplot(111)
             else:
                 return

        self.scatter_plot_ax.clear()
        # if show_placeholder:
        #      self.scatter_plot_ax.text(0.5, 0.5, 'Selecione uma prova e clique em\n"Gerar Gráfico Dispersão"',
        #                               horizontalalignment='center', verticalalignment='center',
        #                               transform=self.scatter_plot_ax.transAxes, wrap=True)
        # self.scatter_plot_ax.set_xticks([])
        # self.scatter_plot_ax.set_yticks([])
        # if self.scatter_plot_canvas:
        #     try: self.scatter_plot_figure.tight_layout()
        #     except Exception: pass; self.scatter_plot_canvas.draw()


    @Slot()
    def _generate_event_graph(self):
        """Gera o gráfico comparativo para a prova selecionada."""
        if not MATPLOTLIB_QT_AVAILABLE: return
        if not self.last_summary_data or 'athlete_details' not in self.last_summary_data: return

        selected_event = self.combo_event_graph.currentText()
        if selected_event == "--- Selecione Prova ---": return

        # Filtra os dados para a prova selecionada
        event_data = [item for item in self.last_summary_data['athlete_details'] if item.get('Prova') == selected_event]

        # Extrai dados para plotagem (Colocação vs Tempo)
        plot_data = []
        for item in event_data:
            try:
                place = int(item.get('Colocação')) # Tenta converter colocação para int
                time_sec = time_to_seconds(item.get('Tempo'))
                if time_sec is not None:
                    plot_data.append({'place': place, 'time': time_sec, 'athlete': item.get('Atleta', '')})
            except (ValueError, TypeError):
                continue # Ignora resultados com colocação não numérica (DSQ, DNS, etc.)

        self._clear_event_graph() # Limpa antes de plotar

        if not plot_data:
            self.event_graph_ax.text(0.5, 0.5, f'Nenhum resultado numérico válido para\n{selected_event}', horizontalalignment='center', verticalalignment='center', transform=self.event_graph_ax.transAxes, wrap=True, color='red')
        else:
            # Ordena por tempo (melhor para pior) para o gráfico de barras
            plot_data.sort(key=lambda x: x['time'])
            athletes = [item['athlete'] for item in plot_data]
            times = [item['time'] for item in plot_data]

            # Cria o gráfico de barras
            bars = self.event_graph_ax.bar(athletes, times)

            # Define os nomes dos atletas como rótulos do eixo X
            self.event_graph_ax.set_xticks(range(len(athletes)))
            self.event_graph_ax.set_xticklabels(athletes)
            self.event_graph_ax.set_title(f'Comparativo de Tempos - {selected_event}')
            self.event_graph_ax.set_xlabel('Atleta')
            self.event_graph_ax.set_ylabel('Tempo (segundos)')
            self.event_graph_ax.grid(True, linestyle=':', alpha=0.7)
            # self.event_graph_ax.invert_yaxis() # Não inverte para barras

            # Rotaciona os nomes dos atletas se forem muitos
            if len(athletes) > 5:
                self.event_graph_figure.autofmt_xdate(rotation=45, ha='right')
            # Adiciona os valores acima das barras
            self.event_graph_ax.bar_label(bars, fmt='%.2f', padding=3, fontsize=8)
            # Ajusta limite Y para dar espaço aos rótulos
            self.event_graph_ax.set_ylim(0, max(times) * 1.1 if times else 1)

        # Redesenha
        try:
            self.event_graph_figure.tight_layout() # Ajusta layout da figura
        except Exception: pass
         # Cria e mostra o diálogo pop-up
        dialog = GraphPopupDialog(self.event_graph_figure, f"Gráfico - {selected_event}", self)
        dialog.show()
    # --- FIM DAS NOVAS FUNÇÕES ---


    @Slot()
    def _export_to_pdf(self):
        """Exporta o resumo atual para PDF, incluindo sparkline."""
        if not REPORTLAB_AVAILABLE or not MATPLOTLIB_AVAILABLE:
             tooltip = []
             if not REPORTLAB_AVAILABLE: tooltip.append("'reportlab' não encontrada.")
             if not MATPLOTLIB_AVAILABLE: tooltip.append("'matplotlib' não encontrado.")
             QMessageBox.warning(self, "Funcionalidade Indisponível", "\n".join(tooltip))
             return
        if self.current_meet_id is None or self.last_summary_data is None: QMessageBox.warning(self, "Nenhum Dado", "Selecione e gere o resumo."); return
        default_filename = re.sub(r'[\\/*?:"<>|]', "", self.last_meet_name.split('(')[0].strip()); default_filename = f"Resumo_{default_filename}.pdf"
        fileName, _ = QFileDialog.getSaveFileName(self, "Salvar PDF", default_filename, "PDF (*.pdf)");
        if not fileName: return

        try:
            page_width, page_height = A4; left_margin = 1.0*cm; right_margin = 1.0*cm; top_margin = 1.5*cm; bottom_margin = 1.5*cm
            doc = SimpleDocTemplate(fileName, pagesize=A4, leftMargin=left_margin, rightMargin=right_margin, topMargin=top_margin, bottomMargin=bottom_margin)
            styles = getSampleStyleSheet(); story = []
            title_style = styles['h1']; title_style.alignment = TA_CENTER; heading_style = styles['h2']; normal_style = styles['Normal']

            # 1, 2, 3, 4: Título e Resumos
            story.append(Paragraph(f"Resumo da Competição: {self.last_meet_name}", title_style)); story.append(Spacer(1, 0.5*cm))
            story.append(Paragraph("<b>Medalhas Totais (Clube)</b>", heading_style)); story.append(Paragraph(f"Ouro: {self.last_summary_data['gold']}", normal_style)); story.append(Paragraph(f"Prata: {self.last_summary_data['silver']}", normal_style)); story.append(Paragraph(f"Bronze: {self.last_summary_data['bronze']}", normal_style)); story.append(Spacer(1, 0.5*cm))
            story.append(Paragraph("<b>Atletas por Prova</b>", heading_style)); athletes_text = self.last_summary_data['athletes_per_event_str']; athletes_lines = athletes_text.split('\n')
            for line in athletes_lines:
                if line.strip(): story.append(Paragraph(line, normal_style))
            story.append(Spacer(1, 0.5*cm))
            story.append(Paragraph("<b>Medalhas por Prova</b>", heading_style)); medals_text = self.last_summary_data['medals_per_event_str']; medals_lines = medals_text.split('\n')
            for line in medals_lines:
                if line.strip(): story.append(Paragraph(line, normal_style))
            story.append(Spacer(1, 0.7*cm))

            # 5. Tabela de Detalhes dos Atletas
            story.append(Paragraph("<b>Detalhes dos Atletas na Competição</b>", heading_style)); story.append(Spacer(1, 0.2*cm))

            table_content = []
            # Cabeçalhos PDF com "Ritmo"
            pdf_headers = ["Atleta", "Nasc", "Prova", "Col", "Tempo",
                           "Média Lap", "DP Lap", "Ritmo", # <<< Novo
                           "vs Top3", "vs Top2", "vs Top1"]
            # Mapeamento com "Ritmo" -> "Lap Times"
            header_to_key_map = {
                "Atleta": "Atleta", "Nasc": "AnoNasc", "Prova": "Prova", "Col": "Colocação",
                "Tempo": "Tempo", "Média Lap": "Média Lap", "DP Lap": "DP Lap",
                "Ritmo": "Lap Times", # <<< Novo
                "vs Top3": "vs Top3", "vs Top2": "vs Top2", "vs Top1": "vs Top1"
            }
            header_style = styles['Normal']; header_style.fontSize = 9
            table_content.append([Paragraph(f"<b>{h}</b>", header_style) for h in pdf_headers])

            athlete_details = self.last_summary_data['athlete_details']
            body_style = styles['Normal']; body_style.fontSize = 8
            # Definir tamanho da imagem no PDF
            sparkline_pdf_width = 2.0*cm
            sparkline_pdf_height = 0.5*cm

            for row_idx, row_dict in enumerate(athlete_details):
                row_list = []; pdf_row = row_idx + 1
                for h in pdf_headers:
                    dict_key = header_to_key_map[h]; value = row_dict.get(dict_key, "")

                    # --- Lógica para Sparkline no PDF ---
                    if h == "Ritmo":
                        lap_times = value # Lista de tempos
                        image_buffer = self._generate_sparkline_pdf_image(lap_times, width_px=int(sparkline_pdf_width / cm * 72), height_px=int(sparkline_pdf_height / cm * 72))
                        if image_buffer:
                            # Cria objeto Image do ReportLab
                            img = Image(image_buffer, width=sparkline_pdf_width, height=sparkline_pdf_height)
                            row_list.append(img)
                        else:
                            row_list.append(Paragraph("N/A", body_style)) # Fallback
                    # --- Fim da Lógica Sparkline PDF ---
                    else:
                        # Outras colunas
                        cell_text = str(value)
                        is_bold = False; athlete_place_str = row_dict.get("Colocação", "")
                        if (h == "vs Top1" and athlete_place_str == "1") or \
                           (h == "vs Top2" and athlete_place_str == "2") or \
                           (h == "vs Top3" and athlete_place_str == "3"):
                            is_bold = True
                        cell_paragraph = Paragraph(f"<b>{cell_text}</b>" if is_bold else cell_text, body_style);
                        row_list.append(cell_paragraph)
                table_content.append(row_list)

            if table_content:
                available_width = page_width - left_margin - right_margin
                # Ajustar larguras das colunas
                col_widths = [
                    3.0*cm,  # Atleta
                    1.2*cm,  # Nasc
                    2.0*cm,  # Prova
                    1.2*cm,  # Col
                    2.0*cm,  # Tempo
                    1.5*cm,  # Média Lap
                    1.0*cm,  # DP Lap
                    sparkline_pdf_width + 0.2*cm, # Ritmo (largura da imagem + margem)
                    1.5*cm,  # vs Top3
                    1.5*cm,  # vs Top2
                    1.5*cm   # vs Top1
                ]
                total_width_cm = sum(w/cm for w in col_widths); print(f"Largura total: {total_width_cm:.2f} cm / Disponível: {available_width/cm:.2f} cm")
                if sum(col_widths) > available_width:
                     print("AVISO: Ajustando larguras proporcionalmente."); scale_factor = available_width / sum(col_widths); col_widths = [w * scale_factor for w in col_widths]

                table = Table(table_content, colWidths=col_widths, repeatRows=1)
                # Estilos
                style = TableStyle([
                    ('BACKGROUND', (0, 0), (-1, 0), colors.grey), ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
                    ('ALIGN', (0, 0), (-1, -1), 'CENTER'), ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'), # VALIGN MIDDLE para imagem
                    ('ALIGN', (0, 1), (0, -1), 'LEFT'), ('ALIGN', (2, 1), (2, -1), 'LEFT'),
                    ('BOTTOMPADDING', (0, 0), (-1, 0), 6), ('TOPPADDING', (0, 0), (-1, 0), 6),
                    ('GRID', (0, 0), (-1, -1), 1, colors.black),
                    ('TOPPADDING', (0, 1), (-1, -1), 2), ('BOTTOMPADDING', (0, 1), (-1, -1), 2),
                ])
                # Linhas alternadas
                for i in range(1, len(table_content)):
                    if i % 2 == 0: style.add('BACKGROUND', (0, i), (-1, i), colors.lightgrey)
                table.setStyle(style); story.append(table)

            # --- Adicionar Gráficos por Prova ao PDF ---
            story.append(Spacer(1, 1.0*cm)) # Espaço antes dos gráficos
            unique_events = sorted(list(set(item['Prova'] for item in athlete_details if item.get('Prova'))))

            graph_heading_style = styles['h2'] # Usar H2 para mais destaque na página
            # Define uma largura fixa para as imagens no PDF (ajuste conforme necessário)
            img_width_pdf = 17*cm

            for i, event_name in enumerate(unique_events):
                # Adiciona quebra de página ANTES de cada conjunto de gráficos
                story.append(PageBreak())
                story.append(Paragraph(f"Gráficos - {event_name}", graph_heading_style))
                story.append(Spacer(1, 0.2*cm))

                event_data_for_graph = [item for item in athlete_details if item.get('Prova') == event_name]

                # Gerar e adicionar gráfico de barras
                bar_buffer = self._generate_pdf_bar_chart(event_name, event_data_for_graph)
                if bar_buffer:
                    try:
                        # Usa largura fixa e calcula altura proporcional baseada no figsize
                        img_bar = Image(bar_buffer, width=img_width_pdf, height=img_width_pdf * (4.5/7.0))
                        img_bar.hAlign = 'CENTER'
                        story.append(img_bar)
                        story.append(Spacer(1, 0.5*cm))
                    except Exception as img_err:
                        print(f"Erro ao adicionar imagem do gráfico de barras para '{event_name}': {img_err}")
                        story.append(Paragraph(f"(Erro ao gerar gráfico de barras para {event_name})", normal_style))
                else:
                    story.append(Paragraph(f"(Sem dados suficientes para gráfico de barras - {event_name})", normal_style))

                # Gerar e adicionar gráfico de dispersão
                scatter_buffer = self._generate_pdf_scatter_plot(event_name, event_data_for_graph)
                if scatter_buffer:
                    try:
                        img_scatter = Image(scatter_buffer, width=img_width_pdf, height=img_width_pdf * (4.5/7.0))
                        img_scatter.hAlign = 'CENTER'
                        story.append(img_scatter)
                    except Exception as img_err:
                        print(f"Erro ao adicionar imagem do gráfico de dispersão para '{event_name}': {img_err}")
                        story.append(Paragraph(f"(Erro ao gerar gráfico de dispersão para {event_name})", normal_style))
                else:
                     story.append(Paragraph(f"(Sem dados suficientes para gráfico de dispersão - {event_name})", normal_style))
                story.append(Spacer(1, 1.0*cm)) # Espaço maior entre provas
            # --- Fim da Adição de Gráficos ---

            # Construir PDF com footer
            doc.build(story, onFirstPage=self._draw_footer, onLaterPages=self._draw_footer)
            QMessageBox.information(self, "Exportação Concluída", f"Resumo salvo com sucesso em:\n{fileName}")

        except Exception as e:
            QMessageBox.critical(self, "Erro ao Exportar PDF", f"Ocorreu um erro ao gerar o arquivo PDF:\n{e}")
            import traceback; print(traceback.format_exc())

    def _draw_footer(self, canvas, doc):
        canvas.saveState(); canvas.setFont('Helvetica', 7); canvas.setFillColor(colors.grey)
        footer_text = "Luiz Arthur Feitosa dos Santos - luizsantos@utfpr.edu.br"
        page_width = doc.pagesize[0]; bottom_margin = doc.bottomMargin
        canvas.drawCentredString(page_width / 2.0, bottom_margin * 0.75, footer_text); canvas.restoreState()
    
    # --- NOVAS FUNÇÕES PARA GERAR GRÁFICOS PARA PDF ---
    def _generate_pdf_bar_chart(self, event_name, event_data):
        """Gera uma imagem PNG do gráfico de barras para o PDF."""
        if not MATPLOTLIB_AVAILABLE: return None

        plot_data = []
        for item in event_data:
            try:
                # place = int(item.get('Colocação')) # Não precisamos da colocação aqui
                time_sec = time_to_seconds(item.get('Tempo'))
                if time_sec is not None:
                    plot_data.append({'time': time_sec, 'athlete': item.get('Atleta', '')})
            except (ValueError, TypeError):
                continue

        if not plot_data: return None

        # Cria uma NOVA figura e eixos para este gráfico específico
        fig, ax = plt.subplots(figsize=(7, 4.5), dpi=120) # Tamanho reduzido, DPI aumentado


        plot_data.sort(key=lambda x: x['time'])
        athletes = [item['athlete'] for item in plot_data]
        times = [item['time'] for item in plot_data]

        bars = ax.bar(athletes, times)
        ax.set_xticks(range(len(athletes)))
        ax.set_xticklabels(athletes)
        ax.set_title(f'Comparativo de Tempos - {event_name}', fontsize=10)
        ax.set_xlabel('Atleta', fontsize=8)
        ax.set_ylabel('Tempo (segundos)', fontsize=8)
        ax.grid(True, axis='y', linestyle=':', alpha=0.7)
        if len(athletes) > 5:
            fig.autofmt_xdate(rotation=45, ha='right')
        ax.bar_label(bars, fmt='%.2f', padding=3, fontsize=6)
        ax.set_ylim(0, max(times) * 1.1 if times else 1)
        ax.tick_params(axis='both', which='major', labelsize=7) # Fonte menor nos eixos

        buf = io.BytesIO()
        try:
            fig.tight_layout()
            fig.savefig(buf, format='png', bbox_inches='tight')
            buf.seek(0)
        except Exception as e:
            print(f"Erro ao salvar gráfico de barras PDF: {e}")
            buf = None
        finally:
            plt.close(fig) # Fecha a figura para liberar memória

        return buf

    def _generate_pdf_scatter_plot(self, event_name, event_data):
        """Gera uma imagem PNG do gráfico de dispersão para o PDF."""
        if not MATPLOTLIB_AVAILABLE or not MaxNLocator: return None

        plot_data = []
        current_year = datetime.now().year
        for item in event_data:
            try:
                birth_year_str = item.get('AnoNasc')
                time_sec = time_to_seconds(item.get('Tempo'))
                if birth_year_str and time_sec is not None:
                    birth_year = int(birth_year_str)
                    age = current_year - birth_year
                    plot_data.append({'age': age, 'time': time_sec, 'athlete': item.get('Atleta', '')})
            except (ValueError, TypeError):
                continue

        if not plot_data: return None

        # Cria uma NOVA figura e eixos
        fig, ax = plt.subplots(figsize=(7, 4.5), dpi=120) # Tamanho reduzido, DPI aumentado


        ages = [item['age'] for item in plot_data]
        times = [item['time'] for item in plot_data]

        ax.scatter(ages, times, alpha=0.7, s=20) # Pontos menores para PDF
        ax.set_title(f'Dispersão Idade vs Tempo - {event_name}', fontsize=10)
        ax.set_xlabel('Idade (aproximada)', fontsize=8)
        ax.set_ylabel('Tempo (segundos)', fontsize=8)
        ax.grid(True, linestyle=':', alpha=0.7)
        ax.xaxis.set_major_locator(MaxNLocator(integer=True))
        ax.tick_params(axis='both', which='major', labelsize=7)

        # Adiciona o primeiro nome do atleta ao lado dos pontos
        for item in plot_data:
            # Ajusta tamanho da fonte e posição se necessário
            ax.text(item['age'], item['time'], f" {item['athlete'].split()[0]}", fontsize=5, va='bottom')

        buf = io.BytesIO()
        try:
            fig.tight_layout()
            fig.savefig(buf, format='png', bbox_inches='tight')
            buf.seek(0)
        except Exception as e:
            print(f"Erro ao salvar gráfico de dispersão PDF: {e}")
            buf = None
        finally:
            plt.close(fig) # Fecha a figura

        return buf
    # --- FIM DAS NOVAS FUNÇÕES PDF ---

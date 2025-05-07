# NadosApp/widgets/edit_meet_tab.py
import sys
import os
from PySide6.QtWidgets import (QWidget, QVBoxLayout, QGridLayout, QLabel, QComboBox,
                               QLineEdit, QPushButton, QMessageBox, QSpacerItem,
                               QSizePolicy)
from PySide6.QtCore import Slot, Qt
import sqlite3

# Adiciona o diretório pai ao sys.path para encontrar 'core'
script_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(script_dir)
if parent_dir not in sys.path:
    sys.path.append(parent_dir)

# Importa funções específicas do core.database
from core.database import (get_db_connection, fetch_all_meets_for_edit,
                           fetch_meet_details, update_meet_details)

class EditMeetTab(QWidget):
    def __init__(self, db_path, parent=None):
        super().__init__(parent)
        self.db_path = db_path
        self.current_meet_id = None # Guarda o ID do meet selecionado

        # --- Layout Principal ---
        self.main_layout = QVBoxLayout(self)

        # --- Layout de Seleção e Edição ---
        edit_group = QWidget()
        edit_layout = QGridLayout(edit_group)
        edit_layout.setContentsMargins(10, 10, 10, 10)
        edit_layout.setSpacing(10)

        # Seleção de Competição
        lbl_select_meet = QLabel("Selecionar Competição para Editar:")
        self.combo_select_meet = QComboBox()
        self.combo_select_meet.addItem("--- Selecione uma Competição ---", userData=None)
        self.combo_select_meet.currentIndexChanged.connect(self._display_selected_meet_data)

        # Campos de Edição
        lbl_name = QLabel("Nome:")
        self.edit_name = QLineEdit()
        lbl_city = QLabel("Cidade:")
        self.edit_city = QLineEdit()
        lbl_hostclub = QLabel("Clube Organizador:")
        self.edit_hostclub = QLineEdit()
        lbl_date = QLabel("Data Início (AAAA-MM-DD):")
        self.edit_date = QLineEdit()
        lbl_course = QLabel("Tipo Piscina:")
        self.combo_course = QComboBox()
        self.combo_course.addItems(["SCM", "LCM", "Outro"]) # Adicione outros códigos se necessário

        # Botão Salvar
        self.btn_save = QPushButton("Salvar Alterações")
        self.btn_save.setEnabled(False) # Desabilitado até selecionar um meet
        self.btn_save.clicked.connect(self._save_changes)

        # Adicionar widgets ao layout de edição
        edit_layout.addWidget(lbl_select_meet, 0, 0, 1, 4)
        edit_layout.addWidget(self.combo_select_meet, 1, 0, 1, 4)

        edit_layout.addWidget(lbl_name, 2, 0)
        edit_layout.addWidget(self.edit_name, 2, 1, 1, 3) # Ocupa mais espaço
        edit_layout.addWidget(lbl_city, 3, 0)
        edit_layout.addWidget(self.edit_city, 3, 1)
        edit_layout.addWidget(lbl_hostclub, 3, 2)
        edit_layout.addWidget(self.edit_hostclub, 3, 3)
        edit_layout.addWidget(lbl_date, 4, 0)
        edit_layout.addWidget(self.edit_date, 4, 1)
        edit_layout.addWidget(lbl_course, 4, 2)
        edit_layout.addWidget(self.combo_course, 4, 3) # Linha 4, Coluna 3

        # Legenda para o tipo de piscina
        lbl_course_legend = QLabel("SCM: Piscina Curta (25m)\nLCM: Piscina Longa (50m)")
        lbl_course_legend.setStyleSheet("font-size: 9pt; color: grey;") # Estilo menor e cinza
        edit_layout.addWidget(lbl_course_legend, 5, 2, 1, 2) # Linha 5, Colunas 2 e 3

        # Espaçador e Botão Salvar
        edit_layout.addItem(QSpacerItem(20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Expanding), 6, 0) # Movido para linha 6
        edit_layout.addWidget(self.btn_save, 6, 0, 1, 4)

        # Adicionar grupo ao layout principal
        self.main_layout.addWidget(edit_group)
        self.main_layout.addStretch() # Empurra tudo para cima

        self.setLayout(self.main_layout)

        # --- Inicialização ---
        self._load_meets_list()

    def _load_meets_list(self):
        """Busca meets no DB e popula o ComboBox de seleção."""
        conn = None
        try:
            conn = get_db_connection(self.db_path)
            if not conn: return

            meets = fetch_all_meets_for_edit(conn)

            self.combo_select_meet.blockSignals(True)
            # Guarda o ID atual para tentar restaurar
            previous_id = self.combo_select_meet.currentData()
            self.combo_select_meet.clear()
            self.combo_select_meet.addItem("--- Selecione uma Competição ---", userData=None)

            for meet_id, name, city, date in meets:
                display_text = f"{name or 'Sem Nome'} ({city or 'Sem Cidade'}) - {date or 'Sem Data'}"
                self.combo_select_meet.addItem(display_text, userData=meet_id)

            # Tenta restaurar a seleção anterior
            if previous_id is not None:
                idx_to_restore = self.combo_select_meet.findData(previous_id)
                if idx_to_restore != -1:
                    self.combo_select_meet.setCurrentIndex(idx_to_restore)
                else: # Se o item foi removido ou alterado, volta para o default
                    self.combo_select_meet.setCurrentIndex(0)
                    self._clear_fields() # Limpa campos se o item sumiu
            else:
                 self.combo_select_meet.setCurrentIndex(0) # Garante que o placeholder esteja selecionado se nada estava antes

            self.combo_select_meet.blockSignals(False)

        except Exception as e:
            QMessageBox.warning(self, "Erro ao Carregar Competições", f"Não foi possível buscar a lista de competições:\n{e}")
        finally:
            if conn:
                conn.close()

    @Slot(int)
    def _display_selected_meet_data(self, index):
        """Quando um meet é selecionado, busca e exibe seus detalhes."""
        self.current_meet_id = self.combo_select_meet.itemData(index)

        if self.current_meet_id is None:
            self._clear_fields()
            self.btn_save.setEnabled(False)
            return

        conn = None
        try:
            conn = get_db_connection(self.db_path)
            if not conn: return

            details = fetch_meet_details(conn, self.current_meet_id)

            if details:
                name, city, course, start_date, hostclub = details
                self.edit_name.setText(name or "")
                self.edit_city.setText(city or "")
                self.edit_hostclub.setText(hostclub or "") # Exibe hostclub
                self.edit_date.setText(start_date or "")

                # Seleciona o item correto no combo de curso
                idx = self.combo_course.findText(course or "", Qt.MatchFlag.MatchFixedString)
                if idx >= 0:
                    self.combo_course.setCurrentIndex(idx)
                else: # Se não encontrar (ex: valor antigo não está na lista), seleciona "Outro" ou o primeiro item
                    other_idx = self.combo_course.findText("Outro")
                    self.combo_course.setCurrentIndex(other_idx if other_idx != -1 else 0)

                self.btn_save.setEnabled(True)
            else:
                QMessageBox.warning(self, "Erro", f"Não foi possível encontrar detalhes para a competição selecionada (ID: {self.current_meet_id}).")
                self._clear_fields()
                self.btn_save.setEnabled(False)

        except Exception as e:
            QMessageBox.critical(self, "Erro ao Buscar Detalhes", f"Ocorreu um erro:\n{e}")
            self._clear_fields()
            self.btn_save.setEnabled(False)
        finally:
            if conn:
                conn.close()

    @Slot()
    def _save_changes(self):
        """Salva as alterações feitas nos campos para o meet selecionado."""
        if self.current_meet_id is None:
            QMessageBox.warning(self, "Nenhuma Competição Selecionada", "Selecione uma competição antes de salvar.")
            return

        # Obter valores dos campos
        new_name = self.edit_name.text().strip()
        new_city = self.edit_city.text().strip()
        new_hostclub = self.edit_hostclub.text().strip()
        new_date = self.edit_date.text().strip() # Adicionar validação de formato se desejado
        new_course = self.combo_course.currentText()

        # Validação simples (opcional)
        if not new_name:
            QMessageBox.warning(self, "Campo Obrigatório", "O nome da competição não pode ficar vazio.")
            return
        # Adicionar mais validações se necessário (formato da data, etc.)

        conn = None
        try:
            conn = get_db_connection(self.db_path)
            if not conn: return

            success = update_meet_details(conn, self.current_meet_id, new_name, new_city, new_course, new_date, new_hostclub)

            if success:
                QMessageBox.information(self, "Sucesso", "Alterações salvas com sucesso!")
                # Atualiza a lista para refletir a mudança no nome/cidade/data
                self._load_meets_list()
                # Mantém o item selecionado (o _load_meets_list já tenta fazer isso)
                # Opcional: recarregar os dados nos campos se o nome na lista mudou muito
                # current_index = self.combo_select_meet.currentIndex()
                # self._display_selected_meet_data(current_index)
            else:
                QMessageBox.critical(self, "Erro ao Salvar", "Não foi possível salvar as alterações no banco de dados.")

        except Exception as e:
            QMessageBox.critical(self, "Erro Inesperado", f"Ocorreu um erro ao salvar:\n{e}")
        finally:
            if conn:
                conn.close()

    def _clear_fields(self):
        """Limpa todos os campos de edição."""
        self.edit_name.clear()
        self.edit_city.clear()
        self.edit_hostclub.clear()
        self.edit_date.clear()
        self.combo_course.setCurrentIndex(0) # Volta para o primeiro item (SCM?)
        self.current_meet_id = None

    @Slot()
    def refresh_data(self):
        """Atualiza a lista de meets. Chamado após importação."""
        print("EditMeetTab: Recebido sinal para refresh_data.")
        self._load_meets_list()
        # Se um meet estava selecionado, os dados dele serão recarregados
        # Se o meet selecionado não existe mais (improvável), os campos serão limpos
        current_index = self.combo_select_meet.currentIndex()
        if current_index > 0: # Se não for o placeholder
             self._display_selected_meet_data(current_index)
        else:
             self._clear_fields()
             self.btn_save.setEnabled(False)

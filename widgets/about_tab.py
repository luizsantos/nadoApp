# NadosApp/widgets/about_tab.py
from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QSpacerItem, QSizePolicy
from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap, QFont
import os

class AboutTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        layout.setSpacing(15)
        layout.setContentsMargins(20, 20, 20, 20)

        # Título
        title_label = QLabel("NadosApp - Importador e Analisador de Dados de Natação")
        title_font = QFont()
        title_font.setPointSize(18)
        title_font.setBold(True)
        title_label.setFont(title_font)
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(title_label)

        layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed))

        # Descrição
        description_text = (
            "O NadosApp é uma ferramenta desenvolvida para auxiliar técnicos e analistas de natação "
            "na importação, visualização e análise de dados de competições no formato LENEX. "
            "Ele permite gerar relatórios detalhados por atleta, por estilo de nado e resumos de competições, "
            "facilitando a compreensão do desempenho e a tomada de decisões."
        )
        desc_label = QLabel(description_text)
        desc_label.setWordWrap(True)
        layout.addWidget(desc_label)

        layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed))

        # Licença
        license_label = QLabel("<b>Licença:</b>")
        layout.addWidget(license_label)
        license_text = (
            "Este programa é um software livre e é distribuído sob os termos da "
            "<a href='https://www.gnu.org/licenses/gpl-3.0.html'>Licença Pública Geral GNU versão 3 (GNU GPLv3)</a>."
        )
        license_link_label = QLabel(license_text)
        license_link_label.setOpenExternalLinks(True) # Permite abrir o link no navegador
        license_link_label.setWordWrap(True)
        layout.addWidget(license_link_label)

        layout.addSpacerItem(QSpacerItem(20, 20, QSizePolicy.Policy.Minimum, QSizePolicy.Policy.Fixed))

        # Autor
        author_label = QLabel("<b>Autor:</b>")
        layout.addWidget(author_label)
        author_name_label = QLabel("Luiz Arthur Feitosa dos Santos")
        layout.addWidget(author_name_label)
        contact_label = QLabel("<b>Contato:</b> <a href='mailto:luizsantos@utfpr.edu.br'>luizsantos@utfpr.edu.br</a>")
        contact_label.setOpenExternalLinks(True)
        layout.addWidget(contact_label)

        layout.addStretch() # Empurra tudo para cima
        self.setLayout(layout)
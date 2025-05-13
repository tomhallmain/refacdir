from PySide6.QtGui import QPalette, QColor
from PySide6.QtCore import Qt

class ThemeColors:
    """Theme color definitions"""
    DARK_BG = "#26242f"
    DARK_FG = "#ffffff"
    LIGHT_BG = "#f0f0f0"
    LIGHT_FG = "#000000"
    
    # Additional colors for better UI
    DARK_ACCENT = "#3a3845"
    DARK_HOVER = "#4a4855"
    LIGHT_ACCENT = "#e0e0e0"
    LIGHT_HOVER = "#d0d0d0"
    
    # Status colors
    SUCCESS = "#4caf50"
    WARNING = "#ff9800"
    ERROR = "#f44336"
    INFO = "#2196f3"

class ThemeManager:
    """Manages application theming"""
    
    @staticmethod
    def apply_theme(app, is_dark: bool):
        """Apply the selected theme to the application"""
        bg_color = ThemeColors.DARK_BG if is_dark else ThemeColors.LIGHT_BG
        fg_color = ThemeColors.DARK_FG if is_dark else ThemeColors.LIGHT_FG
        accent_color = ThemeColors.DARK_ACCENT if is_dark else ThemeColors.LIGHT_ACCENT
        hover_color = ThemeColors.DARK_HOVER if is_dark else ThemeColors.LIGHT_HOVER
        
        # Set application palette
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(bg_color))
        palette.setColor(QPalette.WindowText, QColor(fg_color))
        palette.setColor(QPalette.Base, QColor(bg_color))
        palette.setColor(QPalette.AlternateBase, QColor(accent_color))
        palette.setColor(QPalette.Text, QColor(fg_color))
        palette.setColor(QPalette.Button, QColor(accent_color))
        palette.setColor(QPalette.ButtonText, QColor(fg_color))
        palette.setColor(QPalette.Highlight, QColor(hover_color))
        palette.setColor(QPalette.HighlightedText, QColor(fg_color))
        app.setPalette(palette)
        
        # Apply stylesheet
        app.setStyleSheet(f"""
            QMainWindow, QWidget {{
                background-color: {bg_color};
                color: {fg_color};
            }}
            
            QPushButton {{
                padding: 8px 16px;
                border: 1px solid {fg_color};
                border-radius: 4px;
                background-color: {accent_color};
                min-width: 80px;
            }}
            
            QPushButton:hover {{
                background-color: {hover_color};
            }}
            
            QPushButton:pressed {{
                background-color: {fg_color};
                color: {bg_color};
            }}
            
            QCheckBox {{
                spacing: 8px;
            }}
            
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border: 1px solid {fg_color};
                border-radius: 3px;
            }}
            
            QCheckBox::indicator:checked {{
                background-color: {ThemeColors.SUCCESS};
                border-color: {ThemeColors.SUCCESS};
            }}
            
            QCheckBox::indicator:hover {{
                border-color: {hover_color};
            }}
            
            QProgressBar {{
                border: 1px solid {fg_color};
                border-radius: 4px;
                text-align: center;
                background-color: {accent_color};
                min-height: 20px;
            }}
            
            QProgressBar::chunk {{
                background-color: {ThemeColors.SUCCESS};
                border-radius: 3px;
            }}
            
            QScrollArea {{
                border: none;
                background-color: transparent;
            }}
            
            QScrollBar:vertical {{
                border: none;
                background-color: {accent_color};
                width: 12px;
                margin: 0px;
            }}
            
            QScrollBar::handle:vertical {{
                background-color: {hover_color};
                min-height: 20px;
                border-radius: 6px;
            }}
            
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            
            QScrollBar:horizontal {{
                border: none;
                background-color: {accent_color};
                height: 12px;
                margin: 0px;
            }}
            
            QScrollBar::handle:horizontal {{
                background-color: {hover_color};
                min-width: 20px;
                border-radius: 6px;
            }}
            
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
            }}
            
            QFrame[frameShape="4"] {{
                border: 1px solid {fg_color};
                border-radius: 4px;
                padding: 8px;
            }}
            
            QLabel {{
                padding: 2px;
            }}
            
            QTextEdit {{
                border: 1px solid {fg_color};
                border-radius: 4px;
                padding: 4px;
                background-color: {accent_color};
            }}
        """) 
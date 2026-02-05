"""
Theme management and styling for the RefacDir application.

This module provides centralized theme management including:
- Color definitions for light and dark themes
- Application-wide stylesheet generation
- Custom title bar and frameless window styling
- Integration with refacdir config for custom colors
"""

from PySide6.QtGui import QPalette, QColor
from PySide6.QtCore import Qt


def _adjust_color_brightness(hex_color: str, factor: float) -> str:
    """
    Adjust the brightness of a hex color.
    
    Args:
        hex_color: Color in #RRGGBB format
        factor: < 1.0 darkens, > 1.0 lightens
        
    Returns:
        Adjusted color in #RRGGBB format
    """
    hex_color = hex_color.lstrip('#')
    r = int(hex_color[0:2], 16)
    g = int(hex_color[2:4], 16)
    b = int(hex_color[4:6], 16)
    
    if factor < 1.0:
        # Darken
        r = int(r * factor)
        g = int(g * factor)
        b = int(b * factor)
    else:
        # Lighten
        r = int(r + (255 - r) * (factor - 1.0))
        g = int(g + (255 - g) * (factor - 1.0))
        b = int(b + (255 - b) * (factor - 1.0))
    
    r = max(0, min(255, r))
    g = max(0, min(255, g))
    b = max(0, min(255, b))
    
    return f"#{r:02x}{g:02x}{b:02x}"


class ThemeColors:
    """Theme color definitions (defaults, can be overridden by config)"""
    DARK_BG = "#26242f"
    DARK_FG = "#ffffff"
    DARK_SIDEBAR = "#1e1c26"  # Slightly darker than main background
    LIGHT_BG = "#f0f0f0"
    LIGHT_FG = "#000000"
    LIGHT_SIDEBAR = "#e8e8e8"  # Slightly darker than main background
    
    # Additional colors for better UI
    DARK_ACCENT = "#3a3845"
    DARK_HOVER = "#4a4855"
    LIGHT_ACCENT = "#e0e0e0"
    LIGHT_HOVER = "#d0d0d0"
    
    # Border colors
    DARK_BORDER = "#3a3845"
    LIGHT_BORDER = "#c0c0c0"
    
    # Status colors
    SUCCESS = "#4caf50"
    WARNING = "#ff9800"
    ERROR = "#f44336"
    INFO = "#2196f3"
    
    # Title bar specific
    CLOSE_HOVER = "#e81123"
    CLOSE_PRESSED = "#f1707a"


class ThemeManager:
    """
    Centralized theme manager for the application.
    
    Handles all styling including:
    - Application palette and stylesheet
    - Custom title bar styling
    - Frameless window styling with rounded corners
    """
    
    # Configuration
    _corner_radius = 10
    _is_dark = True
    _title_bar_height = 32
    _resize_grip_size = 8
    
    @classmethod
    def set_corner_radius(cls, radius: int):
        """Set the corner radius for rounded window corners."""
        cls._corner_radius = radius
    
    @classmethod
    def get_corner_radius(cls) -> int:
        """Get the current corner radius."""
        return cls._corner_radius
    
    @classmethod
    def is_dark_theme(cls) -> bool:
        """Check if dark theme is active."""
        return cls._is_dark
    
    @classmethod
    def get_colors(cls, is_dark: bool = None) -> dict:
        """
        Get color dictionary for the specified theme.
        
        Respects custom foreground_color and background_color from refacdir config
        if they are set, deriving other colors (sidebar, accent, hover, border)
        from the custom background color.
        """
        if is_dark is None:
            is_dark = cls._is_dark
        
        # Check for custom colors from config
        custom_bg = None
        custom_fg = None
        try:
            from refacdir.config import config
            if config.background_color:
                custom_bg = config.background_color
            if config.foreground_color:
                custom_fg = config.foreground_color
        except Exception:
            pass  # Config not available, use defaults
        
        if is_dark:
            bg = custom_bg if custom_bg else ThemeColors.DARK_BG
            fg = custom_fg if custom_fg else ThemeColors.DARK_FG
            
            # Derive other colors from background if custom
            if custom_bg:
                sidebar = _adjust_color_brightness(bg, 0.8)  # Darker
                accent = _adjust_color_brightness(bg, 1.3)   # Lighter
                hover = _adjust_color_brightness(bg, 1.5)    # Even lighter
                border = _adjust_color_brightness(bg, 1.3)   # Same as accent
            else:
                sidebar = ThemeColors.DARK_SIDEBAR
                accent = ThemeColors.DARK_ACCENT
                hover = ThemeColors.DARK_HOVER
                border = ThemeColors.DARK_BORDER
            
            return {
                'bg': bg,
                'fg': fg,
                'sidebar': sidebar,
                'accent': accent,
                'hover': hover,
                'border': border,
            }
        else:
            bg = custom_bg if custom_bg else ThemeColors.LIGHT_BG
            fg = custom_fg if custom_fg else ThemeColors.LIGHT_FG
            
            # Derive other colors from background if custom
            if custom_bg:
                sidebar = _adjust_color_brightness(bg, 0.95)  # Slightly darker
                accent = _adjust_color_brightness(bg, 0.9)    # Darker
                hover = _adjust_color_brightness(bg, 0.85)    # Even darker
                border = _adjust_color_brightness(bg, 0.75)   # Border darker
            else:
                sidebar = ThemeColors.LIGHT_SIDEBAR
                accent = ThemeColors.LIGHT_ACCENT
                hover = ThemeColors.LIGHT_HOVER
                border = ThemeColors.LIGHT_BORDER
            
            return {
                'bg': bg,
                'fg': fg,
                'sidebar': sidebar,
                'accent': accent,
                'hover': hover,
                'border': border,
            }
    
    @classmethod
    def apply_theme(cls, app, is_dark: bool, corner_radius: int = None):
        """
        Apply the complete theme to the application.
        
        Args:
            app: QApplication instance
            is_dark: Whether to use dark theme
            corner_radius: Optional corner radius override
        """
        cls._is_dark = is_dark
        if corner_radius is not None:
            cls._corner_radius = corner_radius
            
        colors = cls.get_colors(is_dark)
        radius = cls._corner_radius
        
        # Set application palette
        cls._apply_palette(app, colors)
        
        # Apply comprehensive stylesheet
        app.setStyleSheet(cls._generate_stylesheet(colors, radius))
    
    @classmethod
    def _apply_palette(cls, app, colors: dict):
        """Apply the color palette to the application."""
        palette = QPalette()
        palette.setColor(QPalette.Window, QColor(colors['bg']))
        palette.setColor(QPalette.WindowText, QColor(colors['fg']))
        palette.setColor(QPalette.Base, QColor(colors['bg']))
        palette.setColor(QPalette.AlternateBase, QColor(colors['accent']))
        palette.setColor(QPalette.Text, QColor(colors['fg']))
        palette.setColor(QPalette.Button, QColor(colors['accent']))
        palette.setColor(QPalette.ButtonText, QColor(colors['fg']))
        palette.setColor(QPalette.Highlight, QColor(colors['hover']))
        palette.setColor(QPalette.HighlightedText, QColor(colors['fg']))
        app.setPalette(palette)
    
    @classmethod
    def _generate_stylesheet(cls, colors: dict, radius: int) -> str:
        """Generate the complete application stylesheet."""
        return f"""
            /* Base styling */
            QMainWindow {{
                background-color: transparent;
            }}
            
            QWidget {{
                background-color: {colors['bg']};
                color: {colors['fg']};
            }}
            
            /* Transparent outer container for rounded corners */
            QWidget#transparentOuter {{
                background-color: transparent;
            }}
            
            /* Main frame with rounded corners - the visible window background */
            QFrame#mainFrame {{
                background-color: {colors['bg']};
                border: 1px solid {colors['border']};
                border-radius: {radius}px;
            }}
            
            /* Sidebar with rounded bottom-left corner */
            QWidget#sidebar {{
                background-color: {colors['sidebar']};
                border-bottom-left-radius: {radius}px;
            }}
            
            /* Main content with rounded bottom-right corner */
            QWidget#mainContent {{
                background-color: {colors['bg']};
                border-bottom-right-radius: {radius}px;
            }}
            
            /* Button styling */
            QPushButton {{
                padding: 8px 16px;
                border: 1px solid {colors['fg']};
                border-radius: 4px;
                background-color: {colors['accent']};
                min-width: 80px;
            }}
            
            QPushButton:hover {{
                background-color: {colors['hover']};
            }}
            
            QPushButton:pressed {{
                background-color: {colors['fg']};
                color: {colors['bg']};
            }}
            
            /* Checkbox styling */
            QCheckBox {{
                spacing: 8px;
            }}
            
            QCheckBox::indicator {{
                width: 18px;
                height: 18px;
                border: 1px solid {colors['fg']};
                border-radius: 3px;
            }}
            
            QCheckBox::indicator:checked {{
                background-color: {ThemeColors.SUCCESS};
                border-color: {ThemeColors.SUCCESS};
            }}
            
            QCheckBox::indicator:hover {{
                border-color: {colors['hover']};
            }}
            
            /* Progress bar styling */
            QProgressBar {{
                border: 1px solid {colors['fg']};
                border-radius: 4px;
                text-align: center;
                background-color: {colors['accent']};
                min-height: 20px;
            }}
            
            QProgressBar::chunk {{
                background-color: {ThemeColors.SUCCESS};
                border-radius: 3px;
            }}
            
            /* Scroll area styling */
            QScrollArea {{
                border: none;
                background-color: transparent;
            }}
            
            QScrollBar:vertical {{
                border: none;
                background-color: {colors['accent']};
                width: 12px;
                margin: 0px;
            }}
            
            QScrollBar::handle:vertical {{
                background-color: {colors['hover']};
                min-height: 20px;
                border-radius: 6px;
            }}
            
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0px;
            }}
            
            QScrollBar:horizontal {{
                border: none;
                background-color: {colors['accent']};
                height: 12px;
                margin: 0px;
            }}
            
            QScrollBar::handle:horizontal {{
                background-color: {colors['hover']};
                min-width: 20px;
                border-radius: 6px;
            }}
            
            QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
                width: 0px;
            }}
            
            /* Frame styling */
            QFrame[frameShape="4"] {{
                border: 1px solid {colors['fg']};
                border-radius: 4px;
                padding: 8px;
            }}
            
            /* Label styling */
            QLabel {{
                padding: 2px;
                background-color: transparent;
            }}
            
            /* Text edit styling */
            QTextEdit {{
                border: 1px solid {colors['fg']};
                border-radius: 4px;
                padding: 4px;
                background-color: {colors['accent']};
            }}
            
            /* Line edit styling */
            QLineEdit {{
                border: 1px solid {colors['border']};
                border-radius: 4px;
                padding: 6px;
                background-color: {colors['accent']};
            }}
            
            QLineEdit:focus {{
                border-color: {ThemeColors.INFO};
            }}
        """
    
    @classmethod
    def get_title_bar_style(cls, is_dark: bool = None) -> str:
        """Get the stylesheet for the custom title bar."""
        if is_dark is None:
            is_dark = cls._is_dark
        
        colors = cls.get_colors(is_dark)
        radius = cls._corner_radius
        
        return f"""
            CustomTitleBar {{
                background-color: {colors['bg']};
                border-bottom: 1px solid {colors['border']};
                border-top-left-radius: {radius}px;
                border-top-right-radius: {radius}px;
            }}
        """
    
    @classmethod
    def get_title_bar_button_style(cls, button_type: str, is_dark: bool = None) -> str:
        """
        Get the stylesheet for a title bar button.
        
        Args:
            button_type: One of 'minimize', 'maximize', 'close'
            is_dark: Whether dark theme is active
        """
        if is_dark is None:
            is_dark = cls._is_dark
            
        colors = cls.get_colors(is_dark)
        
        # Common button properties
        base_style = f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                color: {colors['fg']};
                padding: 0px;
                margin: 0px;
            }}
        """
        
        if button_type == "close":
            return base_style + f"""
                QPushButton {{
                    font-size: 12px;
                    font-family: "Segoe MDL2 Assets", "Segoe UI Symbol", sans-serif;
                }}
                QPushButton:hover {{
                    background-color: {ThemeColors.CLOSE_HOVER};
                    color: white;
                }}
                QPushButton:pressed {{
                    background-color: {ThemeColors.CLOSE_PRESSED};
                    color: white;
                }}
            """
        else:
            return base_style + f"""
                QPushButton {{
                    font-size: 11px;
                    font-family: "Segoe MDL2 Assets", "Segoe UI Symbol", sans-serif;
                }}
                QPushButton:hover {{
                    background-color: {colors['hover']};
                }}
                QPushButton:pressed {{
                    background-color: {colors['hover']};
                }}
            """
    
    @classmethod
    def apply_to_title_bar(cls, title_bar, is_dark: bool = None):
        """
        Apply theme styling to a CustomTitleBar widget.
        
        Args:
            title_bar: CustomTitleBar instance
            is_dark: Whether dark theme is active
        """
        if is_dark is None:
            is_dark = cls._is_dark
            
        colors = cls.get_colors(is_dark)
        
        # Apply title bar container style
        title_bar.setStyleSheet(cls.get_title_bar_style(is_dark))
        
        # Apply title label style
        title_bar.title_label.setStyleSheet(
            f"color: {colors['fg']}; font-size: 12px; background: transparent;"
        )
        
        # Apply button styles
        title_bar.minimize_btn.setStyleSheet(cls.get_title_bar_button_style('minimize', is_dark))
        title_bar.maximize_btn.setStyleSheet(cls.get_title_bar_button_style('maximize', is_dark))
        title_bar.close_btn.setStyleSheet(cls.get_title_bar_button_style('close', is_dark))

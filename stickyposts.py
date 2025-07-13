import sys
import os
import json
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from PyQt6.QtWidgets import (
    QApplication, QWidget, QTextEdit, QPushButton, QHBoxLayout, QVBoxLayout, QSystemTrayIcon, QMenu, QCheckBox, QLabel, QDialog, QLineEdit, QMessageBox, QInputDialog, QComboBox, QTabWidget
)
from PyQt6.QtGui import QIcon, QCursor, QMouseEvent, QKeySequence, QAction
from PyQt6.QtCore import Qt, QRect, QPoint, QSize
import win32com.client  # For startup shortcut
import win32cred  # For Windows Credential Manager
from pynput import keyboard  # For global hotkey
import threading

# Constants
NOTE_BG_COLOR = '#FFFFE0'
NOTE_TEXT_COLOR = '#000000'  # Default text color
NOTE_TEXT_SIZE = 14  # Default text size
NOTE_FONT_FAMILY = 'Arial'  # Default font family
NOTE_MIN_SIZE = QSize(200, 150)
SETTINGS_FILE = 'stickyposts_settings.json'
NOTES_FILE = 'stickyposts.json'
APP_NAME = 'StickyPosts'
CREDENTIAL_TARGET = 'StickyPosts_Encryption'

# Performance optimization constants
AUTO_SAVE_DELAY = 3000  # 3 seconds instead of 2
MAX_NOTES_TO_SAVE = 50  # Limit number of notes to prevent excessive storage
MAX_NOTE_TEXT_LENGTH = 10000  # Limit individual note text length
CLEANUP_INTERVAL = 300000  # 5 minutes - cleanup interval

# Encryption utilities
def derive_key_from_password(password, salt=None):
    """Derive encryption key from password using PBKDF2"""
    if salt is None:
        salt = os.urandom(16)
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=100000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode()))
    return key, salt

def encrypt_data(data, password):
    """Encrypt data with password"""
    key, salt = derive_key_from_password(password)
    fernet = Fernet(key)
    encrypted_data = fernet.encrypt(json.dumps(data).encode())
    return {
        'salt': base64.b64encode(salt).decode(),
        'data': base64.b64encode(encrypted_data).decode()
    }

def decrypt_data(encrypted_data, password):
    """Decrypt data with password"""
    try:
        salt = base64.b64decode(encrypted_data['salt'])
        data = base64.b64decode(encrypted_data['data'])
        key, _ = derive_key_from_password(password, salt)
        fernet = Fernet(key)
        decrypted_data = fernet.decrypt(data)
        return json.loads(decrypted_data.decode())
    except Exception:
        return None

# Constants
TRAY_ICON_THEMES = [
    'default',      # Yellow
    'dark',         # Dark mode
    'oled',         # OLED safe
    'monochrome',   # Monochrome
]

# Utility for settings persistence
def load_settings():
    if os.path.exists(SETTINGS_FILE):
        with open(SETTINGS_FILE, 'r') as f:
            settings = json.load(f)
            # Ensure all required keys exist
            default_settings = {
                'launch_on_startup': False,
                'always_on_top': False,
                'hotkey': 'ctrl+shift+s',
                'reopen_notes': False,
                'encrypt_notes': False,
                'prompt_password_on_startup': False,
                'tray_icon_theme': 'default',
                'note_color': NOTE_BG_COLOR,  # Add note color to defaults
                'note_text_color': NOTE_TEXT_COLOR,  # Add note text color to defaults
                'note_text_size': NOTE_TEXT_SIZE,  # Add note text size to defaults
                'note_font_family': NOTE_FONT_FAMILY,  # Add note font family to defaults
                'hide_terminal': True,  # Default to hide terminal window
            }
            # Update with any missing keys
            for key, default_value in default_settings.items():
                if key not in settings:
                    settings[key] = default_value
            return settings
    return {
        'launch_on_startup': False,
        'always_on_top': False,
        'hotkey': 'ctrl+shift+s',
        'reopen_notes': False,
        'encrypt_notes': False,
        'prompt_password_on_startup': False,
        'tray_icon_theme': 'default',
        'note_color': NOTE_BG_COLOR,  # Add note color to defaults
        'note_text_color': NOTE_TEXT_COLOR,  # Add note text color to defaults
        'note_text_size': NOTE_TEXT_SIZE,  # Add note text size to defaults
        'note_font_family': NOTE_FONT_FAMILY,  # Add note font family to defaults
        'hide_terminal': True,  # Default to hide terminal window
    }

def verify_encryption_password():
    """Prompt user for encryption password and verify it"""
    password, ok = QInputDialog.getText(
        None, 
        'Encryption Password Required', 
        'Enter encryption password to access notes:',
        QLineEdit.EchoMode.Password
    )
    
    if not ok:
        return False  # User cancelled
    
    if not password:
        return False  # Empty password
    
    # Try to decrypt a test with the provided password
    try:
        if os.path.exists(NOTES_FILE):
            with open(NOTES_FILE, 'r') as f:
                data = json.load(f)
            
            # Check if data is encrypted
            if isinstance(data, dict) and 'salt' in data and 'data' in data:
                decrypted_data = decrypt_data(data, password)
                return decrypted_data is not None
    except Exception:
        pass
    
    return False

def save_settings(settings):
    with open(SETTINGS_FILE, 'w') as f:
        json.dump(settings, f, separators=(',', ':'))  # Optimized - no pretty formatting

# Utility for notes persistence
def save_notes(notes, settings):
    notes_data = []
    valid_notes = 0
    
    for note in notes:
        if hasattr(note, 'is_deleted') and note.is_deleted:
            continue  # Skip deleted notes
        
        # Limit number of notes to save
        if valid_notes >= MAX_NOTES_TO_SAVE:
            break
            
        # Get note text and limit length
        note_text = note.text_edit.toPlainText()
        if len(note_text) > MAX_NOTE_TEXT_LENGTH:
            note_text = note_text[:MAX_NOTE_TEXT_LENGTH] + "..."
        
        note_data = {
            'geometry': {
                'x': note.geometry().x(),
                'y': note.geometry().y(),
                'width': note.geometry().width(),
                'height': note.geometry().height()
            },
            'text': note_text,
            'pinned': getattr(note, 'pinned', False)  # Save pin state
        }
        notes_data.append(note_data)
        valid_notes += 1
    
    # Check if encryption is enabled
    if settings.get('encrypt_notes', False):
        password = get_password_from_credential_manager()
        if password:
            encrypted_data = encrypt_data(notes_data, password)
            with open(NOTES_FILE, 'w') as f:
                json.dump(encrypted_data, f)
        else:
            # Fallback to unencrypted if no password
            with open(NOTES_FILE, 'w') as f:
                json.dump(notes_data, f)
    else:
        # Save unencrypted (optimized - no pretty formatting to save space)
        with open(NOTES_FILE, 'w') as f:
            json.dump(notes_data, f, separators=(',', ':'))

def load_notes(settings):
    if not os.path.exists(NOTES_FILE):
        return []
    
    try:
        with open(NOTES_FILE, 'r') as f:
            data = json.load(f)
        
        # Check if data is encrypted
        if isinstance(data, dict) and 'salt' in data and 'data' in data:
            # Data is encrypted
            if settings.get('encrypt_notes', False):
                password = get_password_from_credential_manager()
                if password:
                    decrypted_data = decrypt_data(data, password)
                    if decrypted_data is not None:
                        return decrypted_data
                    else:
                        # Wrong password
                        QMessageBox.warning(None, "Encryption Error", 
                                          "Incorrect password. Notes could not be decrypted.")
                        return []
                else:
                    # No password set
                    QMessageBox.warning(None, "Encryption Error", 
                                      "Encryption is enabled but no password is set in Windows Credential Manager.")
                    return []
            else:
                # Encryption disabled but data is encrypted
                QMessageBox.warning(None, "Encryption Error", 
                                  "Notes are encrypted but encryption is disabled in settings.")
                return []
        else:
            # Data is not encrypted
            return data
    except Exception as e:
        QMessageBox.warning(None, "Load Error", f"Could not load notes: {str(e)}")
        return []

# Startup shortcut management (Windows)
def set_startup(enabled):
    startup_path = os.path.join(os.environ['APPDATA'], r'Microsoft\Windows\Start Menu\Programs\Startup')
    shortcut_path = os.path.join(startup_path, f'{APP_NAME}.lnk')
    script = os.path.abspath(__file__)
    
    # Try to find the virtual environment Python interpreter
    venv_python = None
    script_dir = os.path.dirname(script)
    
    # Look for venv in the same directory as the script
    venv_path = os.path.join(script_dir, 'venv', 'Scripts', 'python.exe')
    if os.path.exists(venv_path):
        venv_python = venv_path
    else:
        # Look for venv in parent directory
        parent_venv_path = os.path.join(os.path.dirname(script_dir), 'venv', 'Scripts', 'python.exe')
        if os.path.exists(parent_venv_path):
            venv_python = parent_venv_path
    
    # Use venv Python if found, otherwise fall back to system Python
    target = venv_python if venv_python else sys.executable
    
    if enabled:
        shell = win32com.client.Dispatch('WScript.Shell')
        shortcut = shell.CreateShortCut(shortcut_path)
        shortcut.Targetpath = target
        shortcut.Arguments = f'"{script}"'
        shortcut.WorkingDirectory = os.path.dirname(script)
        shortcut.IconLocation = script
        shortcut.save()
    else:
        if os.path.exists(shortcut_path):
            os.remove(shortcut_path)

# Secure password management using Windows Credential Manager
def save_password_to_credential_manager(password):
    """Save password securely to Windows Credential Manager"""
    try:
        # Create credential structure with proper encoding
        cred = {
            'TargetName': CREDENTIAL_TARGET,
            'UserName': 'stickyposts_user',
            'CredentialBlob': password,  # Remove encoding, let win32cred handle it
            'Type': win32cred.CRED_TYPE_GENERIC,
            'Persist': win32cred.CRED_PERSIST_SESSION
        }
        win32cred.CredWrite(cred)
        return True
    except Exception as e:
        print(f"Credential save error: {e}")
        return False

def get_password_from_credential_manager():
    """Retrieve password from Windows Credential Manager"""
    try:
        cred = win32cred.CredRead(CREDENTIAL_TARGET, win32cred.CRED_TYPE_GENERIC)
        # Handle both string and bytes return types
        password_blob = cred['CredentialBlob']
        if isinstance(password_blob, bytes):
            return password_blob.decode('utf-16-le')
        else:
            return password_blob
    except Exception as e:
        # Only print error if it's not 'Element not found' (1168)
        if getattr(e, 'winerror', None) != 1168:
            print(f"Credential read error: {e}")
        return None

def delete_password_from_credential_manager():
    """Delete password from Windows Credential Manager"""
    try:
        win32cred.CredDelete(CREDENTIAL_TARGET, win32cred.CRED_TYPE_GENERIC)
        return True
    except Exception as e:
        print(f"Credential delete error: {e}")
        return False

def cleanup_old_settings():
    """Remove old encryption_password field from settings file"""
    if os.path.exists(SETTINGS_FILE):
        try:
            with open(SETTINGS_FILE, 'r') as f:
                settings = json.load(f)
            
            # Remove old encryption_password field if it exists
            if 'encryption_password' in settings:
                del settings['encryption_password']
                with open(SETTINGS_FILE, 'w') as f:
                    json.dump(settings, f, indent=2)
                print("Cleaned up old encryption_password field from settings")
            
            # Also ensure we have all required fields
            required_fields = {
                'launch_on_startup': False,
                'always_on_top': False,
                'hotkey': 'ctrl+shift+s',
                'reopen_notes': False,
                'encrypt_notes': False,
            }
            
            updated = False
            for field, default_value in required_fields.items():
                if field not in settings:
                    settings[field] = default_value
                    updated = True
            
            if updated:
                with open(SETTINGS_FILE, 'w') as f:
                    json.dump(settings, f, indent=2)
                print("Updated settings with missing fields")
                
        except Exception as e:
            print(f"Error cleaning up settings: {e}")

# Add a helper to generate tray icons
from PyQt6.QtGui import QPixmap, QPainter, QColor, QIcon

def get_tray_icon(theme, show_text=True):
    pixmap = QPixmap(16, 16)
    painter = QPainter(pixmap)
    if theme == 'dark':
        pixmap.fill(QColor(40, 40, 40))
        painter.setPen(QColor(220, 220, 220))
        if show_text:
            painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "S")
    elif theme == 'oled':
        pixmap.fill(QColor(0, 0, 0))
        if show_text:
            painter.setPen(QColor(180, 180, 180))
            painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "S")
    elif theme == 'monochrome':
        pixmap.fill(QColor(255, 255, 255))
        painter.setPen(QColor(0, 0, 0))
        if show_text:
            painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "S")
    else:  # default
        pixmap.fill(QColor(255, 255, 224))
        painter.setPen(QColor(0, 0, 0))
        if show_text:
            painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "S")
    painter.end()
    icon = QIcon()
    icon.addPixmap(pixmap)
    return icon

# Main Sticky Note Window
class StickyNote(QWidget):
    EDGE_MARGIN = 8  # px for resize area

    def __init__(self, app, settings, text="", geometry=None, pinned=False):
        super().__init__(flags=Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint if settings['always_on_top'] else Qt.WindowType.FramelessWindowHint)
        self.app = app
        self.settings = settings
        self.resizing = False
        self.dragging = False
        self.resize_dir = None
        self.drag_pos = None
        self.is_deleted = False  # Track if note was deleted
        self.pinned = pinned  # Track if note is individually pinned
        self.setMinimumSize(NOTE_MIN_SIZE)
        self.setStyleSheet(f"background: {self.settings.get('note_color', NOTE_BG_COLOR)}; border: 1px solid #e0e0a0;")
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon())  # Set empty icon to prevent taskbar icon
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, False)
        self.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, False)
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, settings['always_on_top'] or self.pinned)
        # Hide from taskbar
        self.setWindowFlag(Qt.WindowType.Tool, True)
        
        # Set geometry if provided (for reopening notes)
        if geometry:
            self.setGeometry(geometry['x'], geometry['y'], geometry['width'], geometry['height'])
        
        # Text area
        self.text_edit = QTextEdit(self)
        self._apply_text_style()
        self.text_edit.setText(text)

        # Set maximum text length to prevent excessive memory usage
        doc = self.text_edit.document()
        if doc is not None:
            try:
                doc.setMaximumBlockCount(MAX_NOTE_TEXT_LENGTH // 100)  # Approximate blocks
            except Exception as e:
                print(f"Warning: Could not set maximum block count: {e}")

        # Connect text change signal for auto-save
        self.text_edit.textChanged.connect(self._on_text_changed)
        # Auto-save timer
        from PyQt6.QtCore import QTimer
        self.auto_save_timer = QTimer()
        self.auto_save_timer.setSingleShot(True)
        self.auto_save_timer.timeout.connect(self._auto_save)
        
        # Top-right buttons
        self.pin_btn = QPushButton('📌', self)
        self.pin_btn.setFixedSize(24, 24)
        self.pin_btn.setToolTip('Pin note on top')
        self._update_pin_button_style()
        self.pin_btn.clicked.connect(self._toggle_pin)
        
        self.close_btn = QPushButton('✕', self)
        self.close_btn.setFixedSize(24, 24)
        self.close_btn.clicked.connect(self.close_note)
        self.add_btn = QPushButton('+', self)
        self.add_btn.setFixedSize(24, 24)
        self.add_btn.clicked.connect(lambda: self.app.create_note("", pinned=False))
        self._update_button_colors(self.settings.get('note_color', NOTE_BG_COLOR))
        
        # Layout
        btn_layout = QHBoxLayout()
        btn_layout.addWidget(self.pin_btn)
        btn_layout.addStretch()
        btn_layout.addWidget(self.add_btn)
        btn_layout.addWidget(self.close_btn)
        btn_layout.setSpacing(2)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        main_layout = QVBoxLayout(self)
        main_layout.addLayout(btn_layout)
        main_layout.addWidget(self.text_edit)
        main_layout.setContentsMargins(4, 4, 4, 4)
        self.setLayout(main_layout)
        # Remove window shadow
        self.setWindowFlag(Qt.WindowType.NoDropShadowWindowHint, True)
        
        # Install event filter to catch mouse events on child widgets
        self.text_edit.installEventFilter(self)
        self.close_btn.installEventFilter(self)
        self.add_btn.installEventFilter(self)
        self.pin_btn.installEventFilter(self)
        
        self.show()

    def _on_text_changed(self):
        """Trigger auto-save when text changes"""
        # Reset timer - will save after AUTO_SAVE_DELAY milliseconds of no typing
        self.auto_save_timer.start(AUTO_SAVE_DELAY)

    def _auto_save(self):
        """Auto-save the current note"""
        if self.app.settings.get('reopen_notes', False):
            self.app._save_notes()

    def _toggle_pin(self):
        """Toggle the pin state of this note"""
        self.pinned = not self.pinned
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.settings['always_on_top'] or self.pinned)
        self.show()  # Need to show after changing window flags
        self._update_pin_button_style()
        
        # Save notes to persist pin state
        if self.app.settings.get('reopen_notes', False):
            self.app._save_notes()

    def _update_pin_button_style(self):
        """Update the pin button appearance based on pin state"""
        if self.pinned:
            self.pin_btn.setStyleSheet("QPushButton { background: #ffcc00; border: none; font-weight: bold; color: black; } QPushButton:hover { background: #ffdd33; }")
            self.pin_btn.setToolTip('Unpin note')
        else:
            # Use the current note color for unpinned state
            pin_bg = self.settings.get('note_color', NOTE_BG_COLOR)
            def adjust_color(hex_color, factor):
                hex_color = hex_color.lstrip('#')
                r = int(hex_color[0:2], 16)
                g = int(hex_color[2:4], 16)
                b = int(hex_color[4:6], 16)
                r = min(255, max(0, int(r * 1.15)))
                g = min(255, max(0, int(g * 1.15)))
                b = min(255, max(0, int(b * 1.15)))
                return f'#{r:02X}{g:02X}{b:02X}'
            pin_bg = adjust_color(pin_bg, 1.15)
            self.pin_btn.setStyleSheet(f"QPushButton {{ background: {pin_bg}; border: none; font-weight: bold; color: black; }} QPushButton:hover {{ background: #f0f0b0; }}")
            self.pin_btn.setToolTip('Pin note on top')

    def close_note(self):
        """Mark note as deleted and close it"""
        self.is_deleted = True
        self.app.notes.remove(self)
        # Save immediately when note is deleted
        if self.app.settings.get('reopen_notes', False):
            self.app._save_notes()
        self.close()

    def eventFilter(self, obj, event):
        if event.type() == event.Type.MouseMove:
            # Convert child widget coordinates to parent coordinates
            child_pos = event.pos()
            global_pos = obj.mapToGlobal(child_pos)
            parent_pos = self.mapFromGlobal(global_pos)
            self._update_cursor(parent_pos)
        return super().eventFilter(obj, event)

    # --- Resizing logic ---
    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self.drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            self.resizing, self.resize_dir = self._check_resize_area(event.pos())
            if not self.resizing:
                self.dragging = True
                self.text_edit.setReadOnly(True)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent):
        # Always update cursor first, regardless of state
        self._update_cursor(event.pos())
        
        if self.resizing:
            self._resize_window(event.globalPosition().toPoint())
        elif self.dragging:
            self._move_window(event.globalPosition().toPoint())
        
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent):
        self.resizing = False
        self.dragging = False
        self.resize_dir = None
        self.text_edit.setReadOnly(False)
        super().mouseReleaseEvent(event)

    def _move_window(self, global_pos):
        if self.drag_pos is not None:
            new_pos = global_pos - self.drag_pos
            self.move(new_pos)

    def _check_resize_area(self, pos):
        rect = self.rect()
        x, y, w, h = pos.x(), pos.y(), rect.width(), rect.height()
        margin = self.EDGE_MARGIN
        # Corners
        if x < margin and y < margin:
            return True, 'topleft'
        if x > w - margin and y < margin:
            return True, 'topright'
        if x < margin and y > h - margin:
            return True, 'bottomleft'
        if x > w - margin and y > h - margin:
            return True, 'bottomright'
        # Edges
        if x < margin:
            return True, 'left'
        if x > w - margin:
            return True, 'right'
        if y < margin:
            return True, 'top'
        if y > h - margin:
            return True, 'bottom'
        return False, None

    def _update_cursor(self, pos):
        is_resize_area, dir = self._check_resize_area(pos)
        cursors = {
            'left': Qt.CursorShape.SizeHorCursor,
            'right': Qt.CursorShape.SizeHorCursor,
            'top': Qt.CursorShape.SizeVerCursor,
            'bottom': Qt.CursorShape.SizeVerCursor,
            'topleft': Qt.CursorShape.SizeFDiagCursor,
            'bottomright': Qt.CursorShape.SizeFDiagCursor,
            'topright': Qt.CursorShape.SizeBDiagCursor,
            'bottomleft': Qt.CursorShape.SizeBDiagCursor,
        }
        if is_resize_area and dir in cursors:
            self.setCursor(QCursor(cursors[dir]))
        else:
            self.setCursor(QCursor(Qt.CursorShape.ArrowCursor))

    def _resize_window(self, global_pos):
        geo = self.geometry()
        minw, minh = self.minimumWidth(), self.minimumHeight()
        dx = global_pos.x() - geo.x()
        dy = global_pos.y() - geo.y()
        dir = self.resize_dir
        if dir == 'left':
            diff = dx
            new_x = geo.x() + diff
            new_w = geo.width() - diff
            if new_w >= minw:
                self.setGeometry(new_x, geo.y(), new_w, geo.height())
        elif dir == 'right':
            new_w = dx
            if new_w >= minw:
                self.resize(new_w, geo.height())
        elif dir == 'top':
            diff = dy
            new_y = geo.y() + diff
            new_h = geo.height() - diff
            if new_h >= minh:
                self.setGeometry(geo.x(), new_y, geo.width(), new_h)
        elif dir == 'bottom':
            new_h = dy
            if new_h >= minh:
                self.resize(geo.width(), new_h)
        elif dir == 'topleft':
            diffx = dx
            diffy = dy
            new_x = geo.x() + diffx
            new_y = geo.y() + diffy
            new_w = geo.width() - diffx
            new_h = geo.height() - diffy
            if new_w >= minw and new_h >= minh:
                self.setGeometry(new_x, new_y, new_w, new_h)
        elif dir == 'topright':
            diffx = dx - geo.width()
            diffy = dy
            new_y = geo.y() + diffy
            new_w = geo.width() + diffx
            new_h = geo.height() - diffy
            if new_w >= minw and new_h >= minh:
                self.setGeometry(geo.x(), new_y, new_w, new_h)
        elif dir == 'bottomleft':
            diffx = dx
            diffy = dy - geo.height()
            new_x = geo.x() + diffx
            new_w = geo.width() - diffx
            new_h = geo.height() + diffy
            if new_w >= minw and new_h >= minh:
                self.setGeometry(new_x, geo.y(), new_w, new_h)
        elif dir == 'bottomright':
            diffx = dx - geo.width()
            diffy = dy - geo.height()
            new_w = geo.width() + diffx
            new_h = geo.height() + diffy
            if new_w >= minw and new_h >= minh:
                self.resize(new_w, new_h)

    def _apply_text_style(self):
        text_color = self.settings.get('note_text_color', NOTE_TEXT_COLOR)
        text_size = self.settings.get('note_text_size', NOTE_TEXT_SIZE)
        font_family = self.settings.get('note_font_family', NOTE_FONT_FAMILY)
        self.text_edit.setStyleSheet(f"background: transparent; border: none; font-size: {text_size}px; color: {text_color}; font-family: '{font_family}';")

    def update_note_color(self, color=None, text_color=None, text_size=None, font_family=None):
        """Update the note background, text color, text size, and font dynamically and update button colors."""
        if color is None:
            color = self.settings.get('note_color', NOTE_BG_COLOR)
        if text_color is None:
            text_color = self.settings.get('note_text_color', NOTE_TEXT_COLOR)
        if text_size is None:
            text_size = self.settings.get('note_text_size', NOTE_TEXT_SIZE)
        if font_family is None:
            font_family = self.settings.get('note_font_family', NOTE_FONT_FAMILY)
        self.setStyleSheet(f"background: {color}; border: 1px solid #e0e0a0;")
        self.text_edit.setStyleSheet(f"background: transparent; border: none; font-size: {text_size}px; color: {text_color}; font-family: '{font_family}';")
        self._update_button_colors(color)

    def _update_button_colors(self, base_color):
        """Update the close, add, and pin button background colors to match the note color."""
        def adjust_color(hex_color, factor):
            # Simple lighten/darken by factor (0.0-1.0 darken, >1.0 lighten)
            hex_color = hex_color.lstrip('#')
            r = int(hex_color[0:2], 16)
            g = int(hex_color[2:4], 16)
            b = int(hex_color[4:6], 16)
            r = min(255, max(0, int(r * factor)))
            g = min(255, max(0, int(g * factor)))
            b = min(255, max(0, int(b * factor)))
            return f'#{r:02X}{g:02X}{b:02X}'
        # Use slightly different shades for each button
        close_bg = adjust_color(base_color, 0.95)  # Slightly darker
        add_bg = adjust_color(base_color, 1.08)    # Slightly lighter
        pin_bg = adjust_color(base_color, 1.15)    # Even lighter
        self.close_btn.setStyleSheet(f"QPushButton {{ background: {close_bg}; border: none; font-weight: bold; color: black; }} QPushButton:hover {{ background: #ffaaaa; }}")
        self.add_btn.setStyleSheet(f"QPushButton {{ background: {add_bg}; border: none; font-weight: bold; color: black; }} QPushButton:hover {{ background: #aaffaa; }}")
        if self.pinned:
            self.pin_btn.setStyleSheet("QPushButton { background: #ffcc00; border: none; font-weight: bold; color: black; } QPushButton:hover { background: #ffdd33; }")
        else:
            self.pin_btn.setStyleSheet(f"QPushButton {{ background: {pin_bg}; border: none; font-weight: bold; color: black; }} QPushButton:hover {{ background: #f0f0b0; }}")

# Main Application Class
class StickyNotesApp(QApplication):
    def __init__(self, argv):
        super().__init__(argv)
        self.setQuitOnLastWindowClosed(False)
        
        # Clean up old settings first
        cleanup_old_settings()
        
        self.settings = load_settings()
        
        # Hide terminal window if setting is enabled
        if self.settings.get('hide_terminal', True):
            import ctypes
            ctypes.windll.user32.ShowWindow(ctypes.windll.kernel32.GetConsoleWindow(), 0)
        
        # Check if password prompt is required on startup
        if (self.settings.get('encrypt_notes', False) and 
            self.settings.get('prompt_password_on_startup', False)):
            
            if not verify_encryption_password():
                # Password verification failed or was cancelled
                QMessageBox.warning(None, "Access Denied", 
                                  "Incorrect password or access cancelled. Application will exit.")
                sys.exit(0)
        
        self.notes = []
        self.tray_icon = None
        self.hotkey_listener = None
        self.oled_icon_text_visible = False
        self.oled_icon_timer = None
        # Show OLED icon text for 15 seconds on launch if OLED theme is active
        if self.settings.get('tray_icon_theme', 'default') == 'oled':
            self.oled_icon_text_visible = True
            # Start a timer to hide text after 15 seconds
            from PyQt6.QtCore import QTimer
            self.oled_icon_timer = QTimer()
            self.oled_icon_timer.setSingleShot(True)
            def hide_text():
                self.oled_icon_text_visible = False
                self.update_tray_icon()
            self.oled_icon_timer.timeout.connect(hide_text)
            self.oled_icon_timer.start(15000)
        self._init_tray()
        self._init_hotkey()
        
        # Setup periodic cleanup timer
        from PyQt6.QtCore import QTimer
        self.cleanup_timer = QTimer()
        self.cleanup_timer.timeout.connect(self._cleanup_memory)
        self.cleanup_timer.start(CLEANUP_INTERVAL)
        
        # Load saved notes if reopen_notes is enabled
        if self.settings.get('reopen_notes', False):
            self._load_saved_notes()
        else:
            # Create a default note if no notes to reopen
            self.create_note()

    def create_note(self, text="", geometry=None, pinned=False):
        note = StickyNote(self, self.settings, str(text), geometry, pinned)
        
        # Check for overlapping notes and reposition if needed
        self._avoid_overlap(note)
        
        note.show()
        self.notes.append(note)
        return note

    def _load_saved_notes(self):
        """Load saved notes from file"""
        saved_notes = load_notes(self.settings)
        if saved_notes:
            for note_data in saved_notes:
                self.create_note(
                    text=note_data.get('text', ''),
                    geometry=note_data.get('geometry'),
                    pinned=note_data.get('pinned', False)  # Load pin state
                )
        else:
            # Create a default note if no saved notes
            self.create_note()

    def _save_notes(self):
        """Save current notes to file"""
        if self.settings.get('reopen_notes', False):
            save_notes(self.notes, self.settings)

    def _cleanup_memory(self):
        """Periodic memory cleanup to reduce resource usage"""
        import gc
        
        # Remove deleted notes from the list
        self.notes = [note for note in self.notes if not getattr(note, 'is_deleted', False)]
        
        # Force garbage collection
        gc.collect()
        
        # Limit number of notes in memory
        if len(self.notes) > MAX_NOTES_TO_SAVE:
            # Remove oldest notes (keep the most recent ones)
            notes_to_remove = len(self.notes) - MAX_NOTES_TO_SAVE
            for _ in range(notes_to_remove):
                if self.notes:
                    oldest_note = self.notes.pop(0)
                    oldest_note.close()
                    oldest_note.deleteLater()

    def _avoid_overlap(self, new_note):
        """Reposition new note to avoid overlapping with existing notes"""
        if not self.notes:
            return  # No existing notes to check against
        
        new_rect = new_note.geometry()
        offset = new_rect.width() + 20  # Full note width plus 20px gap
        
        for existing_note in self.notes:
            existing_rect = existing_note.geometry()
            
            # Check if notes overlap
            if (new_rect.x() < existing_rect.x() + existing_rect.width() and
                new_rect.x() + new_rect.width() > existing_rect.x() and
                new_rect.y() < existing_rect.y() + existing_rect.height() and
                new_rect.y() + new_rect.height() > existing_rect.y()):
                
                # Try moving right first
                new_pos = new_rect.topLeft() + QPoint(offset, 0)
                new_rect.moveTopLeft(new_pos)
                
                # Check if moving right still causes overlap
                still_overlapping = False
                for other_note in self.notes:
                    other_rect = other_note.geometry()
                    if (new_rect.x() < other_rect.x() + other_rect.width() and
                        new_rect.x() + new_rect.width() > other_rect.x() and
                        new_rect.y() < other_rect.y() + other_rect.height() and
                        new_rect.y() + new_rect.height() > other_rect.y()):
                        still_overlapping = True
                        break
                
                # If still overlapping, try moving left instead
                if still_overlapping:
                    new_pos = new_rect.topLeft() - QPoint(offset * 2, 0)  # Move back and then left
                    new_rect.moveTopLeft(new_pos)
                
                # Update the note position
                new_note.setGeometry(new_rect)
                break

    def _init_tray(self):
        # Create a simple icon for the tray
        theme = self.settings.get('tray_icon_theme', 'default')
        show_text = True
        if theme == 'oled' and not getattr(self, 'oled_icon_text_visible', False):
            show_text = False
        icon = get_tray_icon(theme, show_text)
        self.tray_icon = QSystemTrayIcon(icon)
        self.tray_icon.setToolTip(APP_NAME)
        
        # Create tray menu
        tray_menu = QMenu()

        # New: Add 'New Note' action
        new_note_action = QAction("New Note", self)
        new_note_action.triggered.connect(lambda: self.create_note())
        tray_menu.addAction(new_note_action)

        # New: Add 'Delete All Notes' action
        delete_all_action = QAction("Delete All Open Notes", self)
        delete_all_action.triggered.connect(self._confirm_delete_all_notes)
        tray_menu.addAction(delete_all_action)

        # Settings action
        settings_action = QAction("Settings", self)
        settings_action.triggered.connect(self.show_settings)
        tray_menu.addAction(settings_action)
        
        # Separator
        tray_menu.addSeparator()
        
        # Exit action
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.exit_app)
        tray_menu.addAction(exit_action)
        
        # Set the menu
        self.tray_icon.setContextMenu(tray_menu)
        
        # Show the tray icon
        self.tray_icon.show()
        
        # Verify tray icon is available
        if not self.tray_icon.isSystemTrayAvailable():
            print("System tray is not available")
        else:
            print("System tray icon created successfully")

        # Connect double click event
        self.tray_icon.activated.connect(self._on_tray_icon_activated)

    def _on_tray_icon_activated(self, reason):
        # QSystemTrayIcon.ActivationReason.DoubleClick is the double left click
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self.create_note()
        # OLED icon: show text on any activation, then hide after 2 seconds
        theme = self.settings.get('tray_icon_theme', 'default')
        if theme == 'oled':
            self.oled_icon_text_visible = True
            self.update_tray_icon()
            from PyQt6.QtCore import QTimer
            if self.oled_icon_timer:
                self.oled_icon_timer.stop()
            self.oled_icon_timer = QTimer()
            self.oled_icon_timer.setSingleShot(True)
            def hide_text():
                self.oled_icon_text_visible = False
                self.update_tray_icon()
            self.oled_icon_timer.timeout.connect(hide_text)
            self.oled_icon_timer.start(2000)

    def show_settings(self):
        dlg = SettingsDialog(self.settings)
        
        # Set the dialog to always be on top if the setting is enabled
        if self.settings['always_on_top']:
            dlg.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            dlg.show()  # Need to show after setting the flag
        
        if dlg.exec():
            new_settings = dlg.get_settings()
            
            # Check if encryption is being disabled
            encryption_disabled = (self.settings.get('encrypt_notes', False) and 
                                 not new_settings.get('encrypt_notes', False))
            
            # If encryption is being disabled, decrypt and resave notes
            if encryption_disabled:
                if not self._decrypt_and_resave_notes():
                    QMessageBox.warning(None, "Decryption Failed", 
                                      "Failed to decrypt notes. Encryption will remain enabled.")
                    return  # Don't save settings if decryption failed
            
            self.settings.update(new_settings)
            save_settings(self.settings)
            set_startup(self.settings['launch_on_startup'])
            self.update_tray_icon() # Update tray icon after settings change
            # Update all notes' always-on-top (consider individual pin states)
            for note in self.notes:
                note.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.settings['always_on_top'] or getattr(note, 'pinned', False))
                note.update_note_color(
                    self.settings.get('note_color', NOTE_BG_COLOR),
                    self.settings.get('note_text_color', NOTE_TEXT_COLOR),
                    self.settings.get('note_text_size', NOTE_TEXT_SIZE),
                    self.settings.get('note_font_family', NOTE_FONT_FAMILY)
                )
                note.show()  # Needed to apply flag
            self._init_hotkey()

    def _decrypt_and_resave_notes(self):
        """Decrypt notes and save them in plain text format"""
        try:
            if not os.path.exists(NOTES_FILE):
                return True  # No file to decrypt
            
            # Load notes to check if they're actually encrypted
            with open(NOTES_FILE, 'r') as f:
                data = json.load(f)
            
            # Check if data is encrypted
            if isinstance(data, dict) and 'salt' in data and 'data' in data:
                # Data is encrypted, so we need a password
                password = get_password_from_credential_manager()
                if not password:
                    QMessageBox.warning(None, "No Password", 
                                      "No encryption password found. Cannot decrypt notes.")
                    return False
                
                decrypted_data = decrypt_data(data, password)
                if decrypted_data is None:
                    QMessageBox.warning(None, "Decryption Failed", 
                                      "Failed to decrypt notes with current password.")
                    return False
                
                # Save decrypted data in plain text format
                with open(NOTES_FILE, 'w') as f:
                    json.dump(decrypted_data, f, indent=2)
                
                QMessageBox.information(None, "Decryption Complete", 
                                      "Notes have been decrypted and saved in plain text format.")
                return True
            else:
                # Data is already not encrypted, nothing to do
                return True
                
        except Exception as e:
            QMessageBox.warning(None, "Decryption Error", 
                              f"Error during decryption: {str(e)}")
            return False

    def exit_app(self):
        # Save notes before exiting
        self._save_notes()
        if self.tray_icon is not None:
            self.tray_icon.hide()
        for note in self.notes:
            note.close()
        self.quit()

    def _init_hotkey(self):
        if hasattr(self, 'hotkey_listener') and self.hotkey_listener:
            self.hotkey_listener.stop()

        hotkey = self.settings.get('hotkey', 'ctrl+shift+s').lower()
        # Convert to pynput format: ctrl+shift+s -> <ctrl>+<shift>+s
        parts = []
        for part in hotkey.split('+'):
            part = part.strip()
            if part == 'ctrl':
                parts.append('<ctrl>')
            elif part == 'shift':
                parts.append('<shift>')
            elif part == 'alt':
                parts.append('<alt>')
            else:
                parts.append(part)
        hotkey_str = '+'.join(parts)

        def on_activate():
            from PyQt6.QtCore import QTimer
            QTimer.singleShot(0, self.create_note)

        from pynput import keyboard
        self.hotkey_listener = keyboard.GlobalHotKeys({
            hotkey_str: on_activate
        })
        self.hotkey_listener.start()

    def _confirm_delete_all_notes(self):
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QLabel, QLineEdit, QPushButton, QHBoxLayout
        dialog = QDialog()
        dialog.setWindowTitle("Delete All Notes")
        dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        layout = QVBoxLayout(dialog)
        label = QLabel("Type DELETE to confirm you want to close all open notes. This cannot be undone.")
        layout.addWidget(label)
        input_box = QLineEdit()
        layout.addWidget(input_box)
        btn_layout = QHBoxLayout()
        delete_btn = QPushButton("Delete")
        delete_btn.setEnabled(False)
        cancel_btn = QPushButton("Cancel")
        btn_layout.addWidget(delete_btn)
        btn_layout.addWidget(cancel_btn)
        layout.addLayout(btn_layout)
        def on_text_changed(text):
            delete_btn.setEnabled(text == "DELETE")
        input_box.textChanged.connect(on_text_changed)
        def on_delete():
            dialog.accept()
        def on_cancel():
            dialog.reject()
        delete_btn.clicked.connect(on_delete)
        cancel_btn.clicked.connect(on_cancel)
        dialog.setLayout(layout)
        result = dialog.exec()
        if result == QDialog.DialogCode.Accepted:
            self._delete_all_notes()

    def _delete_all_notes(self):
        # Close all notes and clear the list
        for note in self.notes[:]:
            note.is_deleted = True
            note.close()
        self.notes.clear()
        # Save notes to persist deletion if needed
        if self.settings.get('reopen_notes', False):
            self._save_notes()

    def update_tray_icon(self):
        if self.tray_icon:
            theme = self.settings.get('tray_icon_theme', 'default')
            show_text = True
            if theme == 'oled' and not getattr(self, 'oled_icon_text_visible', False):
                show_text = False
            icon = get_tray_icon(theme, show_text)
            self.tray_icon.setIcon(icon)

# Custom Hotkey Input Widget
class HotkeyInput(QLineEdit):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setMaxLength(1)  # Only allow one character
        self.setPlaceholderText("Press a key...")
        self.hotkey_listener = None
        self.current_hotkey = ""
        self.recording = False
        
    def focusInEvent(self, event):
        super().focusInEvent(event)
        self.start_recording()
        
    def focusOutEvent(self, event):
        super().focusOutEvent(event)
        self.stop_recording()
        
    def start_recording(self):
        if self.recording:
            return
        self.recording = True
        self.setText("")
        
        def on_press(key):
            if not self.recording:
                return
            # Handle character keys (letters and numbers only)
            if hasattr(key, 'char') and key.char and key.char.isprintable():
                char_key = key.char.lower()
                if char_key.isalnum():  # Only letters and numbers
                    self.setText(char_key)
                    self.current_hotkey = char_key
                    self.stop_recording()
                    return

        def on_release(key):
            pass  # We don't need to handle releases for single key detection

        if self.hotkey_listener:
            self.hotkey_listener.stop()
            self.hotkey_listener = None
        self.hotkey_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        self.hotkey_listener.start()
        
    def stop_recording(self):
        if self.hotkey_listener:
            self.hotkey_listener.stop()
            self.hotkey_listener = None
        self.recording = False

    def get_hotkey(self):
        return self.current_hotkey

# Settings Dialog
class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle('StickyPosts - Settings')
        self.setFixedSize(400, 550)  # Increased height for new option
        self.settings = settings
        tab_widget = QTabWidget(self)
        general_tab = QWidget()
        general_layout = QVBoxLayout(general_tab)
        general_layout.setSpacing(10)
        general_layout.setContentsMargins(20, 20, 20, 20)
        # Launch on startup
        self.startup_cb = QCheckBox('Launch on system startup')
        self.startup_cb.setChecked(settings['launch_on_startup'])
        general_layout.addWidget(self.startup_cb)
        # Always on top
        self.ontop_cb = QCheckBox('Always on top for all notes')
        self.ontop_cb.setChecked(settings['always_on_top'])
        general_layout.addWidget(self.ontop_cb)
        # Reopen notes
        self.reopen_cb = QCheckBox('Reopen notes on startup')
        self.reopen_cb.setChecked(settings['reopen_notes'])
        general_layout.addWidget(self.reopen_cb)
        # Hide terminal window
        self.hide_terminal_cb = QCheckBox('Hide terminal window on launch')
        self.hide_terminal_cb.setChecked(settings.get('hide_terminal', True))
        general_layout.addWidget(self.hide_terminal_cb)
        # Tray icon theme
        icon_theme_label = QLabel('System tray icon theme:')
        general_layout.addWidget(icon_theme_label)
        self.icon_theme_combo = QComboBox()
        self.icon_theme_combo.setFixedHeight(25)
        self.icon_theme_combo.addItems([
            'Default (Yellow)',
            'Dark Mode',
            'OLED Safe',
            'Monochrome',
        ])
        theme_map = {
            'default': 0,
            'dark': 1,
            'oled': 2,
            'monochrome': 3,
        }
        self.icon_theme_combo.setCurrentIndex(theme_map.get(settings.get('tray_icon_theme', 'default'), 0))
        general_layout.addWidget(self.icon_theme_combo)
        # Hotkey section
        general_layout.addSpacing(10)
        hotkey_label = QLabel('Global hotkey for new note:')
        general_layout.addWidget(hotkey_label)
        modifier_layout = QHBoxLayout()
        self.ctrl_cb = QCheckBox('Ctrl')
        self.shift_cb = QCheckBox('Shift')
        self.alt_cb = QCheckBox('Alt')
        hotkey = settings.get('hotkey', 'ctrl+shift+s').lower()
        if 'ctrl' in hotkey:
            self.ctrl_cb.setChecked(True)
        if 'shift' in hotkey:
            self.shift_cb.setChecked(True)
        if 'alt' in hotkey:
            self.alt_cb.setChecked(True)
        modifier_layout.addWidget(self.ctrl_cb)
        modifier_layout.addWidget(self.shift_cb)
        modifier_layout.addWidget(self.alt_cb)
        modifier_layout.addStretch()
        general_layout.addLayout(modifier_layout)
        key_layout = QHBoxLayout()
        key_label = QLabel('Key:')
        self.hotkey_edit = HotkeyInput()
        self.hotkey_edit.setFixedHeight(20)
        key_parts = hotkey.split('+')
        for part in key_parts:
            if part not in ['ctrl', 'shift', 'alt'] and len(part) == 1:
                self.hotkey_edit.setText(part)
                self.hotkey_edit.current_hotkey = part
                break
        key_layout.addWidget(key_label)
        key_layout.addWidget(self.hotkey_edit)
        general_layout.addLayout(key_layout)
        general_layout.addStretch()
        # Buttons (Save/Cancel) at the bottom of the dialog, not in the tab
        # Encryption tab
        encryption_tab = QWidget()
        encryption_layout = QVBoxLayout(encryption_tab)
        encryption_layout.setSpacing(10)
        encryption_layout.setContentsMargins(20, 20, 20, 20)
        # Encryption settings
        self.encrypt_cb = QCheckBox('Encrypt notes')
        self.encrypt_cb.setChecked(settings['encrypt_notes'])
        self.encrypt_cb.toggled.connect(self._on_encryption_toggled)
        encryption_layout.addWidget(self.encrypt_cb)
        # Encryption password management
        password_layout = QHBoxLayout()
        self.password_btn = QPushButton('Set Encryption Password')
        self.password_btn.setFixedHeight(30)
        self.password_btn.clicked.connect(self._set_encryption_password)
        password_layout.addWidget(self.password_btn)
        self.password_status = QLabel('No password set')
        if get_password_from_credential_manager():
            self.password_status.setText('Password is set')
        password_layout.addWidget(self.password_status)
        encryption_layout.addLayout(password_layout)
        encryption_layout.addSpacing(5)
        self.startup_prompt_cb = QCheckBox('Prompt for password on startup')
        self.startup_prompt_cb.setChecked(settings['prompt_password_on_startup'])
        self.startup_prompt_cb.setEnabled(settings['encrypt_notes'])
        encryption_layout.addWidget(self.startup_prompt_cb)
        encryption_layout.addStretch()
        # Theme tab (was Colors)
        theme_tab = QWidget()
        theme_layout = QVBoxLayout(theme_tab)
        theme_layout.setSpacing(10)
        theme_layout.setContentsMargins(20, 20, 20, 20)
        color_label = QLabel('Sticky note color:')
        theme_layout.addWidget(color_label)
        self.color_combo = QComboBox()
        self.color_options = [
            ('Yellow', '#FFFFE0'),
            ('Blue', '#E0F0FF'),
            ('Green', '#E0FFE0'),
            ('Pink', '#FFE0F0'),
            ('White', '#FFFFFF'),
            ('Gray', '#222222'),
            ('Black', '#000000'),
            ('Custom...', None),
        ]
        for name, _ in self.color_options:
            self.color_combo.addItem(name)
        # Set current index based on settings
        current_color = settings.get('note_color', NOTE_BG_COLOR)
        idx = next((i for i, (_, c) in enumerate(self.color_options[:-1]) if c and c.lower() == current_color.lower()), None)
        if idx is not None:
            self.color_combo.setCurrentIndex(idx)
            self.selected_color = self.color_options[idx][1]
        else:
            # Not a preset, treat as custom
            self.color_combo.setCurrentIndex(len(self.color_options) - 1)
            self.selected_color = current_color
        theme_layout.addWidget(self.color_combo)
        self.custom_color_btn = QPushButton('Choose Custom Color')
        self.custom_color_btn.setFixedHeight(30)
        theme_layout.addWidget(self.custom_color_btn)
        self.selected_color = current_color
        def on_color_combo_changed(index):
            if self.color_options[index][1] is not None:
                self.selected_color = self.color_options[index][1]
            else:
                # Open color dialog
                from PyQt6.QtWidgets import QColorDialog
                color_dialog = QColorDialog(self)
                color_dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
                if color_dialog.exec():
                    color = color_dialog.currentColor()
                    if color.isValid():
                        self.selected_color = color.name()
                        return
                # Revert to previous selection
                self.color_combo.setCurrentIndex(0)
                self.selected_color = self.color_options[0][1]
        self.color_combo.currentIndexChanged.connect(on_color_combo_changed)
        def on_custom_color_btn():
            from PyQt6.QtWidgets import QColorDialog
            color_dialog = QColorDialog(self)
            color_dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            if color_dialog.exec():
                color = color_dialog.currentColor()
                if color.isValid():
                    self.selected_color = color.name()
                    self.color_combo.setCurrentIndex(len(self.color_options) - 1)
        self.custom_color_btn.clicked.connect(on_custom_color_btn)
        # --- Text color option ---
        text_color_label = QLabel('Sticky note text color:')
        theme_layout.addWidget(text_color_label)
        self.text_color_combo = QComboBox()
        self.text_color_options = [
            ('Black', '#000000'),
            ('Dark Blue', '#003366'),
            ('Dark Green', '#006600'),
            ('Dark Red', '#990000'),
            ('Gray', '#444444'),
            ('White', '#FFFFFF'),
            ('Custom...', None),
        ]
        for name, _ in self.text_color_options:
            self.text_color_combo.addItem(name)
        current_text_color = settings.get('note_text_color', NOTE_TEXT_COLOR)
        idx = next((i for i, (_, c) in enumerate(self.text_color_options[:-1]) if c and c.lower() == current_text_color.lower()), None)
        if idx is not None:
            self.text_color_combo.setCurrentIndex(idx)
            self.selected_text_color = self.text_color_options[idx][1]
        else:
            self.text_color_combo.setCurrentIndex(len(self.text_color_options) - 1)
            self.selected_text_color = current_text_color
        theme_layout.addWidget(self.text_color_combo)
        self.custom_text_color_btn = QPushButton('Choose Custom Text Color')
        self.custom_text_color_btn.setFixedHeight(30)
        theme_layout.addWidget(self.custom_text_color_btn)
        self.selected_text_color = current_text_color
        def on_text_color_combo_changed(index):
            if self.text_color_options[index][1] is not None:
                self.selected_text_color = self.text_color_options[index][1]
            else:
                from PyQt6.QtWidgets import QColorDialog
                color_dialog = QColorDialog(self)
                color_dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
                if color_dialog.exec():
                    color = color_dialog.currentColor()
                    if color.isValid():
                        self.selected_text_color = color.name()
                        return
                self.text_color_combo.setCurrentIndex(0)
                self.selected_text_color = self.text_color_options[0][1]
        self.text_color_combo.currentIndexChanged.connect(on_text_color_combo_changed)
        def on_custom_text_color_btn():
            from PyQt6.QtWidgets import QColorDialog
            color_dialog = QColorDialog(self)
            color_dialog.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
            if color_dialog.exec():
                color = color_dialog.currentColor()
                if color.isValid():
                    self.selected_text_color = color.name()
                    self.text_color_combo.setCurrentIndex(len(self.text_color_options) - 1)
        self.custom_text_color_btn.clicked.connect(on_custom_text_color_btn)
        # --- Text size option ---
        text_size_label = QLabel('Sticky note text size:')
        theme_layout.addWidget(text_size_label)
        from PyQt6.QtWidgets import QSpinBox, QFontComboBox
        self.text_size_spin = QSpinBox()
        self.text_size_spin.setRange(8, 48)
        self.text_size_spin.setValue(settings.get('note_text_size', NOTE_TEXT_SIZE))
        self.text_size_spin.setSingleStep(1)
        theme_layout.addWidget(self.text_size_spin)
        # --- Font family option ---
        font_label = QLabel('Sticky note font:')
        theme_layout.addWidget(font_label)
        self.font_combo = QFontComboBox()
        self.font_combo.setEditable(False)
        self.font_combo.setCurrentText(settings.get('note_font_family', NOTE_FONT_FAMILY))
        theme_layout.addWidget(self.font_combo)
        theme_layout.addStretch()
        tab_widget.addTab(general_tab, 'General')
        tab_widget.addTab(encryption_tab, 'Encryption')
        tab_widget.addTab(theme_tab, 'Theme')
        main_layout = QVBoxLayout(self)
        main_layout.addWidget(tab_widget)
        btn_layout = QHBoxLayout()
        self.save_btn = QPushButton('Save')
        self.save_btn.setFixedHeight(25)
        self.save_btn.clicked.connect(self.accept)
        self.cancel_btn = QPushButton('Cancel')
        self.cancel_btn.setFixedHeight(25)
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addStretch()
        btn_layout.addWidget(self.save_btn)
        btn_layout.addWidget(self.cancel_btn)
        main_layout.addLayout(btn_layout)
        self.setLayout(main_layout)

    def _on_encryption_toggled(self, enabled):
        """Enable/disable startup prompt based on encryption setting"""
        self.startup_prompt_cb.setEnabled(enabled)
        if not enabled:
            self.startup_prompt_cb.setChecked(False)

    def _set_encryption_password(self):
        """Set or change the encryption password"""
        password, ok = QInputDialog.getText(
            self, 
            'Set Encryption Password', 
            'Enter encryption password (leave empty to remove):',
            QLineEdit.EchoMode.Password
        )
        
        if ok:
            if password:
                # Set new password
                if save_password_to_credential_manager(password):
                    self.password_status.setText('Password is set')
                    QMessageBox.information(self, 'Success', 'Encryption password has been set.')
                else:
                    QMessageBox.warning(self, 'Error', 'Failed to save password to Windows Credential Manager.')
            else:
                # Remove password - check if we need to decrypt notes first
                if self.encrypt_cb.isChecked():
                    reply = QMessageBox.question(
                        self, 
                        'Remove Password', 
                        'Removing the password will decrypt and save notes in plain text. Continue?',
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
                    )
                    if reply == QMessageBox.StandardButton.Yes:
                        # Decrypt notes before removing password
                        if self._decrypt_and_resave_notes():
                            if delete_password_from_credential_manager():
                                self.password_status.setText('No password set')
                                QMessageBox.information(self, 'Success', 'Notes decrypted and password removed.')
                            else:
                                QMessageBox.warning(self, 'Error', 'Failed to remove password from Windows Credential Manager.')
                        else:
                            QMessageBox.warning(self, 'Decryption Failed', 'Failed to decrypt notes. Password not removed.')
                    else:
                        return  # User cancelled
                else:
                    # Encryption is disabled, just remove password
                    if delete_password_from_credential_manager():
                        self.password_status.setText('No password set')
                        QMessageBox.information(self, 'Success', 'Encryption password has been removed.')
                    else:
                        QMessageBox.warning(self, 'Error', 'Failed to remove password from Windows Credential Manager.')

    def _decrypt_and_resave_notes(self):
        """Decrypt notes and save them in plain text format"""
        try:
            if not os.path.exists(NOTES_FILE):
                return True  # No file to decrypt
            
            # Load notes to check if they're actually encrypted
            with open(NOTES_FILE, 'r') as f:
                data = json.load(f)
            
            # Check if data is encrypted
            if isinstance(data, dict) and 'salt' in data and 'data' in data:
                # Data is encrypted, so we need a password
                password = get_password_from_credential_manager()
                if not password:
                    QMessageBox.warning(self, "No Password", 
                                      "No encryption password found. Cannot decrypt notes.")
                    return False
                
                decrypted_data = decrypt_data(data, password)
                if decrypted_data is None:
                    QMessageBox.warning(self, "Decryption Failed", 
                                      "Failed to decrypt notes with current password.")
                    return False
                
                # Save decrypted data in plain text format
                with open(NOTES_FILE, 'w') as f:
                    json.dump(decrypted_data, f, indent=2)
                
                QMessageBox.information(self, "Decryption Complete", 
                                      "Notes have been decrypted and saved in plain text format.")
                return True
            else:
                # Data is already not encrypted, nothing to do
                return True
                
        except Exception as e:
            QMessageBox.warning(self, "Decryption Error", 
                              f"Error during decryption: {str(e)}")
            return False

    def get_settings(self):
        # Build hotkey string from checkboxes and key
        modifiers = []
        if self.ctrl_cb.isChecked():
            modifiers.append('ctrl')
        if self.shift_cb.isChecked():
            modifiers.append('shift')
        if self.alt_cb.isChecked():
            modifiers.append('alt')
        
        key = self.hotkey_edit.get_hotkey()
        if key:
            modifiers.append(key)
        
        hotkey = '+'.join(modifiers) if modifiers else 'ctrl+shift+s'
        theme_idx = self.icon_theme_combo.currentIndex()
        theme_val = ['default', 'dark', 'oled', 'monochrome'][theme_idx]
        result = {
            'launch_on_startup': self.startup_cb.isChecked(),
            'always_on_top': self.ontop_cb.isChecked(),
            'hotkey': hotkey,
            'reopen_notes': self.reopen_cb.isChecked(),
            'encrypt_notes': self.encrypt_cb.isChecked(),
            'prompt_password_on_startup': self.startup_prompt_cb.isChecked(),
            'tray_icon_theme': theme_val,
            'note_color': getattr(self, 'selected_color', NOTE_BG_COLOR),
            'note_text_color': getattr(self, 'selected_text_color', NOTE_TEXT_COLOR),
            'note_text_size': self.text_size_spin.value(),
            'note_font_family': self.font_combo.currentText(),
            'hide_terminal': self.hide_terminal_cb.isChecked(),
        }
        return result

if __name__ == '__main__':
    app = StickyNotesApp(sys.argv)
    sys.exit(app.exec()) 
import sys
import os
import json
import base64
from cryptography.fernet import Fernet
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from PyQt6.QtWidgets import (
    QApplication, QWidget, QTextEdit, QPushButton, QHBoxLayout, QVBoxLayout, QSystemTrayIcon, QMenu, QCheckBox, QLabel, QDialog, QLineEdit, QMessageBox, QInputDialog
)
from PyQt6.QtGui import QIcon, QCursor, QMouseEvent, QKeySequence, QAction
from PyQt6.QtCore import Qt, QRect, QPoint, QSize
import win32com.client  # For startup shortcut
import win32cred  # For Windows Credential Manager
from pynput import keyboard  # For global hotkey
import threading

# Constants
NOTE_BG_COLOR = '#FFFFE0'
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
        self.setStyleSheet(f"background: {NOTE_BG_COLOR}; border: 1px solid #e0e0a0;")
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
        self.text_edit.setStyleSheet("background: transparent; border: none; font-size: 14px; color: black;")
        self.text_edit.setText(text)
        
        # Set maximum text length to prevent excessive memory usage
        self.text_edit.document().setMaximumBlockCount(MAX_NOTE_TEXT_LENGTH // 100)  # Approximate blocks
        
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
        self.close_btn.setStyleSheet("QPushButton { background: #e0e0a0; border: none; font-weight: bold; color: black; } QPushButton:hover { background: #ffaaaa; }")
        self.close_btn.clicked.connect(self.close_note)
        
        self.add_btn = QPushButton('+', self)
        self.add_btn.setFixedSize(24, 24)
        self.add_btn.setStyleSheet("QPushButton { background: #e0e0a0; border: none; font-weight: bold; color: black; } QPushButton:hover { background: #aaffaa; }")
        self.add_btn.clicked.connect(lambda: self.app.create_note("", pinned=False))
        
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
            self.pin_btn.setStyleSheet("QPushButton { background: #e0e0a0; border: none; font-weight: bold; color: black; } QPushButton:hover { background: #f0f0b0; }")
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
        if self.drag_pos:
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

# Main Application Class
class StickyNotesApp(QApplication):
    def __init__(self, argv):
        super().__init__(argv)
        self.setQuitOnLastWindowClosed(False)
        
        # Clean up old settings first
        cleanup_old_settings()
        
        self.settings = load_settings()
        
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
        icon = QIcon()
        # Use a simple colored square as icon
        from PyQt6.QtGui import QPixmap, QPainter, QColor
        pixmap = QPixmap(16, 16)
        pixmap.fill(QColor(255, 255, 224))  # Same yellow as notes
        painter = QPainter(pixmap)
        painter.setPen(QColor(0, 0, 0))
        painter.drawText(pixmap.rect(), Qt.AlignmentFlag.AlignCenter, "S")
        painter.end()
        icon.addPixmap(pixmap)
        
        self.tray_icon = QSystemTrayIcon(icon)
        self.tray_icon.setToolTip(APP_NAME)
        
        # Create tray menu
        tray_menu = QMenu()
        
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
            # Update all notes' always-on-top (consider individual pin states)
            for note in self.notes:
                note.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, self.settings['always_on_top'] or getattr(note, 'pinned', False))
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
        self.tray_icon.hide()
        for note in self.notes:
            note.close()
        self.quit()

    def _init_hotkey(self):
        # Stop previous listener
        if self.hotkey_listener:
            self.hotkey_listener.stop()
        
        # Parse hotkey string
        hotkey = self.settings.get('hotkey', 'ctrl+shift+s').lower()
        self._required_keys = set()
        
        for part in hotkey.split('+'):
            part = part.strip()
            if part == 'ctrl':
                self._required_keys.add(keyboard.Key.ctrl)
            elif part == 'shift':
                self._required_keys.add(keyboard.Key.shift)
            elif part == 'alt':
                self._required_keys.add(keyboard.Key.alt)
            elif len(part) == 1:
                self._required_keys.add(part)
        
        self._pressed_keys = set()
        
        def on_press(key):
            try:
                # Handle modifier keys (both left and right versions)
                if key in [keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r]:
                    self._pressed_keys.add(keyboard.Key.ctrl)
                elif key in [keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r]:
                    self._pressed_keys.add(keyboard.Key.shift)
                elif key in [keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r]:
                    self._pressed_keys.add(keyboard.Key.alt)
                # Handle character keys (letters and numbers)
                elif hasattr(key, 'char') and key.char and key.char.isprintable():
                    char_key = key.char.lower()  # Always convert to lowercase
                    if char_key.isalnum():  # Only letters and numbers
                        self._pressed_keys.add(char_key)
                
                # Check if all required keys are pressed
                if self._required_keys.issubset(self._pressed_keys):
                    # Use QTimer to call create_note from main thread
                    from PyQt6.QtCore import QTimer
                    QTimer.singleShot(0, self.create_note)
                    
            except Exception as e:
                pass
        
        def on_release(key):
            try:
                # Remove released keys (handle both left and right versions)
                if key in [keyboard.Key.ctrl, keyboard.Key.ctrl_l, keyboard.Key.ctrl_r]:
                    self._pressed_keys.discard(keyboard.Key.ctrl)
                elif key in [keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r]:
                    self._pressed_keys.discard(keyboard.Key.shift)
                elif key in [keyboard.Key.alt, keyboard.Key.alt_l, keyboard.Key.alt_r]:
                    self._pressed_keys.discard(keyboard.Key.alt)
                elif hasattr(key, 'char') and key.char and key.char.isprintable():
                    self._pressed_keys.discard(key.char.lower())
            except Exception as e:
                pass
        
        self.hotkey_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        threading.Thread(target=self.hotkey_listener.start, daemon=True).start()

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
                return False
            try:
                # Handle character keys (letters and numbers only)
                if hasattr(key, 'char') and key.char and key.char.isprintable():
                    char_key = key.char.lower()
                    if char_key.isalnum():  # Only letters and numbers
                        self.setText(char_key)
                        self.current_hotkey = char_key
                        self.stop_recording()
                        return False
                
            except Exception:
                pass
        
        def on_release(key):
            pass  # We don't need to handle releases for single key detection
        
        self.hotkey_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
        threading.Thread(target=self.hotkey_listener.start, daemon=True).start()
        
    def stop_recording(self):
        self.recording = False
        if self.hotkey_listener:
            self.hotkey_listener.stop()
            self.hotkey_listener = None
        
    def get_hotkey(self):
        return self.current_hotkey

# Settings Dialog
class SettingsDialog(QDialog):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.setWindowTitle('Settings')
        self.setFixedSize(400, 320)  # Increased height for new option
        self.settings = settings
        layout = QVBoxLayout(self)
        layout.setSpacing(10)  # Add spacing between elements
        layout.setContentsMargins(20, 20, 20, 20)  # Add margins
        
        # Launch on startup
        self.startup_cb = QCheckBox('Launch on system startup')
        self.startup_cb.setChecked(settings['launch_on_startup'])
        layout.addWidget(self.startup_cb)
        
        # Always on top
        self.ontop_cb = QCheckBox('Always on top for all notes')
        self.ontop_cb.setChecked(settings['always_on_top'])
        layout.addWidget(self.ontop_cb)
        
        # Reopen notes
        self.reopen_cb = QCheckBox('Reopen notes on startup')
        self.reopen_cb.setChecked(settings['reopen_notes'])
        layout.addWidget(self.reopen_cb)
        
        # Add some spacing before encryption section
        layout.addSpacing(10)
        
        # Encryption settings
        self.encrypt_cb = QCheckBox('Encrypt notes')
        self.encrypt_cb.setChecked(settings['encrypt_notes'])
        self.encrypt_cb.toggled.connect(self._on_encryption_toggled)
        layout.addWidget(self.encrypt_cb)

        # Encryption password management
        password_layout = QHBoxLayout()
        self.password_btn = QPushButton('Set Encryption Password')
        self.password_btn.setFixedHeight(30)  # Increase button height
        self.password_btn.clicked.connect(self._set_encryption_password)
        password_layout.addWidget(self.password_btn)
        
        # Show password status
        self.password_status = QLabel('No password set')
        if get_password_from_credential_manager():
            self.password_status.setText('Password is set')
        password_layout.addWidget(self.password_status)
        layout.addLayout(password_layout)
        
        # Add small spacing after password section
        layout.addSpacing(5)
        
        # Startup password prompt (only enabled when encryption is on)
        self.startup_prompt_cb = QCheckBox('Prompt for password on startup')
        self.startup_prompt_cb.setChecked(settings['prompt_password_on_startup'])
        self.startup_prompt_cb.setEnabled(settings['encrypt_notes'])
        layout.addWidget(self.startup_prompt_cb)
        
        # Add some spacing before hotkey section
        layout.addSpacing(10)
        
        # Hotkey section
        hotkey_label = QLabel('Global hotkey for new note:')
        layout.addWidget(hotkey_label)
        
        # Modifier checkboxes
        modifier_layout = QHBoxLayout()
        self.ctrl_cb = QCheckBox('Ctrl')
        self.shift_cb = QCheckBox('Shift')
        self.alt_cb = QCheckBox('Alt')
        
        # Parse existing hotkey to set checkboxes
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
        layout.addLayout(modifier_layout)
        
        # Key input
        key_layout = QHBoxLayout()
        key_label = QLabel('Key:')
        self.hotkey_edit = HotkeyInput()
        # Extract the key from existing hotkey
        key_parts = hotkey.split('+')
        for part in key_parts:
            if part not in ['ctrl', 'shift', 'alt'] and len(part) == 1:
                self.hotkey_edit.setText(part)
                self.hotkey_edit.current_hotkey = part
                break
        key_layout.addWidget(key_label)
        key_layout.addWidget(self.hotkey_edit)
        layout.addLayout(key_layout)
        
        # Add stretch to push buttons to bottom
        layout.addStretch()
        
        # Buttons
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
        layout.addLayout(btn_layout)
        self.setLayout(layout)

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
        return {
            'launch_on_startup': self.startup_cb.isChecked(),
            'always_on_top': self.ontop_cb.isChecked(),
            'hotkey': hotkey,
            'reopen_notes': self.reopen_cb.isChecked(),
            'encrypt_notes': self.encrypt_cb.isChecked(),
            'prompt_password_on_startup': self.startup_prompt_cb.isChecked(),
        }

if __name__ == '__main__':
    app = StickyNotesApp(sys.argv)
    sys.exit(app.exec()) 
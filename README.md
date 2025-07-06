# StickyPosts

A lightweight, feature-rich sticky note application for Windows 11, built with PyQt6.

## ✨ Features

### **Core Functionality**
- 🟡 Frameless, resizable sticky notes with yellow background
- 📌 Individual pin buttons for each note (stay on top independently)
- 🎯 Drag and resize functionality with visual feedback
- ➕ Quick add new notes with the + button
- ❌ Easy note deletion with the ✕ button

### **System Integration**
- 🖥️ System tray icon with Settings and Exit options
- 🔧 Comprehensive settings dialog
- 🚀 Launch on startup option (creates Windows shortcut)
- ⌨️ Global hotkey support (default: Ctrl+Shift+S)
- 🔒 Always-on-top toggle for all notes

### **Data Management**
- 💾 Automatic note persistence (save/load on startup)
- 🔐 Optional AES-256 encryption with password protection
- 🔑 Windows Credential Manager integration for secure password storage
- ⚡ Auto-save functionality (saves as you type)
- 📁 Compact JSON storage format

### **Performance & Optimization**
- 🧹 Automatic memory cleanup every 5 minutes
- 📏 Text length limits to prevent excessive memory usage
- 🎯 Note count limits (max 50 notes) for optimal performance
- ⚡ Optimized auto-save timing (3-second delay)
- 💾 Compact file storage (30-50% smaller files)

## 🚀 Setup & Run

### **1. Create and activate virtual environment:**
```powershell
python -m venv venv
.\venv\Scripts\activate
```

### **2. Install dependencies:**
```powershell
pip install -r requirements.txt
```

### **3. Run the app:**
```powershell
python stickyposts.py
```

## ⚙️ Settings

### **General Settings**
- **Launch on startup**: Creates shortcut in Windows Startup folder
- **Always on top**: Makes all notes stay above other windows
- **Reopen notes**: Automatically loads saved notes on startup
- **Global hotkey**: Customizable keyboard shortcut for new notes

### **Encryption Settings**
- **Encrypt notes**: Enable AES-256 encryption for note data
- **Set encryption password**: Securely stored in Windows Credential Manager
- **Prompt for password on startup**: Optional startup password verification

### **Hotkey Configuration**
- **Modifiers**: Ctrl, Shift, Alt (any combination)
- **Key**: Any alphanumeric key
- **Example**: Ctrl+Shift+S, Alt+N, etc.

## 🔐 Encryption Features

### **Security**
- **AES-256 encryption** with PBKDF2 key derivation
- **Salt-based encryption** for enhanced security
- **Windows Credential Manager** for password storage
- **No plain text passwords** stored anywhere

### **Usage**
1. Enable encryption in Settings
2. Set a password (stored securely in Windows)
3. Notes are automatically encrypted/decrypted
4. Password can be changed or removed anytime

## 📌 Pin Functionality

### **Individual Note Control**
- **Pin button**: 📌 on each note (left side)
- **Visual feedback**: Yellow background when pinned
- **Independent control**: Each note can be pinned/unpinned separately
- **Persistent**: Pin state is saved and restored

### **Always-on-Top Logic**
- Notes stay on top if either:
  - Global "Always on top" setting is enabled, OR
  - Individual note is pinned

## 💾 Data Storage

### **Files Created**
- `stickyposts_settings.json`: Application settings
- `stickyposts.json`: Note data (encrypted if enabled)
- `requirements.txt`: Python dependencies

### **Storage Optimization**
- **Compact JSON format**: 30-50% smaller files
- **Text truncation**: Long notes automatically truncated
- **Note limits**: Maximum 50 notes for optimal performance
- **Auto-cleanup**: Removes deleted notes automatically

## 🎯 Performance

### **Resource Usage**
- **Base RAM**: ~15-25 MB
- **Per note**: ~2-5 MB (depending on text length)
- **Storage**: ~1-10 KB per note
- **Cleanup**: Automatic every 5 minutes

### **Optimization Features**
- **Memory management**: Automatic garbage collection
- **I/O optimization**: Reduced auto-save frequency
- **Text limits**: 10,000 characters per note
- **Note limits**: Maximum 50 notes in memory

## 🔧 Troubleshooting

### **Common Issues**
- **Virtual environment**: Make sure to activate `venv` before running
- **Dependencies**: Install all requirements with `pip install -r requirements.txt`
- **Startup issues**: Check Windows Startup folder for shortcut
- **Encryption**: Verify password in Windows Credential Manager

## 📋 Requirements

- **OS**: Windows 11 (or Windows 10)
- **Python**: 3.8 or higher
- **Dependencies**: See `[requirements.txt](requirements.txt)`

## 🔄 Updates

### **Latest Features**
- ✅ Individual note pinning
- ✅ AES-256 encryption with Windows Credential Manager
- ✅ Note persistence and auto-save
- ✅ Performance optimizations
- ✅ Compact storage format
- ✅ Memory cleanup and management

For detailed optimization information, see [OPTIMIZATION.md](OPTIMIZATION.md). 

# rclone_tui

Dual-panel terminal file manager for rclone transfers. Run with root privileges via launcher to access the full filesystem from `/`.

Features:
- Two columns with borders, path headers, legend of controls
- Arrow keys navigation; Enter to open; Backspace to go up
- Space to select, c/m to choose copy/move
- p/l to toggle progress vs log output
- a/d to run attached vs detached
- Status bar shows selected count and total size (with caching)
- Size footer per panel with "calculating..." for directories
- Colors for copy/move, progress/log, mode, directories/files
- Active cursor highlight
- Symbols: `/` for directories, `*` for executables

## Install
```bash
./install.sh

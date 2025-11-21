import curses
import os
import subprocess
import threading

# Cache for directory sizes
size_cache = {}

# Default logfile for detached mode
LOGFILE_DEFAULT = "/var/log/rclone_tui.log"

# Output buffer for scrolling
output_buffer = []
scroll_offset = 0

def human_size(num_bytes):
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num_bytes < 1024.0:
            return f"{num_bytes:.1f} {unit}"
        num_bytes /= 1024.0
    return f"{num_bytes:.1f} PB"

def calc_size(path):
    total = 0
    for root, dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except Exception:
                pass
    return total

class FilePanel:
    def __init__(self, path="/"):
        self.path = path
        self.files = []
        self.cursor = 0
        self.selected = set()
        self.scroll_offset = 0
        self.refresh()

    def refresh(self):
        try:
            entries = os.listdir(self.path)
        except Exception:
            entries = []
        entries = sorted(
            entries,
            key=lambda n: (0 if os.path.isdir(os.path.join(self.path, n)) else 1, n.lower())
        )
        self.files = [".."] + entries
        self.cursor = max(0, min(self.cursor, len(self.files) - 1))
        self.scroll_offset = 0

    def move_cursor(self, delta, max_rows=None):
        self.cursor = max(0, min(len(self.files) - 1, self.cursor + delta))
        if max_rows is not None:
            if self.cursor < self.scroll_offset:
                self.scroll_offset = self.cursor
            elif self.cursor >= self.scroll_offset + max_rows:
                self.scroll_offset = self.cursor - max_rows + 1

    def enter(self):
        choice = self.files[self.cursor]
        if choice == "..":
            self.path = os.path.dirname(self.path) or "/"
        else:
            new_path = os.path.join(self.path, choice)
            if os.path.isdir(new_path):
                self.path = new_path
        self.refresh()

    def toggle_select(self):
        choice = self.files[self.cursor]
        if choice == "..":
            return
        full = os.path.join(self.path, choice)
        if full in self.selected:
            self.selected.remove(full)
        else:
            self.selected.add(full)

    def current_item_size(self):
        choice = self.files[self.cursor]
        if choice == "..":
            return None
        full = os.path.join(self.path, choice)
        if os.path.isfile(full):
            try:
                return os.path.getsize(full)
            except Exception:
                return None
        elif os.path.isdir(full):
            if full in size_cache and size_cache[full] is not None:
                return size_cache[full]
            else:
                size_cache[full] = None
                threading.Thread(
                    target=lambda p=full: size_cache.update({p: calc_size(p)}),
                    daemon=True
                ).start()
                return None
        return None

def aggregate_selection_size(src_panel, dst_panel):
    total = 0
    pending = False
    all_selected = list(src_panel.selected) + list(dst_panel.selected)
    for path in all_selected:
        if os.path.isfile(path):
            try:
                total += os.path.getsize(path)
            except Exception:
                pass
        elif os.path.isdir(path):
            if path in size_cache and size_cache[path] is not None:
                total += size_cache[path]
            else:
                pending = True
    return total, pending, len(all_selected)

# Output helpers
def append_output(line, output_win):
    global output_buffer
    output_buffer.append(line.rstrip("\n"))
    redraw_output(output_win)

def redraw_output(output_win):
    global output_buffer, scroll_offset
    output_win.clear()
    output_win.box()
    max_y, max_x = output_win.getmaxyx()
    visible_height = max_y - 2
    start = max(0, len(output_buffer) - visible_height - scroll_offset)
    end = len(output_buffer) - scroll_offset
    for i, line in enumerate(output_buffer[start:end]):
        try:
            output_win.addstr(1 + i, 1, line[:max_x - 2])
        except curses.error:
            pass
    output_win.refresh()

def draw_panel(win, panel, title, active, height, width):
    win.box()
    path_str = f"{title}: {panel.path}"
    try:
        win.addstr(0, 2, path_str[:width - 4])
    except curses.error:
        pass

    max_rows = height - 4
    visible_files = panel.files[panel.scroll_offset:panel.scroll_offset + max_rows]

    for i, f in enumerate(visible_files):
        full = os.path.join(panel.path, f)
        sel = "*" if full in panel.selected else " "

        if os.path.isdir(full) or f == "..":
            display_name = f + "/"
            color = curses.color_pair(7)
        elif os.path.isfile(full) and os.access(full, os.X_OK):
            display_name = f + "*"
            color = curses.color_pair(8)
        else:
            display_name = f
            color = curses.color_pair(8)

        display = f"{sel} {display_name}"

        if panel.cursor == panel.scroll_offset + i and active is panel:
            try:
                win.addstr(1 + i, 1, display[:width - 2], curses.color_pair(6) | curses.A_BOLD)
            except curses.error:
                pass
        else:
            try:
                win.addstr(1 + i, 1, display[:width - 2], color)
            except curses.error:
                pass

    size_val = panel.current_item_size()
    size_str = "Size: calculating..." if size_val is None else f"Size: {human_size(size_val)}"
    try:
        win.addstr(height - 2, 2, size_str[:width - 4])
    except curses.error:
        pass

def render_legend(legend_win, width):
    items = [
        ("↑↓", "Navigate"), ("←→", "Switch"), ("Enter", "Open"), ("Backspace", "Up"),
        ("Space", "Select"), ("c", "Copy"), ("m", "Move"), ("p", "Progress"),
        ("l", "Log"), ("a", "Attached"), ("d", "Detached"), ("r", "Run"),
        ("PgUp", "Scroll Up"), ("PgDn", "Scroll Down"), ("q", "Quit"),
    ]
    legend_win.clear()
    x = 0
    def put(text, attr):
        nonlocal x
        if x >= width - 1:
            return
        chunk = text[:max(0, width - 1 - x)]
        try:
            legend_win.addstr(0, x, chunk, attr)
        except curses.error:
            pass
        x += len(chunk)

    put("Controls: ", curses.color_pair(5) | curses.A_BOLD)
    sep = " | "
    for idx, (key, action) in enumerate(items):
        put(key, curses.color_pair(5) | curses.A_BOLD)
        put(";", curses.color_pair(5))
        put(action, curses.color_pair(3))
        if idx != len(items) - 1:
            put(sep, curses.color_pair(5))
    legend_win.refresh()

def run_rclone(operation, src_files, dst_path, mode, output_type, output_win):
    if not src_files:
        append_output("No items selected.", output_win)
        return

    for src in src_files:
        # Option 2: preserve directory name when copying
        dst = dst_path
        if os.path.isdir(src):
            dst = os.path.join(dst_path, os.path.basename(src))

        cmd = ["rclone", operation, src, dst]
        if output_type == "progress":
            cmd.append("-P")
        elif output_type == "log":
            cmd.append("-vv")

        if mode == "attached":
            try:
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                for line in process.stdout:
                    append_output(line, output_win)
                rc = process.wait()
                append_output(f"Completed {operation} {src} -> {dst} (exit {rc})", output_win)
            except FileNotFoundError:
                append_output("rclone not found. Install rclone and ensure it is on PATH.", output_win)
        else:
            logfile = LOGFILE_DEFAULT
            try:
                with open(logfile, "a") as f:
                    subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT)
                append_output(f"Detached {operation} job started for {src}. Logs: {logfile}", output_win)
            except FileNotFoundError:
                append_output("rclone not found. Install rclone and ensure it is on PATH.", output_win)
            except PermissionError:
                append_output(f"Cannot write log file: {logfile}", output_win)

def main(stdscr):
    global scroll_offset, output_buffer
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()

    # Color pairs
    curses.init_pair(1, curses.COLOR_GREEN, -1)    # copy
    curses.init_pair(2, curses.COLOR_RED, -1)      # move
    curses.init_pair(3, curses.COLOR_CYAN, -1)     # progress/log actions
    curses.init_pair(4, curses.COLOR_YELLOW, -1)   # mode
    curses.init_pair(5, curses.COLOR_WHITE, -1)    # base text / keys
    curses.init_pair(6, curses.COLOR_BLACK, curses.COLOR_WHITE)  # active highlight
    curses.init_pair(7, curses.COLOR_BLUE, -1)     # directories
    curses.init_pair(8, curses.COLOR_WHITE, -1)    # files/executables

    height, width = stdscr.getmaxyx()
    col_w = width // 2
    panel_h = max(10, height * 2 // 3)

    # Windows
    src_win = curses.newwin(panel_h, col_w, 0, 0)
    dst_win = curses.newwin(panel_h, col_w, 0, col_w)
    output_win = curses.newwin(height - panel_h - 2, width, panel_h, 0)
    legend_win = curses.newwin(1, width, height - 2, 0)
    status_win = curses.newwin(1, width, height - 1, 0)

    # Panels
    src_panel = FilePanel("/")
    dst_panel = FilePanel("/")
    active = src_panel

    # Modes
    operation, output_type, mode = "copy", "progress", "attached"

    while True:
        # Clear and draw panels
        src_win.clear(); dst_win.clear(); status_win.clear()
        draw_panel(src_win, src_panel, "Source", active, panel_h, col_w)
        draw_panel(dst_win, dst_panel, "Destination", active, panel_h, col_w)

        # Output window
        redraw_output(output_win)
        src_win.refresh(); dst_win.refresh()

        # Legend
        render_legend(legend_win, width)

        # Status bar aggregation
        total_size, pending, count = aggregate_selection_size(src_panel, dst_panel)
        size_str = "calculating..." if pending else human_size(total_size)

        # Status bar with colors
        try:
            status_win.addstr(0, 0, f"Selected: {count} | Total size: {size_str} | ", curses.color_pair(5))
            op_color = curses.color_pair(1) if operation == "copy" else curses.color_pair(2)
            status_win.addstr(f"Op: {operation.upper()} ", op_color)
            status_win.addstr(f"| Out: {output_type.upper()} ", curses.color_pair(3))
            status_win.addstr(f"| Mode: {mode.upper()}", curses.color_pair(4))
        except curses.error:
            pass
        status_win.refresh()

        # Input
        key = stdscr.getch()
        if key == ord("q"):
            break
        elif key == curses.KEY_UP:
            active.move_cursor(-1, panel_h - 4)
        elif key == curses.KEY_DOWN:
            active.move_cursor(1, panel_h - 4)
        elif key == curses.KEY_LEFT:
            active = src_panel
        elif key == curses.KEY_RIGHT:
            active = dst_panel
        elif key in (10, curses.KEY_ENTER):
            active.enter()
        elif key in (8, 127):  # Backspace/Delete
            active.path = os.path.dirname(active.path) or "/"
            active.refresh()
        elif key == ord(" "):
            active.toggle_select()
        elif key == ord("c"):
            operation = "copy"
        elif key == ord("m"):
            operation = "move"
        elif key == ord("p"):
            output_type = "progress"
        elif key == ord("l"):
            output_type = "log"
        elif key == ord("a"):
            mode = "attached"
        elif key == ord("d"):
            mode = "detached"
        elif key == curses.KEY_PPAGE:  # Page Up (output scroll)
            scroll_offset = min(scroll_offset + 1, len(output_buffer))
            redraw_output(output_win)
        elif key == curses.KEY_NPAGE:  # Page Down (output scroll)
            scroll_offset = max(scroll_offset - 1, 0)
            redraw_output(output_win)
        elif key == ord("r"):
            # Update status to show transfer starting
            total_size, pending, count = aggregate_selection_size(src_panel, dst_panel)
            status_msg = f"{operation.capitalize()}ing {count} items, {'calculating...' if pending else human_size(total_size)}"
            try:
                status_win.clear()
                status_win.addstr(0, 0, status_msg[:width - 1], op_color)
                status_win.refresh()
            except curses.error:
                pass
            run_rclone(operation, list(src_panel.selected), dst_panel.path, mode, output_type, output_win)

if __name__ == "__main__":
    curses.wrapper(main)


import curses
import os
import subprocess
import threading

# Global size cache to avoid recomputation
size_cache = {}

LOGFILE_DEFAULT = "/var/log/rclone_tui.log"

def human_size(num_bytes):
    for unit in ["B","KB","MB","GB","TB"]:
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
        self.refresh()

    def refresh(self):
        try:
            entries = os.listdir(self.path)
        except Exception:
            entries = []
        # Directories first, then files
        entries = sorted(
            entries,
            key=lambda n: (0 if os.path.isdir(os.path.join(self.path, n)) else 1, n.lower())
        )
        self.files = [".."] + entries
        self.cursor = max(0, min(self.cursor, len(self.files) - 1))

    def move_cursor(self, delta):
        self.cursor = max(0, min(len(self.files) - 1, self.cursor + delta))

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
                # Mark pending and compute in background
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

def draw_panel(win, panel, title, active, height, width):
    win.box()
    # Header with path
    path_str = f"{title}: {panel.path}"
    try:
        win.addstr(0, 2, path_str[:width - 4])
    except curses.error:
        pass

    max_rows = height - 4
    for i, f in enumerate(panel.files[:max_rows]):
        full = os.path.join(panel.path, f)
        sel = "*" if full in panel.selected else " "

        # Add suffixes and choose colors
        if os.path.isdir(full) or f == "..":
            display_name = f + "/"
            color = curses.color_pair(7)  # directory (blue)
        elif os.path.isfile(full) and os.access(full, os.X_OK):
            display_name = f + "*"
            color = curses.color_pair(8)  # executable/file (white)
        else:
            display_name = f
            color = curses.color_pair(8)  # file (white)

        display = f"{sel} {display_name}"

        if i == panel.cursor and active is panel:
            # Highlight active cursor line
            try:
                win.addstr(1 + i, 1, display[:width - 2], curses.color_pair(6) | curses.A_BOLD)
            except curses.error:
                pass
        else:
            try:
                win.addstr(1 + i, 1, display[:width - 2], color)
            except curses.error:
                pass

    # Footer with current item size
    size_val = panel.current_item_size()
    size_str = "Size: calculating..." if size_val is None else f"Size: {human_size(size_val)}"
    try:
        win.addstr(height - 2, 2, size_str[:width - 4])
    except curses.error:
        pass

def run_rclone(operation, src_files, dst_path, mode, output_type, output_win):
    if not src_files:
        output_win.addstr("No items selected.\n")
        output_win.refresh()
        return

    for src in src_files:
        cmd = ["rclone", operation, src, dst_path]
        if output_type == "progress":
            cmd.append("-P")
        elif output_type == "log":
            cmd.append("-vv")

        if mode == "attached":
            try:
                process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                for line in process.stdout:
                    try:
                        output_win.addstr(line)
                        output_win.refresh()
                    except curses.error:
                        pass
                rc = process.wait()
                output_win.addstr(f"Completed {operation} {src} -> {dst_path} (exit {rc})\n")
                output_win.refresh()
            except FileNotFoundError:
                output_win.addstr("rclone not found. Install rclone and ensure it is on PATH.\n")
                output_win.refresh()
        else:
            # Detached
            logfile = LOGFILE_DEFAULT
            try:
                with open(logfile, "a") as f:
                    subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT)
                output_win.addstr(f"Detached {operation} job started for {src}. Logs: {logfile}\n")
                output_win.refresh()
            except FileNotFoundError:
                output_win.addstr("rclone not found. Install rclone and ensure it is on PATH.\n")
                output_win.refresh()
            except PermissionError:
                output_win.addstr(f"Cannot write log file: {logfile}\n")
                output_win.refresh()

def main(stdscr):
    curses.curs_set(0)
    curses.start_color()
    curses.use_default_colors()

    # Color pairs
    curses.init_pair(1, curses.COLOR_GREEN, -1)   # copy
    curses.init_pair(2, curses.COLOR_RED, -1)     # move
    curses.init_pair(3, curses.COLOR_CYAN, -1)    # progress/log
    curses.init_pair(4, curses.COLOR_YELLOW, -1)  # attached/detached
    curses.init_pair(5, curses.COLOR_WHITE, -1)   # legend / base text
    curses.init_pair(6, curses.COLOR_BLACK, curses.COLOR_WHITE)  # active highlight
    curses.init_pair(7, curses.COLOR_BLUE, -1)    # directories
    curses.init_pair(8, curses.COLOR_WHITE, -1)   # files/executables

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
        src_win.clear(); dst_win.clear(); output_win.clear()
        legend_win.clear(); status_win.clear()

        draw_panel(src_win, src_panel, "Source", active, panel_h, col_w)
        draw_panel(dst_win, dst_panel, "Destination", active, panel_h, col_w)

        # Output window
        output_win.box()
        try:
            output_win.addstr(0, 2, " Output / Status ")
        except curses.error:
            pass
        output_win.refresh()
        src_win.refresh(); dst_win.refresh()

        # Legend line
        legend_str = (
            "Controls: ↑↓ Navigate | ←→ Switch | Enter Open | Backspace Up | Space Select | "
            "c Copy | m Move | p Progress | l Log | a Attached | d Detached | r Run | q Quit"
        )
        try:
            legend_win.addstr(0, 0, legend_str[:width - 1], curses.color_pair(5))
        except curses.error:
            pass
        legend_win.refresh()

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
            active.move_cursor(-1)
        elif key == curses.KEY_DOWN:
            active.move_cursor(1)
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


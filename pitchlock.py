"""
MLB Vision - PitchLock
Creative Module for MLB Vision / Helios II

Search and select MLB pitchers to automatically adjust your detection box
to the perfect release point for each pitcher.

Lineup Manager: Enter your batting lineup with player heights to auto-adjust
the strike zone per batter. Settings persist between sessions.

Compatible with MLB Vision v0.8.0+ and Helios II CV Python 3.11
"""

import json
import os
import sys
import threading
import tkinter as tk
from tkinter import ttk, messagebox
import urllib.request
import shutil
import traceback

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SCREEN_W = 1920
SCREEN_H = 1080

# ---------------------------------------------------------------------------
# Version (used by auto-updater)
# ---------------------------------------------------------------------------
__version__ = "1.1.0"

# Path resolution: robustly find pitchers_db.json across multiple locations
try:
    SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
except NameError:
    SCRIPT_DIR = os.getcwd()


def _find_db() -> str:
    """Search multiple locations for pitchers_db.json."""
    candidates = [
        os.path.join(SCRIPT_DIR, "pitchers_db.json"),
        os.path.join(os.getcwd(), "pitchers_db.json"),
        os.path.join(os.path.dirname(SCRIPT_DIR), "pitchers_db.json"),
        os.path.join(os.path.expanduser("~"), "pitchers_db.json"),
    ]
    # Check sys.argv[0] directory (where the launcher lives)
    if sys.argv and sys.argv[0]:
        candidates.append(
            os.path.join(os.path.dirname(os.path.abspath(sys.argv[0])),
                         "pitchers_db.json"))
    # Check common subfolders
    for sub in ("data", "config", "db", "assets", "resources"):
        candidates.append(os.path.join(SCRIPT_DIR, sub, "pitchers_db.json"))
        candidates.append(os.path.join(os.getcwd(), sub, "pitchers_db.json"))
    # Check sys.path entries
    for p in sys.path:
        if p and os.path.isdir(p):
            candidates.append(os.path.join(p, "pitchers_db.json"))
    # De-duplicate while preserving order
    seen = set()
    unique = []
    for c in candidates:
        c = os.path.normpath(c)
        if c not in seen:
            seen.add(c)
            unique.append(c)
    for c in unique:
        if os.path.isfile(c):
            return c
    return unique[0]  # return first candidate for error messaging


DB_PATH = _find_db()

# Color palette (dark baseball theme matching MLB Vision)
COLORS = {
    "bg_dark": "#0a0e17",
    "bg_panel": "#111827",
    "bg_card": "#1a2236",
    "bg_entry": "#1e293b",
    "bg_hover": "#253352",
    "bg_selected": "#0e3a6e",
    "accent_cyan": "#00e5ff",
    "accent_blue": "#1e90ff",
    "accent_gold": "#ffd700",
    "accent_red": "#ff3b3b",
    "accent_green": "#00e676",
    "text_primary": "#e8eaf6",
    "text_secondary": "#8892a8",
    "text_dim": "#4a5568",
    "border": "#2d3748",
    "border_accent": "#00e5ff",
    "scrollbar_bg": "#1a2236",
    "scrollbar_fg": "#3a4a6a",
}

# MLB team colors for accenting
TEAM_COLORS = {
    "NYY": "#003087", "BOS": "#BD3039", "TOR": "#134A8E", "TB": "#092C5C",
    "BAL": "#DF4601", "CLE": "#00385D", "MIN": "#002B5C", "CWS": "#27251F",
    "DET": "#0C2340", "KC": "#004687", "HOU": "#002D62", "LAA": "#BA0021",
    "SEA": "#0C2C56", "TEX": "#003278", "OAK": "#003831", "NYM": "#002D72",
    "PHI": "#E81828", "ATL": "#CE1141", "MIA": "#00A3E0", "WSH": "#AB0003",
    "CHC": "#0E3386", "STL": "#C41E3A", "MIL": "#FFC52F", "CIN": "#C6011F",
    "PIT": "#FDB827", "LAD": "#005A9C", "SF": "#FD5A1E", "SD": "#2F241D",
    "ARI": "#A71930", "COL": "#33006F", "FA": "#555555",
}

# ---------------------------------------------------------------------------
# Database Loader
# ---------------------------------------------------------------------------


def load_pitcher_database(path: str) -> list:
    """Load the pitcher database from JSON file."""
    # Re-search if the cached path doesn't exist
    if not os.path.isfile(path):
        path = _find_db()
    if not os.path.isfile(path):
        msg = (f"Pitcher database not found.\n"
               f"Searched:\n  Script dir: {SCRIPT_DIR}\n"
               f"  CWD: {os.getcwd()}\n\n"
               f"Place pitchers_db.json in the same folder as pitchlock.py.")
        print(f"[PitchLock] ERROR: {msg}", file=sys.stderr)
        try:
            messagebox.showerror("Database Error", msg)
        except Exception:
            pass
        return []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except Exception as exc:
        msg = f"Failed to read pitcher database:\n{exc}"
        print(f"[PitchLock] ERROR: {msg}", file=sys.stderr)
        try:
            messagebox.showerror("Database Error", msg)
        except Exception:
            pass
        return []
    # Handle multiple JSON formats
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("pitchers", "pitchers_db", "players", "data"):
            if key in data and isinstance(data[key], list):
                return data[key]
        # Try first list value in the dict
        for v in data.values():
            if isinstance(v, list) and v and isinstance(v[0], dict):
                return v
    return []


# ---------------------------------------------------------------------------
# Detection Box Calculator
# ---------------------------------------------------------------------------

class DetectionBoxCalculator:
    """Converts normalized release-point data to pixel coordinates for the
    detection box on a given screen resolution."""

    def __init__(self, screen_w: int = SCREEN_W, screen_h: int = SCREEN_H):
        self.screen_w = screen_w
        self.screen_h = screen_h

    def get_box(self, pitcher: dict) -> dict:
        """Return pixel coordinates for the detection box.

        Returns dict with keys: x, y, w, h, cx, cy
        where (x, y) is top-left corner and (cx, cy) is center.
        """
        cx = int(pitcher["release_x"] * self.screen_w)
        cy = int(pitcher["release_y"] * self.screen_h)
        w = int(pitcher["box_w"] * self.screen_w)
        h = int(pitcher["box_h"] * self.screen_h)
        x = cx - w // 2
        y = cy - h // 2
        return {"x": x, "y": y, "w": w, "h": h, "cx": cx, "cy": cy}

    def format_box(self, pitcher: dict) -> str:
        """Human-readable string of the detection box."""
        box = self.get_box(pitcher)
        return (f"X: {box['x']}  Y: {box['y']}  "
                f"W: {box['w']}  H: {box['h']}")


# ---------------------------------------------------------------------------
# Strike Zone Calculator
# ---------------------------------------------------------------------------

class StrikeZoneCalculator:
    """Calculates strike zone coordinates based on batter height.

    Uses a preset-based approach (no cv2 needed) - all data is stored as
    normalized coordinates that map to screen pixels. The zone is centered
    on home plate (screen center X). Only the vertical position/size
    changes based on batter height.
    """

    # Reference height for baseline zone (6'0" = 72 inches)
    BASE_HEIGHT = 72

    # Strike zone horizontal center (home plate, center of screen)
    SZ_CENTER_X = 0.500
    SZ_HALF_WIDTH = 0.044

    # Baseline zone Y coords for a 72" batter (normalized 0.0-1.0)
    BASE_SZ_TOP = 0.390
    BASE_SZ_BOTTOM = 0.555

    # Per-inch adjustment factors
    # Taller batters: zone top moves UP (lower Y value), bottom shifts slightly
    TOP_FACTOR = 0.0048
    BOTTOM_FACTOR = 0.0022

    def __init__(self, screen_w: int = SCREEN_W, screen_h: int = SCREEN_H):
        self.screen_w = screen_w
        self.screen_h = screen_h

    def get_zone(self, height_inches: int) -> dict:
        """Calculate strike zone coordinates for a batter of given height.

        Returns dict with normalized and pixel coordinates.
        """
        height_diff = height_inches - self.BASE_HEIGHT

        top_y = self.BASE_SZ_TOP - (height_diff * self.TOP_FACTOR)
        bottom_y = self.BASE_SZ_BOTTOM - (height_diff * self.BOTTOM_FACTOR)

        left_x = self.SZ_CENTER_X - self.SZ_HALF_WIDTH
        right_x = self.SZ_CENTER_X + self.SZ_HALF_WIDTH

        zone_h = bottom_y - top_y
        zone_w = right_x - left_x

        return {
            "top_y": round(top_y, 4),
            "bottom_y": round(bottom_y, 4),
            "left_x": round(left_x, 4),
            "right_x": round(right_x, 4),
            "zone_w": round(zone_w, 4),
            "zone_h": round(zone_h, 4),
            "top_px": int(top_y * self.screen_h),
            "bottom_px": int(bottom_y * self.screen_h),
            "left_px": int(left_x * self.screen_w),
            "right_px": int(right_x * self.screen_w),
            "width_px": int(zone_w * self.screen_w),
            "height_px": int(zone_h * self.screen_h),
            "center_x_px": int(self.SZ_CENTER_X * self.screen_w),
            "center_y_px": int(((top_y + bottom_y) / 2) * self.screen_h),
        }

    def format_zone(self, height_inches: int) -> str:
        """Human-readable strike zone string."""
        zone = self.get_zone(height_inches)
        return (f"Top: {zone['top_px']}  Bot: {zone['bottom_px']}  "
                f"W: {zone['width_px']}  H: {zone['height_px']}")


# ---------------------------------------------------------------------------
# State Manager - persist settings between sessions
# ---------------------------------------------------------------------------

class StateManager:
    """Saves and loads PitchLock state (lineup, active batter, last pitcher)
    so settings persist between sessions instead of resetting."""

    STATE_FILE = os.path.join(SCRIPT_DIR, "pitchlock_state.json")

    @classmethod
    def save(cls, state: dict):
        """Save current state to disk."""
        try:
            with open(cls.STATE_FILE, "w", encoding="utf-8") as fh:
                json.dump(state, fh, indent=2)
        except Exception:
            pass

    @classmethod
    def load(cls) -> dict:
        """Load saved state from disk. Returns empty dict if none exists."""
        if not os.path.isfile(cls.STATE_FILE):
            return {}
        try:
            with open(cls.STATE_FILE, "r", encoding="utf-8") as fh:
                return json.load(fh)
        except Exception:
            return {}


# ---------------------------------------------------------------------------
# Output Bridge - writes values that MLB Vision / Helios II can read
# ---------------------------------------------------------------------------

class OutputBridge:
    """Writes the current detection-box and strike-zone values to a shared
    file so the MLB_Vision.py CV script can pick them up at runtime."""

    OUTPUT_FILE = os.path.join(SCRIPT_DIR, "mlb_settings.json")

    @classmethod
    def write(cls, pitcher: dict, box: dict, batter: dict = None,
              strike_zone: dict = None):
        payload = {
            "pitcher_name": pitcher["name"],
            "team": pitcher["team"],
            "throws": pitcher["throws"],
            "arm_slot": pitcher["arm_slot"],
            "detection_box": {
                "x": box["x"],
                "y": box["y"],
                "width": box["w"],
                "height": box["h"],
                "center_x": box["cx"],
                "center_y": box["cy"],
            },
            "screen_resolution": {"w": SCREEN_W, "h": SCREEN_H},
        }

        # Add strike zone data if a batter is active
        if batter and strike_zone:
            payload["active_batter"] = {
                "name": batter["name"],
                "height_inches": batter["height_inches"],
                "lineup_position": batter.get("position", 0),
            }
            payload["strike_zone"] = {
                "top_y": strike_zone["top_px"],
                "bottom_y": strike_zone["bottom_px"],
                "left_x": strike_zone["left_px"],
                "right_x": strike_zone["right_px"],
                "width": strike_zone["width_px"],
                "height": strike_zone["height_px"],
                "center_x": strike_zone["center_x_px"],
                "center_y": strike_zone["center_y_px"],
                "normalized": {
                    "top": strike_zone["top_y"],
                    "bottom": strike_zone["bottom_y"],
                    "left": strike_zone["left_x"],
                    "right": strike_zone["right_x"],
                },
            }

        with open(cls.OUTPUT_FILE, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2)


# ---------------------------------------------------------------------------
# Lineup Manager Dialog
# ---------------------------------------------------------------------------

class LineupDialog(tk.Toplevel):
    """Popup dialog for managing the batting lineup."""

    def __init__(self, parent, lineup: list):
        super().__init__(parent)
        self.title("Manage Lineup")
        self.configure(bg=COLORS["bg_dark"])
        self.geometry("480x620")
        self.resizable(False, False)
        self.transient(parent)
        self.grab_set()

        self.lineup = [dict(b) for b in lineup]  # deep copy
        self.result = None

        self._build_ui()
        self._populate_slots()

        # Center on parent
        self.update_idletasks()
        px = parent.winfo_x() + (parent.winfo_width() - 480) // 2
        py = parent.winfo_y() + (parent.winfo_height() - 620) // 2
        self.geometry(f"+{px}+{py}")

    def _build_ui(self):
        # Header
        header = tk.Frame(self, bg=COLORS["bg_dark"])
        header.pack(fill="x", padx=16, pady=(12, 4))

        tk.Label(header, text="BATTING LINEUP",
                 font=("Segoe UI", 16, "bold"),
                 fg=COLORS["accent_cyan"],
                 bg=COLORS["bg_dark"]).pack(side="left")

        tk.Label(header, text="Set batter heights for auto strike zone",
                 font=("Segoe UI", 9),
                 fg=COLORS["text_secondary"],
                 bg=COLORS["bg_dark"]).pack(side="right")

        sep = tk.Frame(self, bg=COLORS["border_accent"], height=1)
        sep.pack(fill="x", padx=16, pady=(4, 8))

        # Lineup slots container
        self.slots_frame = tk.Frame(self, bg=COLORS["bg_dark"])
        self.slots_frame.pack(fill="both", expand=True, padx=16, pady=(0, 8))

        # Bottom buttons
        btn_frame = tk.Frame(self, bg=COLORS["bg_dark"])
        btn_frame.pack(fill="x", padx=16, pady=(0, 12))

        save_btn = tk.Label(
            btn_frame, text="  SAVE LINEUP  ",
            font=("Segoe UI", 11, "bold"),
            fg=COLORS["bg_dark"], bg=COLORS["accent_cyan"],
            padx=16, pady=8, cursor="hand2")
        save_btn.pack(side="left", padx=(0, 8))
        save_btn.bind("<Button-1>", self._on_save)
        save_btn.bind("<Enter>",
                      lambda e: save_btn.configure(bg=COLORS["accent_blue"]))
        save_btn.bind("<Leave>",
                      lambda e: save_btn.configure(bg=COLORS["accent_cyan"]))

        clear_btn = tk.Label(
            btn_frame, text="  CLEAR ALL  ",
            font=("Segoe UI", 11, "bold"),
            fg=COLORS["text_primary"], bg=COLORS["bg_card"],
            padx=16, pady=8, cursor="hand2")
        clear_btn.pack(side="left", padx=(0, 8))
        clear_btn.bind("<Button-1>", self._on_clear)
        clear_btn.bind("<Enter>",
                       lambda e: clear_btn.configure(bg=COLORS["bg_hover"]))
        clear_btn.bind("<Leave>",
                       lambda e: clear_btn.configure(bg=COLORS["bg_card"]))

        cancel_btn = tk.Label(
            btn_frame, text="  CANCEL  ",
            font=("Segoe UI", 11, "bold"),
            fg=COLORS["text_dim"], bg=COLORS["bg_card"],
            padx=16, pady=8, cursor="hand2")
        cancel_btn.pack(side="right")
        cancel_btn.bind("<Button-1>", self._on_cancel)

    def _populate_slots(self):
        for w in self.slots_frame.winfo_children():
            w.destroy()

        self.name_entries = []
        self.height_ft_vars = []
        self.height_in_vars = []

        for i in range(9):
            slot = tk.Frame(self.slots_frame, bg=COLORS["bg_card"])
            slot.pack(fill="x", pady=2)

            # Position number
            num_lbl = tk.Label(
                slot, text=f"#{i + 1}",
                font=("Segoe UI", 13, "bold"),
                fg=COLORS["accent_gold"], bg=COLORS["bg_card"],
                width=3)
            num_lbl.pack(side="left", padx=(8, 4), pady=6)

            # Name entry
            tk.Label(slot, text="Name:",
                     font=("Segoe UI", 9),
                     fg=COLORS["text_secondary"],
                     bg=COLORS["bg_card"]).pack(side="left", padx=(4, 2))

            name_var = tk.StringVar()
            name_entry = tk.Entry(
                slot, textvariable=name_var,
                font=("Segoe UI", 10), bg=COLORS["bg_entry"],
                fg=COLORS["text_primary"],
                insertbackground=COLORS["accent_cyan"],
                relief="flat", width=16)
            name_entry.pack(side="left", padx=(0, 8), ipady=3)
            self.name_entries.append(name_var)

            # Height (feet + inches)
            tk.Label(slot, text="Ht:",
                     font=("Segoe UI", 9),
                     fg=COLORS["text_secondary"],
                     bg=COLORS["bg_card"]).pack(side="left", padx=(4, 2))

            ft_var = tk.StringVar()
            ft_entry = tk.Entry(
                slot, textvariable=ft_var,
                font=("Segoe UI", 10), bg=COLORS["bg_entry"],
                fg=COLORS["text_primary"],
                insertbackground=COLORS["accent_cyan"],
                relief="flat", width=2, justify="center")
            ft_entry.pack(side="left", padx=(0, 1), ipady=3)

            tk.Label(slot, text="'",
                     font=("Segoe UI", 11, "bold"),
                     fg=COLORS["text_secondary"],
                     bg=COLORS["bg_card"]).pack(side="left")

            in_var = tk.StringVar()
            in_entry = tk.Entry(
                slot, textvariable=in_var,
                font=("Segoe UI", 10), bg=COLORS["bg_entry"],
                fg=COLORS["text_primary"],
                insertbackground=COLORS["accent_cyan"],
                relief="flat", width=2, justify="center")
            in_entry.pack(side="left", padx=(0, 1), ipady=3)

            tk.Label(slot, text='"',
                     font=("Segoe UI", 11, "bold"),
                     fg=COLORS["text_secondary"],
                     bg=COLORS["bg_card"]).pack(side="left")

            self.height_ft_vars.append(ft_var)
            self.height_in_vars.append(in_var)

            # Pre-fill from existing lineup
            if i < len(self.lineup):
                b = self.lineup[i]
                name_var.set(b.get("name", ""))
                h = b.get("height_inches", 0)
                if h > 0:
                    ft_var.set(str(h // 12))
                    in_var.set(str(h % 12))

    def _on_save(self, event=None):
        lineup = []
        for i in range(9):
            name = self.name_entries[i].get().strip()
            ft_str = self.height_ft_vars[i].get().strip()
            in_str = self.height_in_vars[i].get().strip()

            if not name:
                continue

            try:
                ft = int(ft_str) if ft_str else 0
                inches = int(in_str) if in_str else 0
                total_inches = ft * 12 + inches
            except ValueError:
                total_inches = 72  # default to 6'0"

            if total_inches < 60:
                total_inches = 72
            if total_inches > 84:
                total_inches = 84

            lineup.append({
                "name": name,
                "height_inches": total_inches,
                "position": i + 1,
            })

        self.result = lineup
        self.destroy()

    def _on_clear(self, event=None):
        for i in range(9):
            self.name_entries[i].set("")
            self.height_ft_vars[i].set("")
            self.height_in_vars[i].set("")

    def _on_cancel(self, event=None):
        self.result = None
        self.destroy()


# ---------------------------------------------------------------------------
# GUI Application
# ---------------------------------------------------------------------------

class PitchLockApp(tk.Tk):
    """Main application window - baseball themed dark GUI."""

    WIDTH = 860
    HEIGHT = 820

    def __init__(self):
        super().__init__()

        # Apply dark theme using THIS window as the master (no extra root)
        self._apply_dark_theme()

        self.title("MLB Vision - PitchLock")
        self.geometry(f"{self.WIDTH}x{self.HEIGHT}")
        self.configure(bg=COLORS["bg_dark"])
        self.resizable(False, False)

        # Try to set icon
        try:
            self.iconbitmap(default="")
        except Exception:
            pass

        # Data
        self.pitchers = load_pitcher_database(DB_PATH)
        self.calculator = DetectionBoxCalculator()
        self.sz_calculator = StrikeZoneCalculator()
        self.selected_pitcher = None
        self.filtered_pitchers = list(self.pitchers)

        # Lineup data
        self.lineup = []
        self.active_batter_index = -1

        # Search variable
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_search)

        # Debounce timer for search
        self._search_after_id = None

        # Filter variables
        self.filter_hand = tk.StringVar(value="All")
        self.filter_slot = tk.StringVar(value="All")
        self.filter_team = tk.StringVar(value="All")

        self._build_ui()
        self._populate_list()

        # Load saved state
        self._load_state()

    def _apply_dark_theme(self):
        """Configure ttk styles using this window as master."""
        style = ttk.Style(self)
        style.theme_use("clam")

        style.configure("TCombobox",
                        fieldbackground=COLORS["bg_entry"],
                        background=COLORS["bg_card"],
                        foreground=COLORS["text_primary"],
                        arrowcolor=COLORS["accent_cyan"],
                        bordercolor=COLORS["border"],
                        lightcolor=COLORS["border"],
                        darkcolor=COLORS["border"])

        style.map("TCombobox",
                  fieldbackground=[("readonly", COLORS["bg_entry"])],
                  selectbackground=[("readonly", COLORS["bg_selected"])],
                  selectforeground=[("readonly", COLORS["text_primary"])])

        style.configure("Vertical.TScrollbar",
                        background=COLORS["scrollbar_fg"],
                        troughcolor=COLORS["scrollbar_bg"],
                        bordercolor=COLORS["scrollbar_bg"],
                        arrowcolor=COLORS["accent_cyan"])

    # -----------------------------------------------------------------------
    # UI Construction
    # -----------------------------------------------------------------------

    def _build_ui(self):
        # ---- Header ----
        header = tk.Frame(self, bg=COLORS["bg_dark"], height=70)
        header.pack(fill="x", padx=0, pady=0)
        header.pack_propagate(False)

        # Title with baseball diamond accent
        title_frame = tk.Frame(header, bg=COLORS["bg_dark"])
        title_frame.pack(side="left", padx=20, pady=10)

        diamond = tk.Canvas(title_frame, width=36, height=36,
                            bg=COLORS["bg_dark"], highlightthickness=0)
        diamond.pack(side="left", padx=(0, 10))
        self._draw_diamond(diamond)

        lbl_title = tk.Label(
            title_frame, text="PITCHLOCK",
            font=("Segoe UI", 20, "bold"), fg=COLORS["accent_cyan"],
            bg=COLORS["bg_dark"])
        lbl_title.pack(side="left")

        lbl_sub = tk.Label(
            title_frame, text="MLB",
            font=("Segoe UI", 11, "bold"), fg=COLORS["accent_gold"],
            bg=COLORS["bg_dark"])
        lbl_sub.pack(side="left", padx=(10, 0))

        # Version badge
        badge = tk.Label(
            header, text="BETA",
            font=("Segoe UI", 9, "bold"),
            fg=COLORS["bg_dark"], bg=COLORS["accent_gold"],
            padx=8, pady=2)
        badge.pack(side="right", padx=20, pady=22)

        # Separator
        sep = tk.Frame(self, bg=COLORS["border_accent"], height=2)
        sep.pack(fill="x")

        # ---- Body ----
        body = tk.Frame(self, bg=COLORS["bg_dark"])
        body.pack(fill="both", expand=True, padx=12, pady=8)

        # Left panel: search + list
        left = tk.Frame(body, bg=COLORS["bg_panel"], width=370)
        left.pack(side="left", fill="both", padx=(0, 6))
        left.pack_propagate(False)

        self._build_search_panel(left)
        self._build_filter_bar(left)
        self._build_pitcher_list(left)
        self._build_count_bar(left)

        # Right panel: batter bar + details + visualization
        right = tk.Frame(body, bg=COLORS["bg_panel"], width=460)
        right.pack(side="right", fill="both", expand=True)
        right.pack_propagate(False)

        self._build_batter_bar(right)
        self._build_detail_panel(right)
        self._build_visualization(right)
        self._build_action_buttons(right)

        # ---- Bottom Lineup Strip ----
        self._build_lineup_strip()

    # -- Header diamond icon --
    def _draw_diamond(self, canvas: tk.Canvas):
        cx, cy, r = 18, 18, 14
        pts = [cx, cy - r, cx + r, cy, cx, cy + r, cx - r, cy]
        canvas.create_polygon(pts, outline=COLORS["accent_cyan"],
                              fill=COLORS["bg_card"], width=2)
        canvas.create_oval(cx - 3, cy - 3, cx + 3, cy + 3,
                           fill=COLORS["accent_cyan"], outline="")

    # -- Search --
    def _build_search_panel(self, parent):
        frame = tk.Frame(parent, bg=COLORS["bg_panel"])
        frame.pack(fill="x", padx=10, pady=(10, 4))

        lbl = tk.Label(frame, text="SEARCH PITCHER",
                       font=("Segoe UI", 9, "bold"),
                       fg=COLORS["text_secondary"], bg=COLORS["bg_panel"])
        lbl.pack(anchor="w")

        entry_frame = tk.Frame(frame, bg=COLORS["border_accent"],
                               highlightthickness=0)
        entry_frame.pack(fill="x", pady=(4, 0))

        search_icon = tk.Label(entry_frame, text="\u2315",
                               font=("Segoe UI", 14),
                               fg=COLORS["accent_cyan"],
                               bg=COLORS["bg_entry"], padx=8)
        search_icon.pack(side="left")

        self.search_entry = tk.Entry(
            entry_frame, textvariable=self.search_var,
            font=("Segoe UI", 12), bg=COLORS["bg_entry"],
            fg=COLORS["text_primary"], insertbackground=COLORS["accent_cyan"],
            relief="flat", bd=0)
        self.search_entry.pack(side="left", fill="x", expand=True,
                               ipady=6, padx=(0, 4))

        clear_btn = tk.Label(
            entry_frame, text="\u2715", font=("Segoe UI", 11),
            fg=COLORS["text_dim"], bg=COLORS["bg_entry"],
            cursor="hand2", padx=8)
        clear_btn.pack(side="right")
        clear_btn.bind("<Button-1>", lambda e: self.search_var.set(""))

    # -- Filters --
    def _build_filter_bar(self, parent):
        frame = tk.Frame(parent, bg=COLORS["bg_panel"])
        frame.pack(fill="x", padx=10, pady=(2, 4))

        # Hand filter
        self._make_filter_combo(frame, "Hand:", self.filter_hand,
                                ["All", "R", "L"], width=5)
        # Slot filter
        slots = ["All", "Overhand", "Three-Quarter", "Low Three-Quarter",
                 "Sidearm", "Submarine"]
        self._make_filter_combo(frame, "Slot:", self.filter_slot,
                                slots, width=14)
        # Team filter
        teams = ["All"] + sorted(set(p["team"] for p in self.pitchers))
        self._make_filter_combo(frame, "Team:", self.filter_team,
                                teams, width=6)

    def _make_filter_combo(self, parent, label, var, values, width=8):
        f = tk.Frame(parent, bg=COLORS["bg_panel"])
        f.pack(side="left", padx=(0, 8))

        tk.Label(f, text=label, font=("Segoe UI", 8, "bold"),
                 fg=COLORS["text_dim"], bg=COLORS["bg_panel"]).pack(
            side="left", padx=(0, 2))

        combo = ttk.Combobox(
            f, textvariable=var, values=values, width=width,
            state="readonly", font=("Segoe UI", 9))
        combo.pack(side="left")
        combo.bind("<<ComboboxSelected>>", lambda e: self._apply_filters())

    # -- Pitcher List --
    def _build_pitcher_list(self, parent):
        list_frame = tk.Frame(parent, bg=COLORS["bg_card"])
        list_frame.pack(fill="both", expand=True, padx=10, pady=4)

        # Canvas + scrollbar for custom list
        self.list_canvas = tk.Canvas(list_frame, bg=COLORS["bg_card"],
                                     highlightthickness=0, bd=0)
        scrollbar = tk.Scrollbar(list_frame, orient="vertical",
                                 command=self.list_canvas.yview)
        self.list_inner = tk.Frame(self.list_canvas, bg=COLORS["bg_card"])

        self.list_inner.bind(
            "<Configure>",
            lambda e: self.list_canvas.configure(
                scrollregion=self.list_canvas.bbox("all")))
        self.list_canvas.create_window((0, 0), window=self.list_inner,
                                       anchor="nw")
        self.list_canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        self.list_canvas.pack(side="left", fill="both", expand=True)

        # Mouse wheel scrolling
        self.list_canvas.bind_all(
            "<MouseWheel>",
            lambda e: self.list_canvas.yview_scroll(
                -1 * (e.delta // 120), "units"))

    # -- Count bar --
    def _build_count_bar(self, parent):
        self.count_label = tk.Label(
            parent, text="", font=("Segoe UI", 9),
            fg=COLORS["text_dim"], bg=COLORS["bg_panel"])
        self.count_label.pack(fill="x", padx=10, pady=(0, 8))

    # -- Active Batter Bar (top of right panel) --
    def _build_batter_bar(self, parent):
        batter_frame = tk.Frame(parent, bg=COLORS["bg_card"])
        batter_frame.pack(fill="x", padx=10, pady=(10, 4))

        # Top label
        top_row = tk.Frame(batter_frame, bg=COLORS["bg_card"])
        top_row.pack(fill="x", padx=10, pady=(8, 2))

        tk.Label(top_row, text="ACTIVE BATTER",
                 font=("Segoe UI", 8, "bold"),
                 fg=COLORS["text_dim"],
                 bg=COLORS["bg_card"]).pack(side="left")

        # Manage lineup button
        manage_btn = tk.Label(
            top_row, text="MANAGE LINEUP",
            font=("Segoe UI", 8, "bold"),
            fg=COLORS["accent_cyan"],
            bg=COLORS["bg_card"], cursor="hand2")
        manage_btn.pack(side="right")
        manage_btn.bind("<Button-1>", self._on_manage_lineup)
        manage_btn.bind("<Enter>",
                        lambda e: manage_btn.configure(
                            fg=COLORS["accent_blue"]))
        manage_btn.bind("<Leave>",
                        lambda e: manage_btn.configure(
                            fg=COLORS["accent_cyan"]))

        # Batter info row with prev/next
        nav_row = tk.Frame(batter_frame, bg=COLORS["bg_card"])
        nav_row.pack(fill="x", padx=10, pady=(2, 8))

        # Prev button
        self.btn_prev = tk.Label(
            nav_row, text=" \u25C0 ",
            font=("Segoe UI", 12, "bold"),
            fg=COLORS["accent_cyan"], bg=COLORS["bg_entry"],
            cursor="hand2", padx=4)
        self.btn_prev.pack(side="left", padx=(0, 6))
        self.btn_prev.bind("<Button-1>", self._on_prev_batter)
        self.btn_prev.bind(
            "<Enter>",
            lambda e: self.btn_prev.configure(bg=COLORS["bg_hover"]))
        self.btn_prev.bind(
            "<Leave>",
            lambda e: self.btn_prev.configure(bg=COLORS["bg_entry"]))

        # Batter display
        batter_info = tk.Frame(nav_row, bg=COLORS["bg_entry"])
        batter_info.pack(side="left", fill="x", expand=True, ipady=4)

        self.lbl_batter_pos = tk.Label(
            batter_info, text="--",
            font=("Segoe UI", 11, "bold"),
            fg=COLORS["accent_gold"], bg=COLORS["bg_entry"])
        self.lbl_batter_pos.pack(side="left", padx=(8, 4))

        self.lbl_batter_name = tk.Label(
            batter_info, text="No lineup set",
            font=("Segoe UI", 11),
            fg=COLORS["text_primary"], bg=COLORS["bg_entry"])
        self.lbl_batter_name.pack(side="left", padx=(0, 8))

        self.lbl_batter_height = tk.Label(
            batter_info, text="",
            font=("Segoe UI", 10),
            fg=COLORS["text_secondary"], bg=COLORS["bg_entry"])
        self.lbl_batter_height.pack(side="left")

        self.lbl_batter_sz = tk.Label(
            batter_info, text="",
            font=("Segoe UI", 9),
            fg=COLORS["accent_green"], bg=COLORS["bg_entry"])
        self.lbl_batter_sz.pack(side="right", padx=(0, 8))

        # Next button
        self.btn_next = tk.Label(
            nav_row, text=" \u25B6 ",
            font=("Segoe UI", 12, "bold"),
            fg=COLORS["accent_cyan"], bg=COLORS["bg_entry"],
            cursor="hand2", padx=4)
        self.btn_next.pack(side="right", padx=(6, 0))
        self.btn_next.bind("<Button-1>", self._on_next_batter)
        self.btn_next.bind(
            "<Enter>",
            lambda e: self.btn_next.configure(bg=COLORS["bg_hover"]))
        self.btn_next.bind(
            "<Leave>",
            lambda e: self.btn_next.configure(bg=COLORS["bg_entry"]))

    # -- Detail Panel --
    def _build_detail_panel(self, parent):
        detail_frame = tk.Frame(parent, bg=COLORS["bg_card"])
        detail_frame.pack(fill="x", padx=10, pady=(4, 4))

        # Top: pitcher name + team
        top = tk.Frame(detail_frame, bg=COLORS["bg_card"])
        top.pack(fill="x", padx=12, pady=(12, 0))

        self.lbl_pitcher_name = tk.Label(
            top, text="Select a Pitcher",
            font=("Segoe UI", 20, "bold"), fg=COLORS["text_primary"],
            bg=COLORS["bg_card"], anchor="w")
        self.lbl_pitcher_name.pack(side="left")

        self.lbl_team_badge = tk.Label(
            top, text="", font=("Segoe UI", 10, "bold"),
            fg="#ffffff", bg=COLORS["bg_card"],
            padx=8, pady=2)
        self.lbl_team_badge.pack(side="right")

        # Separator
        tk.Frame(detail_frame, bg=COLORS["border"], height=1).pack(
            fill="x", padx=12, pady=8)

        # Stats grid
        stats_frame = tk.Frame(detail_frame, bg=COLORS["bg_card"])
        stats_frame.pack(fill="x", padx=12, pady=(0, 12))

        # Row 1
        r1 = tk.Frame(stats_frame, bg=COLORS["bg_card"])
        r1.pack(fill="x", pady=2)
        self.stat_throws = self._make_stat_field(r1, "THROWS")
        self.stat_slot = self._make_stat_field(r1, "ARM SLOT")
        self.stat_height = self._make_stat_field(r1, "HEIGHT")

        # Row 2
        r2 = tk.Frame(stats_frame, bg=COLORS["bg_card"])
        r2.pack(fill="x", pady=2)
        self.stat_release_x = self._make_stat_field(r2, "RELEASE X")
        self.stat_release_y = self._make_stat_field(r2, "RELEASE Y")
        self.stat_box_size = self._make_stat_field(r2, "BOX SIZE")

        # Notes
        notes_frame = tk.Frame(detail_frame, bg=COLORS["bg_card"])
        notes_frame.pack(fill="x", padx=12, pady=(0, 12))

        tk.Label(notes_frame, text="SCOUTING NOTES",
                 font=("Segoe UI", 8, "bold"),
                 fg=COLORS["text_dim"], bg=COLORS["bg_card"]).pack(
            anchor="w")
        self.lbl_notes = tk.Label(
            notes_frame, text="--",
            font=("Segoe UI", 10, "italic"),
            fg=COLORS["text_secondary"], bg=COLORS["bg_card"],
            anchor="w", wraplength=400, justify="left")
        self.lbl_notes.pack(anchor="w", pady=(2, 0))

    def _make_stat_field(self, parent, label):
        frame = tk.Frame(parent, bg=COLORS["bg_card"])
        frame.pack(side="left", expand=True, fill="x", padx=4)

        tk.Label(frame, text=label, font=("Segoe UI", 8, "bold"),
                 fg=COLORS["text_dim"], bg=COLORS["bg_card"]).pack(
            anchor="w")
        val = tk.Label(frame, text="--", font=("Segoe UI", 12, "bold"),
                       fg=COLORS["accent_cyan"], bg=COLORS["bg_card"],
                       anchor="w")
        val.pack(anchor="w")
        return val

    # -- Visualization --
    def _build_visualization(self, parent):
        viz_label = tk.Label(
            parent, text="RELEASE POINT PREVIEW",
            font=("Segoe UI", 9, "bold"),
            fg=COLORS["text_secondary"], bg=COLORS["bg_panel"])
        viz_label.pack(padx=10, pady=(8, 2), anchor="w")

        viz_frame = tk.Frame(parent, bg=COLORS["bg_card"])
        viz_frame.pack(fill="both", expand=True, padx=10, pady=(0, 4))

        # Canvas representing the screen
        self.viz_canvas = tk.Canvas(
            viz_frame, bg="#0d1117", highlightthickness=1,
            highlightbackground=COLORS["border"])
        self.viz_canvas.pack(fill="both", expand=True, padx=8, pady=8)

        self.viz_canvas.bind("<Configure>", self._on_viz_resize)

    # -- Action Buttons --
    def _build_action_buttons(self, parent):
        btn_frame = tk.Frame(parent, bg=COLORS["bg_panel"])
        btn_frame.pack(fill="x", padx=10, pady=(0, 10))

        self.btn_apply = tk.Label(
            btn_frame, text="  APPLY PITCHLOCK  ",
            font=("Segoe UI", 11, "bold"),
            fg=COLORS["bg_dark"], bg=COLORS["accent_cyan"],
            padx=16, pady=8, cursor="hand2")
        self.btn_apply.pack(side="left", padx=(0, 8))
        self.btn_apply.bind("<Button-1>", self._on_apply)
        self.btn_apply.bind("<Enter>",
                            lambda e: self.btn_apply.configure(
                                bg=COLORS["accent_blue"]))
        self.btn_apply.bind("<Leave>",
                            lambda e: self.btn_apply.configure(
                                bg=COLORS["accent_cyan"]))

        self.btn_copy = tk.Label(
            btn_frame, text="  COPY COORDS  ",
            font=("Segoe UI", 11, "bold"),
            fg=COLORS["text_primary"], bg=COLORS["bg_card"],
            padx=16, pady=8, cursor="hand2")
        self.btn_copy.pack(side="left", padx=(0, 8))
        self.btn_copy.bind("<Button-1>", self._on_copy)
        self.btn_copy.bind(
            "<Enter>",
            lambda e: self.btn_copy.configure(bg=COLORS["bg_hover"]))
        self.btn_copy.bind(
            "<Leave>",
            lambda e: self.btn_copy.configure(bg=COLORS["bg_card"]))

        # Status label
        self.lbl_status = tk.Label(
            btn_frame, text="", font=("Segoe UI", 9),
            fg=COLORS["accent_green"], bg=COLORS["bg_panel"])
        self.lbl_status.pack(side="right", padx=8)

    # -- Bottom Lineup Strip --
    def _build_lineup_strip(self):
        """Build the horizontal lineup strip at the bottom of the window."""
        strip_outer = tk.Frame(self, bg=COLORS["bg_dark"])
        strip_outer.pack(fill="x", padx=12, pady=(0, 8))

        # Label
        top_bar = tk.Frame(strip_outer, bg=COLORS["bg_dark"])
        top_bar.pack(fill="x")

        tk.Label(top_bar, text="LINEUP",
                 font=("Segoe UI", 8, "bold"),
                 fg=COLORS["text_dim"],
                 bg=COLORS["bg_dark"]).pack(side="left", padx=(4, 0))

        self.lbl_lineup_info = tk.Label(
            top_bar, text="Click MANAGE LINEUP to set up batters",
            font=("Segoe UI", 8),
            fg=COLORS["text_dim"],
            bg=COLORS["bg_dark"])
        self.lbl_lineup_info.pack(side="right", padx=(0, 4))

        # Strip with 9 slots
        self.lineup_strip = tk.Frame(strip_outer, bg=COLORS["bg_card"])
        self.lineup_strip.pack(fill="x", pady=(2, 0))

        self.lineup_slot_labels = []
        for i in range(9):
            slot = tk.Frame(self.lineup_strip, bg=COLORS["bg_card"],
                            cursor="hand2")
            slot.pack(side="left", fill="both", expand=True, padx=1, pady=2)

            num_lbl = tk.Label(
                slot, text=f"#{i + 1}",
                font=("Segoe UI", 8, "bold"),
                fg=COLORS["text_dim"], bg=COLORS["bg_card"])
            num_lbl.pack(pady=(2, 0))

            name_lbl = tk.Label(
                slot, text="--",
                font=("Segoe UI", 8),
                fg=COLORS["text_secondary"], bg=COLORS["bg_card"])
            name_lbl.pack()

            ht_lbl = tk.Label(
                slot, text="",
                font=("Segoe UI", 7),
                fg=COLORS["text_dim"], bg=COLORS["bg_card"])
            ht_lbl.pack(pady=(0, 2))

            self.lineup_slot_labels.append({
                "frame": slot,
                "num": num_lbl,
                "name": name_lbl,
                "height": ht_lbl,
            })

            # Click to select this batter
            for w in [slot, num_lbl, name_lbl, ht_lbl]:
                w.bind("<Button-1>",
                       lambda e, idx=i: self._on_click_lineup_slot(idx))

    # -----------------------------------------------------------------------
    # List Population
    # -----------------------------------------------------------------------

    def _populate_list(self):
        # Clear
        for w in self.list_inner.winfo_children():
            w.destroy()

        for idx, p in enumerate(self.filtered_pitchers):
            self._make_list_item(p, idx)

        self.count_label.configure(
            text=f"{len(self.filtered_pitchers)} pitcher"
                 f"{'s' if len(self.filtered_pitchers) != 1 else ''} found")

        # Force canvas scroll region update
        self.list_inner.update_idletasks()
        self.list_canvas.configure(
            scrollregion=self.list_canvas.bbox("all") or (0, 0, 0, 0))
        self.list_canvas.yview_moveto(0)

    def _make_list_item(self, pitcher: dict, idx: int):
        team = pitcher["team"]
        team_color = TEAM_COLORS.get(team, "#555555")

        item = tk.Frame(self.list_inner, bg=COLORS["bg_card"],
                        cursor="hand2")
        item.pack(fill="x", padx=4, pady=2)

        # Team color stripe
        stripe = tk.Frame(item, bg=team_color, width=4)
        stripe.pack(side="left", fill="y")

        # Content
        content = tk.Frame(item, bg=COLORS["bg_card"])
        content.pack(side="left", fill="x", expand=True, padx=8, pady=6)

        name_lbl = tk.Label(
            content, text=pitcher["name"],
            font=("Segoe UI", 11, "bold"),
            fg=COLORS["text_primary"], bg=COLORS["bg_card"],
            anchor="w")
        name_lbl.pack(anchor="w")

        info_text = (f"{pitcher['team']}  |  {pitcher['throws']}HP  |  "
                     f"{pitcher['arm_slot']}")
        info_lbl = tk.Label(
            content, text=info_text,
            font=("Segoe UI", 8),
            fg=COLORS["text_secondary"], bg=COLORS["bg_card"],
            anchor="w")
        info_lbl.pack(anchor="w")

        # Arrow indicator
        arrow = tk.Label(item, text="\u25B6", font=("Segoe UI", 9),
                         fg=COLORS["text_dim"], bg=COLORS["bg_card"],
                         padx=8)
        arrow.pack(side="right")

        # Bind hover + click to all children
        for widget in [item, stripe, content, name_lbl, info_lbl, arrow]:
            widget.bind("<Button-1>",
                        lambda e, p=pitcher: self._on_select_pitcher(p))
            widget.bind("<Enter>",
                        lambda e, f=item: self._on_item_enter(f))
            widget.bind("<Leave>",
                        lambda e, f=item: self._on_item_leave(f))

    def _on_item_enter(self, frame):
        for w in self._get_all_children(frame):
            try:
                w.configure(bg=COLORS["bg_hover"])
            except tk.TclError:
                pass

    def _on_item_leave(self, frame):
        bg = COLORS["bg_selected"] if (
            self.selected_pitcher and
            frame.winfo_children() and
            any(isinstance(w, tk.Label) and
                w.cget("text") == self.selected_pitcher.get("name", "")
                for w in self._get_all_children(frame))
        ) else COLORS["bg_card"]

        for w in self._get_all_children(frame):
            try:
                if not isinstance(w, tk.Frame) or w.cget("bg") not in TEAM_COLORS.values():
                    w.configure(bg=bg)
            except tk.TclError:
                pass

    def _get_all_children(self, widget):
        """Recursively get all child widgets."""
        result = [widget]
        for child in widget.winfo_children():
            result.extend(self._get_all_children(child))
        return result

    # -----------------------------------------------------------------------
    # Event Handlers
    # -----------------------------------------------------------------------

    def _on_search(self, *args):
        # Debounce: cancel previous pending search, schedule new one
        if self._search_after_id is not None:
            self.after_cancel(self._search_after_id)
        self._search_after_id = self.after(150, self._apply_filters)

    def _apply_filters(self):
        query = self.search_var.get().strip().lower()
        hand = self.filter_hand.get()
        slot = self.filter_slot.get()
        team = self.filter_team.get()

        results = []
        for p in self.pitchers:
            if query and query not in p["name"].lower():
                continue
            if hand != "All" and p["throws"] != hand:
                continue
            if slot != "All" and p["arm_slot"] != slot:
                continue
            if team != "All" and p["team"] != team:
                continue
            results.append(p)

        self.filtered_pitchers = results
        self._populate_list()

    def _on_select_pitcher(self, pitcher: dict):
        self.selected_pitcher = pitcher

        # Update detail panel
        self.lbl_pitcher_name.configure(text=pitcher["name"])

        team = pitcher["team"]
        team_color = TEAM_COLORS.get(team, "#555555")
        self.lbl_team_badge.configure(text=f"  {pitcher['team_full']}  ",
                                      bg=team_color)

        hand_text = "Right" if pitcher["throws"] == "R" else "Left"
        self.stat_throws.configure(text=hand_text)
        self.stat_slot.configure(text=pitcher["arm_slot"])

        h_ft = pitcher["height_inches"] // 12
        h_in = pitcher["height_inches"] % 12
        self.stat_height.configure(text=f"{h_ft}'{h_in}\"")

        box = self.calculator.get_box(pitcher)
        self.stat_release_x.configure(text=f"{box['cx']} px")
        self.stat_release_y.configure(text=f"{box['cy']} px")
        self.stat_box_size.configure(text=f"{box['w']}x{box['h']}")

        self.lbl_notes.configure(text=pitcher.get("notes", "--"))

        # Update visualization
        self._draw_release_point(pitcher)

        # Auto-apply: write output immediately so the CV pipeline picks it up
        self._on_apply()

    def _on_apply(self, event=None):
        if not self.selected_pitcher:
            self.lbl_status.configure(text="No pitcher selected",
                                      fg=COLORS["accent_red"])
            return

        box = self.calculator.get_box(self.selected_pitcher)

        # Get active batter + strike zone if lineup is set
        batter = None
        strike_zone = None
        if self.lineup and 0 <= self.active_batter_index < len(self.lineup):
            batter = self.lineup[self.active_batter_index]
            strike_zone = self.sz_calculator.get_zone(
                batter["height_inches"])

        try:
            OutputBridge.write(self.selected_pitcher, box, batter, strike_zone)
        except Exception as exc:
            self.lbl_status.configure(
                text=f"Write error: {exc}",
                fg=COLORS["accent_red"])
            return

        name = self.selected_pitcher["name"]
        status_parts = [f"Applied: {name} ({box['cx']}, {box['cy']})"]
        if batter:
            status_parts.append(f"| SZ: {batter['name']}")
        self.lbl_status.configure(
            text=" ".join(status_parts),
            fg=COLORS["accent_green"])

        # Save state
        self._save_state()

    def _on_copy(self, event=None):
        if not self.selected_pitcher:
            self.lbl_status.configure(text="No pitcher selected",
                                      fg=COLORS["accent_red"])
            return

        box = self.calculator.get_box(self.selected_pitcher)
        text = (f"{self.selected_pitcher['name']} | "
                f"X:{box['x']} Y:{box['y']} W:{box['w']} H:{box['h']} | "
                f"Center:({box['cx']},{box['cy']})")

        # Add strike zone info if batter active
        if self.lineup and 0 <= self.active_batter_index < len(self.lineup):
            batter = self.lineup[self.active_batter_index]
            zone = self.sz_calculator.get_zone(batter["height_inches"])
            text += (f" | SZ: {batter['name']} "
                     f"Top:{zone['top_px']} Bot:{zone['bottom_px']} "
                     f"W:{zone['width_px']} H:{zone['height_px']}")

        self.clipboard_clear()
        self.clipboard_append(text)
        self.lbl_status.configure(text="Coordinates copied!",
                                  fg=COLORS["accent_green"])

    # -----------------------------------------------------------------------
    # Lineup Event Handlers
    # -----------------------------------------------------------------------

    def _on_manage_lineup(self, event=None):
        """Open the lineup management dialog."""
        dialog = LineupDialog(self, self.lineup)
        self.wait_window(dialog)

        if dialog.result is not None:
            self.lineup = dialog.result
            if self.lineup:
                self.active_batter_index = 0
            else:
                self.active_batter_index = -1
            self._update_batter_display()
            self._update_lineup_strip()
            self._save_state()

    def _on_prev_batter(self, event=None):
        """Cycle to previous batter in lineup."""
        if not self.lineup:
            return
        self.active_batter_index -= 1
        if self.active_batter_index < 0:
            self.active_batter_index = len(self.lineup) - 1
        self._update_batter_display()
        self._update_lineup_strip()
        self._save_state()

        # Auto-update output if pitcher is selected
        if self.selected_pitcher:
            self._on_apply()

    def _on_next_batter(self, event=None):
        """Cycle to next batter in lineup."""
        if not self.lineup:
            return
        self.active_batter_index += 1
        if self.active_batter_index >= len(self.lineup):
            self.active_batter_index = 0
        self._update_batter_display()
        self._update_lineup_strip()
        self._save_state()

        # Auto-update output if pitcher is selected
        if self.selected_pitcher:
            self._on_apply()

    def _on_click_lineup_slot(self, slot_index: int):
        """Click a lineup slot to make that batter active."""
        if not self.lineup:
            self._on_manage_lineup()
            return

        if slot_index < len(self.lineup):
            self.active_batter_index = slot_index
            self._update_batter_display()
            self._update_lineup_strip()
            self._save_state()

            if self.selected_pitcher:
                self._on_apply()

    def _update_batter_display(self):
        """Update the active batter bar display."""
        if not self.lineup or self.active_batter_index < 0:
            self.lbl_batter_pos.configure(text="--")
            self.lbl_batter_name.configure(text="No lineup set")
            self.lbl_batter_height.configure(text="")
            self.lbl_batter_sz.configure(text="")
            return

        if self.active_batter_index >= len(self.lineup):
            self.active_batter_index = 0

        batter = self.lineup[self.active_batter_index]
        pos = batter.get("position", self.active_batter_index + 1)
        h = batter["height_inches"]
        h_ft = h // 12
        h_in = h % 12

        self.lbl_batter_pos.configure(text=f"#{pos}")
        self.lbl_batter_name.configure(text=batter["name"])
        self.lbl_batter_height.configure(text=f"{h_ft}'{h_in}\"")

        zone = self.sz_calculator.get_zone(h)
        self.lbl_batter_sz.configure(
            text=f"SZ: {zone['width_px']}x{zone['height_px']}")

    def _update_lineup_strip(self):
        """Update the bottom lineup strip display."""
        for i in range(9):
            slot = self.lineup_slot_labels[i]
            if i < len(self.lineup):
                b = self.lineup[i]
                h = b["height_inches"]
                h_ft = h // 12
                h_in = h % 12

                # Truncate name for display
                name = b["name"]
                if len(name) > 10:
                    parts = name.split()
                    if len(parts) > 1:
                        name = f"{parts[0][0]}. {parts[-1]}"
                    if len(name) > 10:
                        name = name[:9] + "."

                slot["name"].configure(text=name)
                slot["height"].configure(text=f"{h_ft}'{h_in}\"")

                if i == self.active_batter_index:
                    # Active batter highlight
                    bg = COLORS["bg_selected"]
                    slot["num"].configure(
                        fg=COLORS["accent_gold"], bg=bg)
                    slot["name"].configure(
                        fg=COLORS["accent_cyan"], bg=bg)
                    slot["height"].configure(
                        fg=COLORS["text_primary"], bg=bg)
                    slot["frame"].configure(bg=bg)
                else:
                    bg = COLORS["bg_card"]
                    slot["num"].configure(
                        fg=COLORS["text_dim"], bg=bg)
                    slot["name"].configure(
                        fg=COLORS["text_secondary"], bg=bg)
                    slot["height"].configure(
                        fg=COLORS["text_dim"], bg=bg)
                    slot["frame"].configure(bg=bg)
            else:
                slot["name"].configure(text="--",
                                       fg=COLORS["text_dim"],
                                       bg=COLORS["bg_card"])
                slot["height"].configure(text="",
                                         bg=COLORS["bg_card"])
                slot["num"].configure(fg=COLORS["text_dim"],
                                      bg=COLORS["bg_card"])
                slot["frame"].configure(bg=COLORS["bg_card"])

        if self.lineup:
            self.lbl_lineup_info.configure(
                text=f"{len(self.lineup)} batters | "
                     f"Use \u25C0 \u25B6 to cycle")
        else:
            self.lbl_lineup_info.configure(
                text="Click MANAGE LINEUP to set up batters")

    # -----------------------------------------------------------------------
    # State Persistence
    # -----------------------------------------------------------------------

    def _save_state(self):
        """Save current state to disk."""
        state = {
            "lineup": self.lineup,
            "active_batter_index": self.active_batter_index,
            "last_pitcher_name": (self.selected_pitcher["name"]
                                  if self.selected_pitcher else None),
        }
        StateManager.save(state)

    def _load_state(self):
        """Load saved state and restore UI."""
        state = StateManager.load()
        if not state:
            return

        # Restore lineup
        self.lineup = state.get("lineup", [])
        self.active_batter_index = state.get("active_batter_index", -1)

        if self.lineup:
            if self.active_batter_index >= len(self.lineup):
                self.active_batter_index = 0
            self._update_batter_display()
            self._update_lineup_strip()

        # Restore last selected pitcher
        last_pitcher = state.get("last_pitcher_name")
        if last_pitcher:
            for p in self.pitchers:
                if p["name"] == last_pitcher:
                    self._on_select_pitcher(p)
                    break

    # -----------------------------------------------------------------------
    # Visualization Drawing
    # -----------------------------------------------------------------------

    def _on_viz_resize(self, event=None):
        if self.selected_pitcher:
            self._draw_release_point(self.selected_pitcher)
        else:
            self._draw_empty_field()

    def _draw_empty_field(self):
        c = self.viz_canvas
        c.delete("all")
        cw = c.winfo_width()
        ch = c.winfo_height()
        if cw < 10 or ch < 10:
            return

        # Draw field outline
        self._draw_field_background(c, cw, ch)

        # Prompt text
        c.create_text(cw // 2, ch // 2, text="Select a pitcher to lock in",
                      font=("Segoe UI", 11), fill=COLORS["text_dim"])

    def _draw_release_point(self, pitcher: dict):
        c = self.viz_canvas
        c.delete("all")
        cw = c.winfo_width()
        ch = c.winfo_height()
        if cw < 10 or ch < 10:
            return

        # Draw field background
        self._draw_field_background(c, cw, ch)

        # Scale factors (canvas represents 1920x1080)
        sx = cw / SCREEN_W
        sy = ch / SCREEN_H

        box = self.calculator.get_box(pitcher)

        # Draw strike zone if batter is active
        if self.lineup and 0 <= self.active_batter_index < len(self.lineup):
            batter = self.lineup[self.active_batter_index]
            zone = self.sz_calculator.get_zone(batter["height_inches"])
            self._draw_strike_zone(c, zone, sx, sy)

        # Draw detection box
        bx = box["x"] * sx
        by = box["y"] * sy
        bw = box["w"] * sx
        bh = box["h"] * sy

        # Glow effect (outer)
        c.create_rectangle(bx - 2, by - 2, bx + bw + 2, by + bh + 2,
                           outline=COLORS["accent_cyan"], width=1,
                           dash=(4, 2))

        # Main box
        c.create_rectangle(bx, by, bx + bw, by + bh,
                           outline=COLORS["accent_cyan"], width=2,
                           fill="")

        # Center crosshair
        cx = box["cx"] * sx
        cy = box["cy"] * sy
        cross_size = 8

        c.create_line(cx - cross_size, cy, cx + cross_size, cy,
                      fill=COLORS["accent_red"], width=2)
        c.create_line(cx, cy - cross_size, cx, cy + cross_size,
                      fill=COLORS["accent_red"], width=2)

        # Center dot
        c.create_oval(cx - 3, cy - 3, cx + 3, cy + 3,
                      fill=COLORS["accent_gold"], outline="")

        # Label
        hand_label = "RHP" if pitcher["throws"] == "R" else "LHP"
        c.create_text(
            cx, by - 14,
            text=f"{pitcher['name']} ({hand_label})",
            font=("Segoe UI", 9, "bold"),
            fill=COLORS["accent_cyan"])

        # Coordinate labels
        c.create_text(
            bx + bw + 6, by,
            text=f"({box['x']}, {box['y']})",
            font=("Segoe UI", 7), fill=COLORS["text_dim"],
            anchor="nw")

        c.create_text(
            bx + bw + 6, by + bh,
            text=f"({box['x'] + box['w']}, {box['y'] + box['h']})",
            font=("Segoe UI", 7), fill=COLORS["text_dim"],
            anchor="sw")

        # Draw pitcher silhouette hint
        self._draw_pitcher_silhouette(c, cx, cy, cw, ch, pitcher)

    def _draw_strike_zone(self, canvas, zone: dict, sx: float, sy: float):
        """Draw the strike zone rectangle on the visualization."""
        left = zone["left_px"] * sx
        right = zone["right_px"] * sx
        top = zone["top_px"] * sy
        bottom = zone["bottom_px"] * sy

        # Zone outline
        canvas.create_rectangle(
            left, top, right, bottom,
            outline=COLORS["accent_gold"], width=2,
            dash=(6, 3), fill="")

        # Inner zone lines (9 sub-zones like a real strike zone)
        third_w = (right - left) / 3
        third_h = (bottom - top) / 3

        for i in range(1, 3):
            x = left + third_w * i
            canvas.create_line(x, top, x, bottom,
                               fill=COLORS["accent_gold"], width=1,
                               dash=(2, 4))
        for i in range(1, 3):
            y = top + third_h * i
            canvas.create_line(left, y, right, y,
                               fill=COLORS["accent_gold"], width=1,
                               dash=(2, 4))

        # Label
        canvas.create_text(
            (left + right) / 2, bottom + 10,
            text="STRIKE ZONE",
            font=("Segoe UI", 7, "bold"),
            fill=COLORS["accent_gold"])

    def _draw_field_background(self, canvas, cw, ch):
        """Draw a subtle baseball field background."""
        # Mound area (circle at bottom center)
        mound_cx = cw * 0.5
        mound_cy = ch * 0.85
        mound_r = min(cw, ch) * 0.06

        canvas.create_oval(
            mound_cx - mound_r, mound_cy - mound_r,
            mound_cx + mound_r, mound_cy + mound_r,
            outline=COLORS["border"], fill="#0f1520", width=1)

        # Rubber on mound
        rubber_w = mound_r * 0.8
        rubber_h = 3
        canvas.create_rectangle(
            mound_cx - rubber_w / 2, mound_cy - rubber_h / 2,
            mound_cx + rubber_w / 2, mound_cy + rubber_h / 2,
            fill=COLORS["text_dim"], outline="")

        # Home plate area at bottom
        hp_cx = cw * 0.5
        hp_cy = ch * 0.98
        hp_size = 6
        canvas.create_polygon(
            hp_cx, hp_cy - hp_size,
            hp_cx + hp_size, hp_cy,
            hp_cx + hp_size / 2, hp_cy + hp_size / 2,
            hp_cx - hp_size / 2, hp_cy + hp_size / 2,
            hp_cx - hp_size, hp_cy,
            fill=COLORS["text_dim"], outline=COLORS["border"])

        # Trajectory line (mound to plate)
        canvas.create_line(
            mound_cx, mound_cy, hp_cx, hp_cy,
            fill=COLORS["border"], width=1, dash=(2, 4))

        # Grid lines for reference
        for i in range(1, 4):
            y = ch * i / 4
            canvas.create_line(0, y, cw, y,
                               fill="#0f1520", width=1, dash=(1, 6))
        for i in range(1, 4):
            x = cw * i / 4
            canvas.create_line(x, 0, x, ch,
                               fill="#0f1520", width=1, dash=(1, 6))

        # Corner labels
        canvas.create_text(4, 4, text="0,0", font=("Segoe UI", 7),
                           fill=COLORS["text_dim"], anchor="nw")
        canvas.create_text(cw - 4, 4, text=f"{SCREEN_W},0",
                           font=("Segoe UI", 7),
                           fill=COLORS["text_dim"], anchor="ne")
        canvas.create_text(4, ch - 4, text=f"0,{SCREEN_H}",
                           font=("Segoe UI", 7),
                           fill=COLORS["text_dim"], anchor="sw")

    def _draw_pitcher_silhouette(self, canvas, cx, cy, cw, ch,
                                 pitcher: dict):
        """Draw a simple pitcher silhouette near the release point."""
        sx = cw / SCREEN_W
        sy = ch / SCREEN_H

        # Body center is below and to the side of release point
        is_righty = pitcher["throws"] == "R"
        body_offset_x = 20 * sx * (1 if is_righty else -1)
        body_cx = cx + body_offset_x
        body_cy = cy + 60 * sy

        # Torso line
        canvas.create_line(body_cx, body_cy - 15 * sy,
                           body_cx, body_cy + 25 * sy,
                           fill=COLORS["text_dim"], width=2)

        # Head
        head_r = 6 * sy
        canvas.create_oval(
            body_cx - head_r, body_cy - 15 * sy - head_r * 2,
            body_cx + head_r, body_cy - 15 * sy,
            outline=COLORS["text_dim"], width=2, fill="")

        # Arm to release point
        canvas.create_line(body_cx, body_cy - 10 * sy,
                           cx, cy,
                           fill=COLORS["accent_gold"], width=2,
                           dash=(3, 2))

        # Legs
        canvas.create_line(body_cx, body_cy + 25 * sy,
                           body_cx - 10 * sx, body_cy + 50 * sy,
                           fill=COLORS["text_dim"], width=2)
        canvas.create_line(body_cx, body_cy + 25 * sy,
                           body_cx + 10 * sx, body_cy + 50 * sy,
                           fill=COLORS["text_dim"], width=2)




# ---------------------------------------------------------------------------
# Auto-Updater
# ---------------------------------------------------------------------------

_GITHUB_USER = "creativeclickz"
_GITHUB_REPO = "pitchlock"
_GITHUB_BRANCH = "main"

_RAW_BASE = (f"https://raw.githubusercontent.com/"
             f"{_GITHUB_USER}/{_GITHUB_REPO}/{_GITHUB_BRANCH}")

_UPDATE_FILES = ["pitchlock.py", "pitchers_db.json"]


def _check_for_updates():
    """Silently check GitHub for a newer version and auto-update if found.

    Runs in a background thread so it never blocks the GUI or CV pipeline.
    If anything fails (no internet, repo not found, etc.) it silently
    skips — the user just keeps running whatever version they have.
    """
    try:
        version_url = f"{_RAW_BASE}/pitchlock.py"
        req = urllib.request.Request(version_url, method="GET")
        req.add_header("User-Agent", "PitchLock-AutoUpdater")
        with urllib.request.urlopen(req, timeout=5) as resp:
            remote_source = resp.read().decode("utf-8", errors="replace")

        # Extract __version__ from remote file
        remote_version = None
        for line in remote_source.splitlines():
            if line.startswith("__version__"):
                remote_version = line.split("=", 1)[1].strip().strip("\"'")
                break

        if not remote_version:
            return  # can't determine remote version, skip

        if remote_version == __version__:
            return  # already up to date

        # Newer version available — download all files
        target_dir = SCRIPT_DIR
        for fname in _UPDATE_FILES:
            file_url = f"{_RAW_BASE}/{fname}"
            req = urllib.request.Request(file_url, method="GET")
            req.add_header("User-Agent", "PitchLock-AutoUpdater")
            tmp_path = os.path.join(target_dir, fname + ".tmp")
            try:
                with urllib.request.urlopen(req, timeout=10) as resp:
                    with open(tmp_path, "wb") as f:
                        shutil.copyfileobj(resp, f)
                # Replace the original file
                final_path = os.path.join(target_dir, fname)
                os.replace(tmp_path, final_path)
            except Exception:
                # Clean up partial download
                if os.path.exists(tmp_path):
                    os.remove(tmp_path)

        print(f"[PitchLock] Updated from v{__version__} to v{remote_version}. "
              f"Restart to use the new version.", file=sys.stderr)

    except Exception:
        pass  # no internet, GitHub down, etc. — silently skip


def _start_update_check():
    """Launch the update check in a background thread."""
    t = threading.Thread(target=_check_for_updates, daemon=True)
    t.start()


# ---------------------------------------------------------------------------
# Entry Point
# ---------------------------------------------------------------------------

_app_instance = None


def launch():
    """Launch the PitchLock GUI.
    Called automatically when loaded as a creative module."""
    global _app_instance

    # Check for updates in the background (non-blocking)
    _start_update_check()

    try:
        _app_instance = PitchLockApp()

        # Center on screen
        _app_instance.update_idletasks()
        sw = _app_instance.winfo_screenwidth()
        sh = _app_instance.winfo_screenheight()
        x = (sw - _app_instance.WIDTH) // 2
        y = (sh - _app_instance.HEIGHT) // 2
        _app_instance.geometry(
            f"{_app_instance.WIDTH}x{_app_instance.HEIGHT}+{x}+{y}")

        _app_instance.mainloop()
    except Exception as exc:
        print(f"[PitchLock] ERROR: Failed to launch: {exc}", file=sys.stderr)
        traceback.print_exc(file=sys.stderr)
        try:
            messagebox.showerror("PitchLock Error",
                                 f"Failed to launch:\n{exc}")
        except Exception:
            pass


def main():
    """Direct launch (standalone mode)."""
    launch()


# ---------------------------------------------------------------------------
# Auto-launch when imported as a creative module by MLB Vision / Helios II
# ---------------------------------------------------------------------------
# When MLB Vision imports this module, the GUI launches in a background
# thread so it doesn't block the main CV pipeline.

def _auto_launch():
    gui_thread = threading.Thread(target=launch, daemon=True)
    gui_thread.start()


# Detect if we're being imported (creative module) vs run directly
if __name__ == "__main__":
    # Run directly from command line - launch in main thread
    main()
else:
    # Imported by MLB Vision creative module system - launch in background
    _auto_launch()

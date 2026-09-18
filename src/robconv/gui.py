"""Desktop window (Tkinter, part of Python: no extra dependency).

Pick an ABB backup (folder or .zip) or RAPID files; the conversion runs in a
background thread so the window stays responsive; the output folder opens when
it is done. Files dropped on the robconv.exe icon arrive as command-line
arguments and are converted straight away (see app.py).
"""

import os
import queue
import subprocess
import sys
import threading
import tkinter as tk
import zipfile
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

from robconv import __version__, pipeline
from robconv.convert import ConversionConfig
from robconv.rapid import RAPID_SUFFIXES

RAPID_PATTERNS = " ".join(f"*{s}" for s in sorted(RAPID_SUFFIXES))


def open_in_explorer(path: Path) -> None:
    if sys.platform == "win32":
        os.startfile(path)
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


class App(tk.Tk):
    def __init__(self) -> None:
        super().__init__()
        self.title(f"robconv {__version__} - ABB RAPID to FANUC TP")
        scale = self.winfo_fpixels("1i") / 96  # 1.25 / 1.5 on scaled Windows displays
        self.geometry(f"{int(760 * scale)}x{int(540 * scale)}")
        self.minsize(int(600 * scale), int(420 * scale))
        self.mapping: Path | None = None
        self.last: pipeline.RunOutput | None = None
        self.messages: queue.Queue[tuple[str, object]] = queue.Queue()
        self._build()
        self.after(100, self._poll)

    # -- layout -----------------------------------------------------------

    def _build(self) -> None:
        root = ttk.Frame(self, padding=14)
        root.pack(fill="both", expand=True)

        ttk.Label(root, text="Convert an ABB robot program to FANUC", font=("Segoe UI", 13, "bold")).pack(anchor="w")
        ttk.Label(
            root,
            text=(
                "Choose a controller backup (folder or .zip) or RAPID files. Each robot task is converted to\n"
                ".LS programs with a report next to the input. Nothing leaves this computer."
            ),
            foreground="#555",
        ).pack(anchor="w", pady=(2, 10))

        buttons = ttk.Frame(root)
        buttons.pack(fill="x")
        self.inputs = [
            ttk.Button(buttons, text="Backup folder...", command=self.pick_folder),
            ttk.Button(buttons, text="Backup .zip...", command=self.pick_zip),
            ttk.Button(buttons, text="RAPID files...", command=self.pick_files),
        ]
        for button in self.inputs:
            button.pack(side="left", padx=(0, 8))

        mapping = ttk.Frame(root)
        mapping.pack(fill="x", pady=(10, 6))
        ttk.Button(mapping, text="Mapping file (optional)...", command=self.pick_mapping).pack(side="left")
        self.mapping_label = ttk.Label(mapping, text="automatic numbering", foreground="#555")
        self.mapping_label.pack(side="left", padx=8)

        self.log_view = ScrolledText(root, height=14, state="disabled", font=("Consolas", 9))
        self.log_view.pack(fill="both", expand=True, pady=(4, 8))

        actions = ttk.Frame(root)
        actions.pack(fill="x")
        self.open_folder = ttk.Button(actions, text="Open output folder", command=self.show_folder, state="disabled")
        self.open_report = ttk.Button(actions, text="Open report", command=self.show_report, state="disabled")
        self.open_folder.pack(side="left", padx=(0, 8))
        self.open_report.pack(side="left")
        self.status = ttk.Label(actions, text="Ready", foreground="#555")
        self.status.pack(side="right")

    # -- input ------------------------------------------------------------

    def pick_folder(self) -> None:
        folder = filedialog.askdirectory(title="ABB backup folder")
        if folder:
            self.start([Path(folder)])

    def pick_zip(self) -> None:
        archive = filedialog.askopenfilename(title="Zipped ABB backup", filetypes=[("Zip archive", "*.zip")])
        if archive:
            self.start([Path(archive)])

    def pick_files(self) -> None:
        files = filedialog.askopenfilenames(
            title="RAPID modules", filetypes=[("RAPID modules", RAPID_PATTERNS), ("All files", "*.*")]
        )
        if files:
            self.start([Path(f) for f in files])

    def pick_mapping(self) -> None:
        path = filedialog.askopenfilename(title="Mapping file", filetypes=[("JSON", "*.json")])
        if path:
            try:
                ConversionConfig.from_mapping_file(path)
            except (OSError, ValueError, TypeError) as exc:
                messagebox.showerror("robconv", f"Invalid mapping file:\n{exc}")
                return
            self.mapping = Path(path)
            self.mapping_label.config(text=self.mapping.name)

    # -- conversion (background thread) -------------------------------------

    def start(self, paths: list[Path]) -> None:
        for button in (*self.inputs, self.open_folder, self.open_report):
            button.config(state="disabled")
        self.status.config(text="Converting...")
        self.log(f"> {', '.join(p.name for p in paths)}")
        threading.Thread(target=self._work, args=(paths,), daemon=True).start()

    def _work(self, paths: list[Path]) -> None:
        try:
            config = ConversionConfig.from_mapping_file(self.mapping) if self.mapping else ConversionConfig()
            result = pipeline.run(paths, config=config, log=lambda line: self.messages.put(("log", line)))
            self.messages.put(("done", result))
        except (OSError, ValueError, TypeError, zipfile.BadZipFile) as exc:
            self.messages.put(("error", exc))
        except Exception as exc:  # noqa: BLE001 - never leave the window stuck on "Converting..."
            self.messages.put(("error", f"Unexpected error ({type(exc).__name__}): {exc}"))

    def _poll(self) -> None:
        while not self.messages.empty():
            kind, payload = self.messages.get()
            if kind == "log":
                self.log(str(payload))
            elif kind == "done":
                self.finished(payload)  # type: ignore[arg-type]
            else:
                self.failed(str(payload))
        self.after(100, self._poll)

    def finished(self, result: pipeline.RunOutput) -> None:
        self.last = result
        for button in (*self.inputs, self.open_folder, self.open_report):
            button.config(state="normal")
        errors = sum(len(t.syntax_errors) for t in result.tasks)
        summary = f"Done: {result.programs} programs, {result.todo} TODO to review"
        self.status.config(text=summary + (f", {errors} syntax errors" if errors else ""))
        self.log(summary + "\n")
        open_in_explorer(result.folder)

    def failed(self, message: str) -> None:
        for button in self.inputs:
            button.config(state="normal")
        self.status.config(text="Failed")
        self.log(f"ERROR: {message}\n")
        messagebox.showerror("robconv", message)

    # -- output ---------------------------------------------------------------

    def log(self, line: str) -> None:
        self.log_view.config(state="normal")
        self.log_view.insert("end", line + "\n")
        self.log_view.see("end")
        self.log_view.config(state="disabled")

    def show_folder(self) -> None:
        if self.last:
            open_in_explorer(self.last.folder)

    def show_report(self) -> None:
        if self.last and self.last.tasks and self.last.tasks[0].report_html:
            open_in_explorer(self.last.tasks[0].report_html)


def _sharp_on_high_dpi() -> None:
    """Without this, Windows scales the window as a bitmap on 125-150 % displays: blurry text."""
    if sys.platform == "win32":
        try:
            import ctypes

            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except (AttributeError, OSError):
            pass


def launch(paths: list[Path] | None = None) -> None:
    _sharp_on_high_dpi()
    app = App()
    if paths:
        app.after(200, app.start, paths)  # files dropped on the exe icon
    app.mainloop()

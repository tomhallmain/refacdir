from copy import deepcopy
import os
import signal
import time
import traceback

import tkinter as tk
from tkinter import messagebox, HORIZONTAL
from tkinter.constants import W
import tkinter.font as fnt
from tkinter.ttk import Button, Entry, Progressbar, Label, Checkbutton, LabelFrame, Style
from lib.autocomplete_entry import AutocompleteEntry, matches
from ttkthemes import ThemedTk

from run import main
from extensions.refacdir_server import RefacDirServer
from refacdir.batch import BatchArgs
from refacdir.config import config as _config
from refacdir.job_queue import JobQueue
from refacdir.running_tasks_registry import start_thread, periodic, RecurringActionConfig
from refacdir.utils import Utils

from refacdir.ui.test_results_window import TestResultWindow

# TODO persistent file ops (see "D:\Scripts\poll_folder.py")
# TODO filtering of configs


def set_attr_if_not_empty(text_box):
    current_value = text_box.get()
    if not current_value or current_value == "":
        return None
    return

def matches_tag(fieldValue, acListEntry):
    if fieldValue and "+" in fieldValue:
        pattern_base = fieldValue.split("+")[-1]
    elif fieldValue and "," in fieldValue:
        pattern_base = fieldValue.split(",")[-1]
    else:
        pattern_base = fieldValue
    return matches(pattern_base, acListEntry)

def set_tag(current_value, new_value):
    if current_value and (current_value.endswith("+") or current_value.endswith(",")):
        return current_value + new_value
    else:
        return new_value

def clear_quotes(s):
    if len(s) > 0:
        if s.startswith('"'):
            s = s[1:]
        if s.endswith('"'):
            s = s[:-1]
        if s.startswith("'"):
            s = s[1:]
        if s.endswith("'"):
            s = s[:-1]
    return s

class Sidebar(tk.Frame):
    def __init__(self, master=None, cnf={}, **kw):
        tk.Frame.__init__(self, master=master, cnf=cnf, **kw)


class ProgressListener:
    def __init__(self, update_func):
        self.update_func = update_func

    def update(self, context, percent_complete):
        self.update_func(context, percent_complete)

    def update_status(self, status):
        self.update_func(None, None, status)


class App():
    '''
    UI for refacdir app.
    '''

    configs = {}

    IS_DEFAULT_THEME = False
    DARK_BG = _config.background_color if _config.background_color and _config.background_color != "" else "#26242f"
    DARK_FG = _config.foreground_color if _config.foreground_color and _config.foreground_color != "" else "#ffffff"
    LIGHT_BG = "#f0f0f0"
    LIGHT_FG = "#000000"

    def configure_style(self, theme):
        self.master.set_theme(theme, themebg="black")
        self.style = Style()
        
        # Configure colors based on theme
        bg_color = App.LIGHT_BG if App.IS_DEFAULT_THEME else App.DARK_BG
        fg_color = App.LIGHT_FG if App.IS_DEFAULT_THEME else App.DARK_FG
        
        # Configure styles with appropriate colors
        self.style.configure('Header.TLabel', 
                           font=('Helvetica', 12, 'bold'))
        self.style.configure('Status.TLabel', 
                           font=('Helvetica', 10))
        self.style.configure('Summary.TLabel', 
                           font=('Helvetica', 11))
        self.style.configure('Action.TButton', 
                           font=('Helvetica', 10))
        self.style.configure('Config.TCheckbutton', 
                           font=('Helvetica', 10))
        self.style.configure('Toast.TLabel', 
                           font=('Helvetica', 12))
        
        # Configure frame styles
        self.style.configure('Main.TFrame', background=bg_color)
        self.style.configure('Sidebar.TFrame', background=bg_color)
        self.style.configure('Config.TFrame', background=bg_color)
        self.style.configure('Progress.TFrame', background=bg_color)
        self.style.configure('Control.TFrame', background=bg_color)
        
        # Configure label styles with proper background and foreground
        self.style.configure('TLabel', 
                           background=bg_color,
                           foreground=fg_color)
        
        # Configure checkbutton styles with proper background and foreground
        self.style.configure('TCheckbutton', 
                           background=bg_color,
                           foreground=fg_color)
        
        # Configure button styles
        self.style.configure('TButton', 
                           background=bg_color,
                           foreground=fg_color)
        
        # Configure labelframe styles
        self.style.configure('TLabelframe', 
                           background=bg_color,
                           foreground=fg_color)
        self.style.configure('TLabelframe.Label', 
                           background=bg_color,
                           foreground=fg_color)
        
        # Configure progress bar styles
        self.style.configure('Horizontal.TProgressbar', 
                           background=bg_color,
                           troughcolor=bg_color)

    def toggle_theme(self):
        if App.IS_DEFAULT_THEME:
            self.configure_style("breeze")
            bg_color = App.LIGHT_BG
            fg_color = App.LIGHT_FG
        else:
            self.configure_style("black")
            bg_color = App.DARK_BG
            fg_color = App.DARK_FG
        App.IS_DEFAULT_THEME = not App.IS_DEFAULT_THEME
        
        # Update main window and container backgrounds
        self.master.config(bg=bg_color)
        self.main_container.config(bg=bg_color)
        self.sidebar.config(bg=bg_color)
        self.config.config(bg=bg_color)
        
        # Update all frames
        for frame in [self.main_container, self.sidebar, self.config]:
            for child in frame.winfo_children():
                if isinstance(child, tk.Frame):
                    child.config(bg=bg_color)
        
        self.master.update()
        self.toast("Theme switched to light." if App.IS_DEFAULT_THEME else "Theme switched to dark.")

    def __init__(self, master):
        self.master = master
        self.master.protocol("WM_DELETE_WINDOW", self.on_closing)
        self.progress_bar = None
        self.job_queue = JobQueue()
        self.server = self.setup_server()
        self.recurring_action_config = RecurringActionConfig()

        BatchArgs.setup_configs(recache=False)
        App.configs = deepcopy(BatchArgs.configs)
        self.filtered_configs = deepcopy(BatchArgs.configs)
        self.filter_text = ""

        # Configure main window
        self.master.title("RefacDir")
        self.master.geometry("800x600")
        self.master.minsize(600, 400)
        self.master.configure(bg=App.DARK_BG)
        
        # Main container
        self.main_container = tk.Frame(self.master, bg=App.DARK_BG)
        self.main_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # Create sections
        self.create_header_section()
        self.create_sidebar_section()
        self.create_config_section()
        self.create_progress_section()
        self.create_control_section()

        # Initialize theme
        self.configure_style("black")
        self.toggle_theme()

    def create_header_section(self):
        """Create the header section with title and description"""
        header_frame = tk.Frame(self.main_container, bg=App.DARK_BG)
        header_frame.pack(fill=tk.X, pady=(0, 10))
        
        title = Label(header_frame, 
                     text="RefacDir File Management", 
                     style='Header.TLabel')
        title.pack(anchor=tk.W)
        
        description = Label(header_frame,
                          text="Configure and run file management operations with ease",
                          wraplength=700)
        description.pack(anchor=tk.W)

    def create_sidebar_section(self):
        """Create the sidebar section with action buttons and configs"""
        self.sidebar = tk.Frame(self.main_container, bg=App.DARK_BG)
        self.sidebar.pack(side=tk.LEFT, fill=tk.Y, padx=(0, 10))
        
        # Action buttons
        self.toggle_theme_btn = Button(self.sidebar, 
                                     text="Toggle Theme", 
                                     command=self.toggle_theme,
                                     style='Action.TButton')
        self.toggle_theme_btn.pack(fill=tk.X, pady=(0, 5))
        
        self.test_runner_btn = Button(self.sidebar, 
                                    text="Run Backup Tests", 
                                    command=self.run_tests,
                                    style='Action.TButton')
        self.test_runner_btn.pack(fill=tk.X, pady=(0, 5))
        
        self.run_btn = Button(self.sidebar, 
                            text="Run Operations", 
                            command=self.run,
                            style='Action.TButton')
        self.run_btn.pack(fill=tk.X, pady=(0, 5))
        
        # Config checkboxes
        self.config_vars = []
        self.config_checkbuttons = []
        self.add_config_widgets()

    def create_config_section(self):
        """Create the configuration section with options"""
        self.config = tk.Frame(self.main_container, bg=App.DARK_BG)
        self.config.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        
        # Options frame
        options_frame = LabelFrame(self.config, text="Options", padding="5")
        options_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Configuration options
        self.recur_var = tk.BooleanVar(value=False)
        self.recur_choice = Checkbutton(options_frame, 
                                      text="Recur Selected Actions", 
                                      variable=self.recur_var, 
                                      command=self.set_recurring_action,
                                      style='Config.TCheckbutton')
        self.recur_choice.pack(anchor=tk.W, pady=2)
        
        self.test_var = tk.BooleanVar(value=False)
        self.test_choice = Checkbutton(options_frame, 
                                     text="Test Mode", 
                                     variable=self.test_var,
                                     style='Config.TCheckbutton')
        self.test_choice.pack(anchor=tk.W, pady=2)
        
        self.skip_confirm_var = tk.BooleanVar(value=False)
        self.skip_confirm_choice = Checkbutton(options_frame, 
                                             text="Skip Confirmations", 
                                             variable=self.skip_confirm_var,
                                             style='Config.TCheckbutton')
        self.skip_confirm_choice.pack(anchor=tk.W, pady=2)
        
        self.only_observers_var = tk.BooleanVar(value=False)
        self.only_observers_choice = Checkbutton(options_frame, 
                                               text="Only Observers", 
                                               variable=self.only_observers_var,
                                               style='Config.TCheckbutton')
        self.only_observers_choice.pack(anchor=tk.W, pady=2)

    def create_progress_section(self):
        """Create the progress section"""
        self.progress_frame = tk.Frame(self.config, bg=App.DARK_BG)
        self.progress_frame.pack(fill=tk.X, pady=(0, 10))
        
        self.status_label = Label(self.progress_frame, 
                                text="Ready",
                                style='Status.TLabel')
        self.status_label.pack(fill=tk.X)
        
        self.progress_bar = None

    def create_control_section(self):
        """Create the control section"""
        control_frame = tk.Frame(self.config, bg=App.DARK_BG)
        control_frame.pack(fill=tk.X)
        
        # Bind keyboard shortcuts
        self.master.bind("<Shift-R>", self.run)
        self.master.bind("<Return>", self.do_action)
        self.master.bind("<Key>", self.filter_configs)

    def add_config_widgets(self):
        """Add configuration checkboxes to sidebar"""
        for config, will_run in self.filtered_configs.items():
            def toggle_config_handler(event=None, self=self, config=config):
                if config in self.filtered_configs:
                    self.filtered_configs[config] = not self.filtered_configs[config]
                    App.configs[config] = self.filtered_configs[config]
                    BatchArgs.update_config_state(config, self.filtered_configs[config])
                    print(f"Config {config} set to {self.filtered_configs[config]}")
                return True

            var = tk.BooleanVar(value=will_run if will_run is not None else False)
            self.config_vars.append(var)
            checkbutton = Checkbutton(self.sidebar, 
                                    text=config, 
                                    variable=var, 
                                    command=toggle_config_handler,
                                    style='Config.TCheckbutton')
            self.config_checkbuttons.append(checkbutton)
            checkbutton.pack(anchor=tk.W, pady=2)

    def on_closing(self):
        if self.server is not None:
            try:
                self.server.stop()
            except Exception as e:
                print(f"Error stopping server: {e}")
        self.master.destroy()

    def setup_server(self):
        server = RefacDirServer(self.server_run_callback)
        try:
            Utils.start_thread(server.start)
            return server
        except Exception as e:
            print(f"Failed to start server: {e}")
        return None

    def get_config(self, event=None, config=None):
        """
        Have to call this when user is setting a new directory as well, in which case _dir will be None.
        
        In this case we will need to add the new directory to the list of valid directories.
        
        Also in this case, this function will call itself by calling set_directory(),
        just this time with the directory set.
        """
        config, target_was_valid = RecentDirectoryWindow.get_directory(config, self.starting_target, self.app_actions.toast)
        if not os.path.isdir(config):
            self.close_windows()
            raise Exception("Failed to set target directory to receive marked files.")
        if target_was_valid and config is not None:
            if config in RecentDirectories.directories:
                RecentDirectories.directories.remove(config)
            RecentDirectories.directories.insert(0, config)
            return config

        config = os.path.normpath(config)
        # NOTE don't want to sort here, instead keep the most recent directories at the top
        if config in RecentDirectories.directories:
            RecentDirectories.directories.remove(config)
        RecentDirectories.directories.insert(0, config)
        self.run_config(config=config)

    def run_config(self, event=None, config=None):
        config = self.get_config(config=config)
        if self.filter_text is not None and self.filter_text.strip() != "":
            print(f"Filtered by string: {self.filter_text}")
        self.filtered_configs = {config: True}
        RecentDirectoryWindow.last_set_directory = config
        self.close_windows()

    def filter_configs(self, event):
        """
        Rebuild the filtered configs dict based on the filter string and update the UI.
        """
        modifier_key_pressed = (event.state & 0x1) != 0 or (event.state & 0x4) != 0 # Do not filter if modifier key is down
        if modifier_key_pressed:
            return
        filtered_configs_list = list(self.filtered_configs.keys())
        if len(event.keysym) > 1:
            # If the key is up/down arrow key, roll the list up/down
            if event.keysym == "Down" or event.keysym == "Up":
                if event.keysym == "Down":
                    filtered_configs_list = filtered_configs_list[1:] + [filtered_configs_list[0]]
                else:  # keysym == "Up"
                    filtered_configs_list = [filtered_configs_list[-1]] + filtered_configs_list[:-1]
                to_delete = []
                for config in self.filtered_configs:
                    if config not in filtered_configs_list and config is not None:
                        to_delete += [config]
                for config in to_delete:
                    del self.filtered_configs[config]
                self.clear_widget_lists()
                self.add_config_widgets()
                self.master.update()
            if event.keysym != "BackSpace":
                return
        if event.keysym == "BackSpace":
            if len(self.filter_text) > 0:
                self.filter_text = self.filter_text[:-1]
        elif event.char:
            self.filter_text += event.char
        else:
            return
        if self.filter_text.strip() == "":
            if _config.debug:
                print("Filter unset")
            # Restore the list of target directories to the full list
            self.filtered_configs.clear()
            self.filtered_configs = deepcopy(App.configs)
        else:
            temp = []
            for path in App.configs:
                basename = os.path.basename(os.path.normpath(path))
                if basename.lower() == self.filter_text:
                    temp.append(path)
            for path in App.configs:
                basename = os.path.basename(os.path.normpath(path))
                if not path in temp:
                    if basename.lower().startswith(self.filter_text):
                        temp.append(path)
            for path in App.configs:
                if not path in temp:
                    basename = os.path.basename(os.path.normpath(path))
                    if basename and (f" {self.filter_text}" in basename.lower() or f"_{self.filter_text}" in basename.lower()):
                        temp.append(path)
            self.filtered_configs = {}
            for config_path in temp:
                self.filtered_configs[config_path]  = App.configs[config_path]

        self.clear_widget_lists()
        self.add_config_widgets()
        self.master.update()


    def do_action(self, event=None):
        """
        The user has requested to run a file operation. Based on the context, figure out what to do.

        If no configs preset or control key pressed, run all files not explicitly set to will_run == False.

        If configs filtered, call set_directory() to set the first directory.

        The idea is the user can filter the configs using keypresses, then press enter to
        do the action with the first filtered config.
        """
#        shift_key_pressed = (event.state & 0x1) != 0
        control_key_pressed = (event.state & 0x4) != 0
#        alt_key_pressed = (event.state & 0x20000) != 0
        if len(self.filtered_configs) == 0:
            raise Exception("No directories to run")
        if self.filter_text.strip() == "" or control_key_pressed:
            self.run()
        elif len(self.filtered_configs) == 1 or self.filter_text.strip() != "":
            _dir = self.filtered_configs[0]
            self.run_config(config=_dir)
        else:
            self.run()


    def set_workflow_type(self, event=None, workflow_tag=None):
        pass

    def destroy_progress_bar(self):
        if self.progress_bar is not None:
            self.progress_bar.stop()
            self.progress_bar.pack_forget()
            self.progress_bar = None

    def run(self, event=None):
        if self.progress_bar is not None:
            return

        args = BatchArgs(recache_configs=False)  # Don't reload from files
        args.test = self.test_var.get()
        args.skip_confirm = self.skip_confirm_var.get()
        args.only_observers = self.only_observers_var.get()
        
        # Only run filtered configs
        BatchArgs.override_configs(self.filtered_configs)

        # Create progress bar if it doesn't exist
        if self.progress_bar is None:
            self.progress_bar = Progressbar(
                self.progress_frame,
                orient=tk.HORIZONTAL,
                length=300,
                mode='determinate'
            )
            self.progress_bar.pack(fill=tk.X, pady=(5, 0))

        # Update status
        self.status_label.config(text="Running operations...")
        self.progress_bar["value"] = 0

        def run_async(args) -> None:
            try:
                main(args)
            except Exception as e:
                self.alert("Error", str(e), "error")
                self.status_label.config(text="Operation failed")
            finally:
                self.status_label.config(text="Ready")
                self.progress_bar["value"] = 0
                self.progress_bar.pack_forget()  # Hide progress bar when done
                self.progress_bar = None

        Utils.start_thread(lambda: run_async(args))


    def set_recurring_action(self, event=None):
        self.recurring_action_config.set(self.recur_var.get())
        if self.recurring_action_config.is_running:
            self.skip_confirm_var.set(True)
            start_thread(self.run_recurring_actions)


    @periodic("recurring_action_config")
    async def run_recurring_actions(self, **kwargs):
        self.run()


    def server_run_callback(self, args):
        if len(args) > 0:
            print(args)
            self.master.update()
        self.run()
        return {} # Empty error object for confirmation


    def clear_widget_lists(self):
        for btn in self.config_checkbuttons:
            btn.destroy()
            self.row_counter0 -= 1
        self.config_vars = []
        self.config_checkbuttons = []

    def alert(self, title, message, kind="info", hidemain=True) -> None:
        if kind not in ("error", "warning", "info"):
            raise ValueError("Unsupported alert kind.")

        print(f"Alert - Title: \"{title}\" Message: {message}")
        show_method = getattr(messagebox, "show{}".format(kind))
        return show_method(title, message)

    def toast(self, message):
        print("Toast message: " + message)

        # Set the position of the toast on the screen (top right)
        width = 300
        height = 100
        x = self.master.winfo_screenwidth() - width
        y = 0

        # Create the toast on the top level
        toast = tk.Toplevel(self.master, bg=App.DARK_BG if not App.IS_DEFAULT_THEME else App.LIGHT_BG)
        toast.geometry(f'{width}x{height}+{int(x)}+{int(y)}')
        self.container = tk.Frame(toast, bg=App.DARK_BG if not App.IS_DEFAULT_THEME else App.LIGHT_BG)
        self.container.pack(fill=tk.BOTH, expand=tk.YES)
        
        # Style the toast message
        label = Label(
            self.container,
            text=message,
            anchor=tk.NW,
            style='Toast.TLabel'
        )
        label.grid(row=1, column=1, sticky="NSEW", padx=10, pady=(0, 5))
        
        # Make the window invisible and bring it to front
        toast.attributes('-topmost', True)

        # Start a new thread that will destroy the window after a few seconds
        def self_destruct_after(time_in_seconds):
            time.sleep(time_in_seconds)
            label.destroy()
            toast.destroy()
        Utils.start_thread(self_destruct_after, use_asyncio=False, args=[2])

    def apply_to_grid(self, component, sticky=None, pady=0, interior_column=0, column=0, increment_row_counter=True, columnspan=None):
        row = self.row_counter0 if column == 0 else self.row_counter1
        if sticky is None:
            if columnspan is None:
                component.grid(column=interior_column, row=row, pady=pady)
            else:
                component.grid(column=interior_column, row=row, pady=pady, columnspan=columnspan)
        else:
            if columnspan is None:
                component.grid(column=interior_column, row=row, sticky=sticky, pady=pady)
            else:
                component.grid(column=interior_column, row=row, sticky=sticky, pady=pady, columnspan=columnspan)
        if increment_row_counter:
            if column == 0:
                self.row_counter0 += 1
            else:
                self.row_counter1 += 1

    def add_label(self, label_ref, text, sticky=W, pady=0, column=0, columnspan=None):
        label_ref['text'] = text
        self.apply_to_grid(label_ref, sticky=sticky, pady=pady, column=column, columnspan=columnspan)

    def add_button(self, button_ref_name, text, command):
        if getattr(self, button_ref_name) is None:
            button = Button(master=self.sidebar, text=text, command=command)
            setattr(self, button_ref_name, button)
            button
            self.apply_to_grid(button)

    def new_entry(self, text_variable, text="", **kw):
        return Entry(self.sidebar, text=text, textvariable=text_variable, width=40, font=fnt.Font(size=8), **kw)

    def destroy_grid_element(self, element_ref_name):
        element = getattr(self, element_ref_name)
        if element is not None:
            element.destroy()
            setattr(self, element_ref_name, None)
            self.row_counter0 -= 1

    def run_tests(self, event=None):
        """Run backup system tests and display results"""
        # Create results window
        results_window = TestResultWindow(self.master)
        results_window.run_tests()
            


if __name__ == "__main__":
    try:
        assets = os.path.join(os.path.dirname(os.path.realpath(__file__)), "assets")
        root = ThemedTk(theme="black", themebg="black")
        root.title("RefacDir")
        root.geometry("800x600")
        root.minsize(600, 400)
        root.resizable(True, True)
        
        # Configure grid weights
        root.columnconfigure(0, weight=1)
        root.columnconfigure(1, weight=1)
        root.rowconfigure(0, weight=1)

        # Graceful shutdown handler
        def graceful_shutdown(signum, frame):
            print("Caught signal, shutting down gracefully...")
            app.on_closing()
            exit(0)

        # Register the signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, graceful_shutdown)
        signal.signal(signal.SIGTERM, graceful_shutdown)

        app = App(root)
        root.mainloop()
        exit()
    except KeyboardInterrupt:
        pass
    except Exception:
        traceback.print_exc()

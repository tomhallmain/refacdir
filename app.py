from copy import deepcopy
import os
import signal
import time
import traceback

import tkinter as tk
from tkinter import messagebox, HORIZONTAL, Label, Checkbutton
from tkinter.constants import W
import tkinter.font as fnt
from tkinter.ttk import Button, Entry, Frame, OptionMenu, Progressbar
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


class App():
    '''
    UI for refacdir app.
    '''

    configs = {}

    IS_DEFAULT_THEME = False
    GRAY = "gray"
    DARK_BG = _config.background_color if _config.background_color and _config.background_color != "" else "#26242f"
    DARK_FG = _config.foreground_color if _config.foreground_color and _config.foreground_color != "" else "#white"

    def configure_style(self, theme):
        self.master.set_theme(theme, themebg="black")

    def toggle_theme(self):
        if App.IS_DEFAULT_THEME:
            self.configure_style("breeze") # Changes the window to light theme
            bg_color = App.GRAY
            fg_color = "black"
        else:
            self.configure_style("black") # Changes the window to dark theme
            bg_color = App.DARK_BG
            fg_color = App.DARK_FG
        App.IS_DEFAULT_THEME = not App.IS_DEFAULT_THEME
        self.master.config(bg=bg_color)
        self.sidebar.config(bg=bg_color)
        self.config.config(bg=bg_color)
        for name, attr in self.__dict__.items():
            if isinstance(attr, Label):
                attr.config(bg=bg_color, fg=fg_color)
            elif isinstance(attr, Checkbutton):
                attr.config(bg=bg_color, fg=fg_color, selectcolor=bg_color)
        self.master.update()
        self.toast("Theme switched to dark." if App.IS_DEFAULT_THEME else "Theme switched to light.")

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

        # Sidebar
        self.sidebar = Sidebar(self.master)
        self.sidebar.columnconfigure(0, weight=1)
        self.row_counter0 = 0
        self.sidebar.grid(column=0, row=self.row_counter0)
        self.label_title = Label(self.sidebar)
        self.add_label(self.label_title, "Run File Batch Operations", sticky=None)

        self.toggle_theme_btn = None
        self.add_button("toggle_theme_btn", "Toggle theme", self.toggle_theme)

        self.run_btn = None
        self.add_button("run_btn", "Run", self.run)
        self.master.bind("<Shift-R>", self.run)

        self.config_vars = []
        self.config_checkbuttons = []
        self.add_config_widgets()

        # Prompter Config
        self.row_counter1 = 0
        self.config = Sidebar(self.master)
        self.config.columnconfigure(0, weight=1)
        self.config.columnconfigure(1, weight=1)
        self.config.columnconfigure(2, weight=1)
        self.config.grid(column=1, row=self.row_counter1)

        # self.label_title_config = Label(self.prompter_config)
        # self.add_label(self.label_title_config, "Prompts Configuration", column=1, sticky=tk.W+tk.E)

        # self.label_prompt_mode = Label(self.prompter_config)
        # self.add_label(self.label_prompt_mode, "Prompt Mode", column=1)
        # self.prompt_mode = tk.StringVar(master)
        # self.prompt_mode_choice = OptionMenu(self.prompter_config, self.prompt_mode, str(PromptMode.SFW), *PromptMode.__members__.keys())
        # self.apply_to_grid(self.prompt_mode_choice, sticky=W, column=1)

        self.recur_var = tk.BooleanVar(value=False)
        self.recur_choice = Checkbutton(self.config, text="Recur Selected Actions", variable=self.recur_var, command=self.set_recurring_action)
        self.apply_to_grid(self.recur_choice, sticky=W, column=1)

        self.test_var = tk.BooleanVar(value=False)
        self.test_choice = Checkbutton(self.config, text="Test Mode", variable=self.test_var)
        self.apply_to_grid(self.test_choice, sticky=W, column=1)

        self.skip_confirm_var = tk.BooleanVar(value=False)
        self.skip_confirm_choice = Checkbutton(self.config, text="Skip Confirmations", variable=self.skip_confirm_var)
        self.apply_to_grid(self.skip_confirm_choice, sticky=W, column=1)

        self.only_observers_var = tk.BooleanVar(value=False)
        self.only_observers_choice = Checkbutton(self.config, text="Only Observers", variable=self.only_observers_var)
        self.apply_to_grid(self.only_observers_choice, sticky=W, column=1)

        self.master.bind("<Return>", self.do_action)
        self.master.bind("<Key>", self.filter_configs)
        self.toggle_theme()
        self.master.update()
#        self.model_tags_box.closeListbox()

        # Add test runner button after theme toggle
        self.test_runner_btn = None
        self.add_button("test_runner_btn", "Run Backup Tests", self.run_tests)

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

    def add_config_widgets(self):
        for config, will_run in self.filtered_configs.items():
            def toggle_config_handler(event=None, self=self, config=config):
                if config in self.filtered_configs:
                    self.filtered_configs[config] = not self.filtered_configs[config]
                    App.configs[config] = self.filtered_configs[config]  # Keep main configs in sync
                    BatchArgs.update_config_state(config, self.filtered_configs[config])
                    print(f"Config {config} set to {self.filtered_configs[config]}")
                return True

            var = tk.BooleanVar(value=will_run if will_run is not None else False)
            self.config_vars.append(var)
            checkbutton = Checkbutton(self.sidebar, text=config, variable=var, command=toggle_config_handler)
            self.config_checkbuttons.append(checkbutton)
            self.apply_to_grid(checkbutton, sticky=W)

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
            self.progress_bar.grid_forget()
            self.destroy_grid_element("progress_bar")
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

        self.progress_bar = Progressbar(
            self.config,
            orient=HORIZONTAL,
            length=100,
            mode='determinate'
        )
        self.apply_to_grid(self.progress_bar, sticky=W, column=1)

        def run_async(args) -> None:
            try:
                main(args)
            except Exception as e:
                self.alert("Error", str(e), "error")
            finally:
                self.destroy_progress_bar()

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
        toast = tk.Toplevel(self.master, bg=App.DARK_BG)
        toast.geometry(f'{width}x{height}+{int(x)}+{int(y)}')
        self.container = tk.Frame(toast, bg=App.DARK_BG)
        self.container.pack(fill=tk.BOTH, expand=tk.YES)
        label = tk.Label(
            self.container,
            text=message,
            anchor=tk.NW,
            bg=App.DARK_BG,
            fg='white',
            font=('Helvetica', 12)
        )
        label.grid(row=1, column=1, sticky="NSEW", padx=10, pady=(0, 5))
        
        # Make the window invisible and bring it to front
        toast.attributes('-topmost', True)
#        toast.withdraw()

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
        root.title(" RefacDir ")
        #root.iconbitmap(bitmap=r"icon.ico")
        # icon = PhotoImage(file=os.path.join(assets, "icon.png"))
        # root.iconphoto(False, icon)
        root.geometry("600x400")
        # root.attributes('-fullscreen', True)
        root.resizable(1, 1)
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

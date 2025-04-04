import os
import pytest
import sys
import traceback
from io import StringIO
import threading

import tkinter as tk
from tkinter import ttk
from tkinter.ttk import Frame, Label, Button, Progressbar
from datetime import datetime
from queue import Queue
from typing import Dict, Tuple

from refacdir.utils.translations import I18N

_ = I18N._


class TestResultWindow(tk.Toplevel):
    """Professional test results display window with real-time updates"""
    
    def __init__(self, master):
        super().__init__(master)
        self.title(_("Backup System Verification"))
        self.geometry("800x600")
        self.minsize(600, 400)
        
        # Configure window style
        self.configure(bg='#f0f0f0')
        self.style = ttk.Style()
        self.style.configure('Header.TLabel', font=('Helvetica', 12, 'bold'))
        self.style.configure('Status.TLabel', font=('Helvetica', 10))
        self.style.configure('Summary.TLabel', font=('Helvetica', 11))
        
        # Main container
        self.main_container = Frame(self, padding="10")
        self.main_container.pack(fill=tk.BOTH, expand=True)
        
        # Header section
        self.create_header_section()
        
        # Progress section
        self.create_progress_section()
        
        # Results section
        self.create_results_section()
        
        # Summary section
        self.create_summary_section()
        
        # Control section
        self.create_control_section()
        
        # Initialize state
        self.test_stats = {
            'total': 0,
            'passed': 0,
            'failed': 0,
            'current_file': '',
            'start_time': datetime.now()
        }
        
        self.update_queue = Queue()
        self.start_update_checker()

    def run_tests(self):
        def run_tests_thread():
            try:
                # Store original stdout and cwd to restore later
                original_stdout = sys.stdout
                original_cwd = os.getcwd()
                captured_output = StringIO()
                sys.stdout = captured_output
                
                # Run tests - use normalized paths
                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
                
                # Change to base directory and update Python path
                os.chdir(base_dir)
                if base_dir not in sys.path:
                    sys.path.insert(0, base_dir)
                    
                # Remove any other paths that might interfere
                sys.path = [p for p in sys.path if not p.endswith('simple_image_compare')]
                
                # Use proper directory name for tests
                test_dir = os.path.join(base_dir, "test", "backup")
                if not os.path.exists(test_dir):
                    raise Exception(_("Test directory not found: {0}").format(test_dir))
                
                # Ensure test files directory exists
                test_files_dir = os.path.join(test_dir, "test_files")
                if not os.path.exists(test_files_dir):
                    os.makedirs(test_files_dir)
                
                test_files = [
                    os.path.join(test_dir, "test_hash_manager.py"),
                    os.path.join(test_dir, "test_backup_state.py"),
                    os.path.join(test_dir, "test_backup_source_data.py"),
                    os.path.join(test_dir, "test_backup_transaction.py")
                ]
                
                # Debug info
                self.update_queue.put(("text", (_("Base directory: ") + "{base_dir}\n", "important")))
                self.update_queue.put(("text", (_("Test directory: ") + "{test_dir}\n", "important")))
                self.update_queue.put(("text", (_("Test files directory: ") + "{test_files_dir}\n", "important")))
                self.update_queue.put(("text", (_("Python path: ") + "{sys.path[0]}\n", "important")))
                
                # Verify test files exist
                for test_file in test_files[:]:
                    if not os.path.exists(test_file):
                        error_msg = _("Test file not found: {0}").format(test_file) + "\n"
                        print(error_msg, file=original_stdout)
                        self.update_queue.put(("text", (error_msg, "error")))
                        test_files.remove(test_file)
                    else:
                        self.update_queue.put(("text", (_("Found test file: ") + "{test_file}\n", "important")))
                
                if not test_files:
                    error_msg = _("No test files found!") + "\n"
                    print(error_msg, file=original_stdout)
                    self.update_queue.put(("text", (error_msg, "error")))
                    self.update_queue.put(("done", None))
                    return
                
                total_tests = 0
                current_test = 0
                passed_tests = 0
                failed_tests = 0
                
                # First pass to count tests
                self.update_queue.put(("status", _("Analyzing test suite...")))
                for test_file in test_files:
                    try:
                        class TestCounter:
                            def __init__(self):
                                self.count = 0
                            
                            def pytest_collection_modifyitems(self, items):
                                self.count = len(items)
                        
                        counter = TestCounter()
                        pytest.main(['--collect-only', '-v', test_file], plugins=[counter])
                        
                        if counter.count > 0:
                            total_tests += counter.count
                            message = _("Found {0} tests in {1}").format(counter.count, os.path.basename(test_file))
                            print(message, file=original_stdout)
                            self.update_queue.put(("text", (message + "\n", "important")))
                    except Exception as e:
                        error_msg = _("Error collecting tests from {0}: {1}").format(test_file, str(e)) + "\n"
                        error_trace = traceback.format_exc()
                        print(error_msg + error_trace, file=original_stdout)
                        self.update_queue.put(("text", (error_msg, "error")))
                        self.update_queue.put(("text", (error_trace, "error")))
                        continue
                
                self.progress_bar["maximum"] = total_tests or 1  # Prevent division by zero
                self.update_queue.put(("stats", {
                    'total': total_tests,
                    'passed': 0,
                    'failed': 0
                }))
                
                # Run actual tests
                for test_file in test_files:
                    try:
                        # Update status with current file
                        current_file = os.path.basename(test_file)
                        self.update_queue.put(
                            ("status", _("Running tests from {0}...").format(current_file))
                        )
                        
                        # Add header for test file
                        self.update_queue.put((
                            "text",
                            ("\n" + _("Running tests from {0}:").format(current_file) + "\n", "header")
                        ))
                        
                        class ResultCollector:
                            def __init__(self, update_queue):
                                self.update_queue = update_queue
                            
                            def pytest_runtest_logreport(self, report):
                                nonlocal current_test, passed_tests, failed_tests
                                if report.when == "call":
                                    current_test += 1
                                    
                                    # Update progress
                                    self.update_queue.put(("progress", current_test))
                                    
                                    # Format test name
                                    test_name = report.nodeid.split("::")[-1]
                                    
                                    if report.passed:
                                        passed_tests += 1
                                        self.update_queue.put((
                                            "text",
                                            (f"✓ {test_name}\n", "pass")
                                        ))
                                    elif report.failed:
                                        failed_tests += 1
                                        self.update_queue.put((
                                            "text",
                                            (f"✗ {test_name}\n", "fail")
                                        ))
                                        if report.longrepr:
                                            error_text = str(report.longrepr)
                                            message = "\n" + _("Error in {0}:").format(test_name) + f"\n{error_text}\n"
                                            print(message, file=original_stdout)
                                            self.update_queue.put(("text", (message, "error")))
                                    
                                    # Update statistics
                                    self.update_queue.put(("stats", {
                                        'total': total_tests,
                                        'passed': passed_tests,
                                        'failed': failed_tests
                                    }))
                        
                        # Create plugin instance with access to update queue
                        collector = ResultCollector(self.update_queue)
                        
                        # Run tests with proper config
                        pytest.main(['-v', test_file], plugins=[collector])
                        
                    except Exception as e:
                        error_msg = "\n" + _("Error running tests in {0}: {1}").format(test_file, str(e)) + "\n"
                        error_trace = traceback.format_exc()
                        # Print to both console and results window
                        print(error_msg + error_trace, file=original_stdout)
                        self.update_queue.put(("text", (error_msg, "error")))
                        self.update_queue.put(("text", (error_trace, "error")))
                
                # Restore stdout and cwd
                sys.stdout = original_stdout
                os.chdir(original_cwd)
                
                # Mark as done
                self.update_queue.put(("done", None))
                
            except Exception as e:
                error_msg = "\n" + _("Unexpected error running tests: {0}").format(str(e)) + "\n"
                error_trace = traceback.format_exc()
                # Print to both console and results window
                print(error_msg + error_trace, file=original_stdout)
                self.update_queue.put(("text", (error_msg, "error")))
                self.update_queue.put(("text", (error_trace, "error")))
                self.update_queue.put(("done", None))
                
            finally:
                # Always ensure stdout is restored
                if 'original_stdout' in locals():
                    sys.stdout = original_stdout
        
        # Run tests in separate thread
        threading.Thread(target=run_tests_thread, daemon=True).start()

    def create_header_section(self):
        """Create the header section with title and description"""
        header_frame = Frame(self.main_container, padding="0 0 0 10")
        header_frame.pack(fill=tk.X, pady=(0, 10))
        
        title = Label(header_frame, 
                     text=_("Backup System Verification"), 
                     style='Header.TLabel')
        title.pack(anchor=tk.W)
        
        description = Label(header_frame,
                          text=_("Running comprehensive tests to verify backup system integrity and reliability"),
                          wraplength=700)
        description.pack(anchor=tk.W)
    
    def create_progress_section(self):
        """Create the progress section with status and progress bar"""
        progress_frame = Frame(self.main_container, padding="0 10")
        progress_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Status line
        self.status_label = Label(progress_frame, 
                                text=_("Initializing tests..."),
                                style='Status.TLabel')
        self.status_label.pack(side=tk.TOP, fill=tk.X)
        
        # Progress bar with label
        progress_bar_frame = Frame(progress_frame)
        progress_bar_frame.pack(fill=tk.X, pady=(5, 0))
        
        self.progress_bar = Progressbar(
            progress_bar_frame,
            orient=tk.HORIZONTAL,
            length=300,
            mode='determinate'
        )
        self.progress_bar.pack(side=tk.LEFT, fill=tk.X, expand=True)
        
        self.progress_label = Label(progress_bar_frame, 
                                  text="0%",
                                  width=8)
        self.progress_label.pack(side=tk.LEFT, padx=(10, 0))
    
    def create_results_section(self):
        """Create the scrollable results section"""
        # Results container with border
        results_frame = ttk.LabelFrame(self.main_container, 
                                     text=_("Test Results"),
                                     padding="5")
        results_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 10))
        
        # Scrollable text widget
        self.results_text = tk.Text(
            results_frame,
            wrap=tk.WORD,
            font=('Consolas', 10),
            background='#ffffff',
            height=10,
            state='normal'  # Ensure text is editable
        )
        scrollbar = ttk.Scrollbar(results_frame, 
                                orient=tk.VERTICAL,
                                command=self.results_text.yview)
        self.results_text.configure(yscrollcommand=scrollbar.set)
        
        # Enable text selection and copying
        self.results_text.bind('<Control-c>', lambda e: self.copy_selected_text())
        self.results_text.bind('<Control-a>', lambda e: self.select_all_text())
        
        self.results_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)
        
        # Configure text tags
        self.results_text.tag_configure("pass", foreground="dark green")
        self.results_text.tag_configure("fail", foreground="red")
        self.results_text.tag_configure("error", foreground="red", underline=1)
        self.results_text.tag_configure("header", font=('Consolas', 10, 'bold'))
        self.results_text.tag_configure("important", background="#fff3cd")
    
    def create_summary_section(self):
        """Create the test summary section"""
        self.summary_frame = ttk.LabelFrame(self.main_container,
                                          text=_("Summary"),
                                          padding="5")
        self.summary_frame.pack(fill=tk.X, pady=(0, 10))
        
        # Grid for test statistics
        self.total_label = Label(self.summary_frame, 
                               text=_("Total Tests: 0"),
                               style='Summary.TLabel',
                               padding="0 5")
        self.total_label.grid(row=0, column=0, padx=5)
        
        self.passed_label = Label(self.summary_frame,
                                text=_("Passed: 0"),
                                style='Summary.TLabel',
                                padding="0 5",
                                foreground='dark green')
        self.passed_label.grid(row=0, column=1, padx=5)
        
        self.failed_label = Label(self.summary_frame,
                                text=_("Failed: 0"),
                                style='Summary.TLabel',
                                padding="0 5",
                                foreground='red')
        self.failed_label.grid(row=0, column=2, padx=5)
        
        self.time_label = Label(self.summary_frame,
                              text=_("Time: 0:00"),
                              style='Summary.TLabel',
                              padding="0 5")
        self.time_label.grid(row=0, column=3, padx=5)
    
    def create_control_section(self):
        """Create the control buttons section"""
        control_frame = Frame(self.main_container)
        control_frame.pack(fill=tk.X)
        
        self.close_button = Button(
            control_frame,
            text=_("Close"),
            command=self.destroy,
            width=15
        )
        self.close_button.pack(side=tk.RIGHT)
        
        self.save_button = Button(
            control_frame,
            text=_("Save Results"),
            command=self.save_results,
            width=15
        )
        self.save_button.pack(side=tk.RIGHT, padx=10)
    
    def start_update_checker(self):
        """Start checking for updates from the test runner thread"""
        def check_queue():
            try:
                while True:
                    msg_type, msg = self.update_queue.get_nowait()
                    self.process_message(msg_type, msg)
            except:
                pass
            
            # Update time elapsed
            if not hasattr(self, 'is_complete'):
                elapsed = datetime.now() - self.test_stats['start_time']
                minutes = elapsed.seconds // 60
                seconds = elapsed.seconds % 60
                self.time_label.config(text=_("Time: ") + "f{minutes}:{seconds:02d}")
            
            self.after(100, check_queue)
        
        self.after(100, check_queue)
    
    def process_message(self, msg_type: str, msg: any):
        """Process incoming messages from the test runner"""
        if msg_type == "progress":
            self.update_progress(msg)
        elif msg_type == "text":
            text, tags = msg
            self.append_text(text, tags)
        elif msg_type == "status":
            self.status_label.config(text=msg)
        elif msg_type == "stats":
            self.update_stats(msg)
        elif msg_type == "done":
            self.test_complete()
    
    def update_progress(self, value: int):
        """Update progress bar and percentage"""
        if hasattr(self.progress_bar, "maximum"):
            percentage = int((value / self.progress_bar["maximum"]) * 100)
            self.progress_bar["value"] = value
            self.progress_label.config(text=f"{percentage}%")
    
    def update_stats(self, stats: Dict[str, int]):
        """Update test statistics"""
        self.test_stats.update(stats)
        self.total_label.config(text=_("Total Tests: ").format(stats['total']))
        self.passed_label.config(text=_("Passed: ").format(stats['passed']))
        self.failed_label.config(text=_("Failed: ").format(stats['failed']))
    
    def append_text(self, text: str, tags: str = None):
        """Append text to results with optional tags"""
        self.results_text.insert(tk.END, text, tags)
        self.results_text.see(tk.END)
    
    def test_complete(self):
        """Handle test completion"""
        self.is_complete = True
        elapsed = datetime.now() - self.test_stats['start_time']
        minutes = elapsed.seconds // 60
        seconds = elapsed.seconds % 60
        
        # Add summary to results
        self.append_text("\n" + "="*50 + "\n", "header")
        self.append_text(_("Test Run Complete - ") + f"{minutes}:{seconds:02d}\n", "header")
        self.append_text(_("Total Tests: ") + f"{self.test_stats['total']}\n")
        self.append_text(_("Passed: ") + f"{self.test_stats['passed']}\n", "pass")
        self.append_text(_("Failed: ") + f"{self.test_stats['failed']}\n", "fail" if self.test_stats['failed'] > 0 else None)
        
        # Update status
        status = _("All tests passed successfully!") if self.test_stats['failed'] == 0 else _("Some tests failed - check results")
        self.status_label.config(text=status)
        
        # Enable save button
        self.save_button.state(['!disabled'])
    
    def save_results(self):
        """Save test results to a file"""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"backup_test_results_{timestamp}.txt"
        
        try:
            with open(filename, 'w') as f:
                f.write(self.results_text.get("1.0", tk.END))
            self.append_text("\n" + _("Results saved to ") + f"{filename}\n", "important")
        except Exception as e:
            self.append_text("\n" + _("Error saving results: ") + f"{str(e)}\n", "error")

    def copy_selected_text(self):
        """Copy selected text to clipboard"""
        try:
            selected_text = self.results_text.get(tk.SEL_FIRST, tk.SEL_LAST)
            self.clipboard_clear()
            self.clipboard_append(selected_text)
        except tk.TclError:  # No selection
            pass

    def select_all_text(self, event=None):
        """Select all text in the results window"""
        self.results_text.tag_add(tk.SEL, "1.0", tk.END)
        self.results_text.mark_set(tk.INSERT, "1.0")
        self.results_text.see(tk.INSERT)
        return 'break'  # Prevent default handling

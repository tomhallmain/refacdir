import asyncio
import datetime
import os
import re
import shutil
import sys
import threading

if sys.platform == "win32":
    import win32file
    import pywintypes
else:
    pass # TODO

class Utils:
    @staticmethod
    def extract_substring(text, pattern):
        result = re.search(pattern, text)    
        if result:
            return result.group()
        return ""

    @staticmethod
    def start_thread(callable, use_asyncio=True, args=None):
        if use_asyncio:
            def asyncio_wrapper():
                asyncio.run(callable())

            target_func = asyncio_wrapper
        else:
            target_func = callable

        if args:
            thread = threading.Thread(target=target_func, args=args)
        else:
            thread = threading.Thread(target=target_func)

        thread.daemon = True  # Daemon threads exit when the main process does
        thread.start()

    @staticmethod
    def periodic(run_obj, sleep_attr="", run_attr=None):
        def scheduler(fcn):
            async def wrapper(*args, **kwargs):
                while True:
                    asyncio.create_task(fcn(*args, **kwargs))
                    period = int(run_obj) if isinstance(run_obj, int) else getattr(run_obj, sleep_attr)
                    await asyncio.sleep(period)
                    if run_obj and run_attr and not getattr(run_obj, run_attr):
                        print(f"Ending periodic task: {run_obj.__name__}.{run_attr} = False")
                        break
            return wrapper
        return scheduler

    @staticmethod
    def fix_path(path):
        path = path.replace("{{USER_HOME}}", os.path.expanduser("~"))
        if sys.platform=="win32":
            path = path.replace("/", "\\")
        else:
            path = path.replace("\\", "/")
        return os.path.normpath(path)

    @staticmethod
    def string_distance(s, t):
        # create two work vectors of integer distances
        v0 = [0] * (len(t) + 1)
        v1 = [0] * (len(t) + 1)

        # initialize v0 (the previous row of distances)
        # this row is A[0][i]: edit distance from an empty s to t;
        # that distance is the number of characters to append to  s to make t.
        for i in range(len(t) + 1):
            v0[i] = i

        for i in range(len(s)):
            # calculate v1 (current row distances) from the previous row v0

            # first element of v1 is A[i + 1][0]
            # edit distance is delete (i + 1) chars from s to match empty t
            v1[0] = i + 1

            for j in range(len(t)):
                # calculating costs for A[i + 1][j + 1]
                deletion_cost = v0[j + 1] + 1
                insertion_cost = v1[j] + 1
                substitution_cost = v0[j] if s[i] == t[j] else v0[j] + 1

                v1[j + 1] = min(deletion_cost, insertion_cost, substitution_cost)
            # copy v1 (current row) to v0 (previous row) for next iteration
            v0,v1 = v1,v0
        # after the last swap, the results of v1 are now in v0
        return v0[len(t)]

    @staticmethod
    def identify_string_differences(s, t, unicode_escape=False):
        len_s = len(s)
        len_t = len(t)
        if len_s == 0:
            if len_s == 0:
                return None
            return f"EXPECTED:\n[{s}]\nACTUAL:\n[]"
        elif len_t == 0:
            return f"EXPECTED:\n[]\nACTUAL:\n[{t}]"
        out_s = ""
        out_t = ""
        max_len = max(len_s, len_t)
        has_found_one_difference = False
        has_found_difference = False
        to_close_s = False
        to_close_t = False
        for i in range(max_len):
            c_s = None
            c_t = None
            if i < len_s:
                c_s = s[i]
            if i < len_t:
                c_t = t[i]
            if c_s is not None and c_t is not None:
                if c_s == c_t:
                    if has_found_difference:
                        has_found_difference = False
                        out_s += "]"
                        out_t += "]"
                    out_s += c_s
                    out_t += c_t
                else:
                    if not has_found_difference:
                        has_found_difference = True
                        has_found_one_difference = True
                        out_s += "["
                        out_t += "["
                    if unicode_escape:
                        out_s += repr(c_s)
                        out_t += repr(c_t)
                    else:
                        out_s += c_s
                        out_t += c_t
            elif c_s is not None:
                if not has_found_difference:
                    has_found_difference = True
                    has_found_one_difference = True
                    to_close_s = True
                    out_s += "["
                if unicode_escape:
                    out_s += repr(c_s)
                else:
                    out_s += c_s
            elif c_t is not None:
                if not has_found_difference:
                    has_found_difference = True
                    has_found_one_difference = True
                    to_close_t = True
                    out_t += "["
                if unicode_escape:
                    out_t += repr(c_t)
                else:
                    out_t += c_t

        if not has_found_one_difference:
            Utils.debug_print("No differences were found between the two strings!", "utils")
            return None

        if to_close_s:
            out_s += "]"
        if to_close_t:
            out_t += "]"

        return f"EXPECTED:\n{out_s}\nACTUAL:\n{out_t}"

    @staticmethod
    def longest_common_substring(str1, str2):
        m = [[0] * (1 + len(str2)) for _ in range(1 + len(str1))]
        longest, x_longest = 0, 0
        for x in range(1, 1 + len(str1)):
            for y in range(1, 1 + len(str2)):
                if str1[x - 1] == str2[y - 1]:
                    m[x][y] = m[x - 1][y - 1] + 1
                    if m[x][y] > longest:
                        longest = m[x][y]
                        x_longest = x
                else:
                    m[x][y] = 0
        return str1[x_longest - longest: x_longest]

    @staticmethod
    def shared_elements(list1, list2):
       return any(item in list1 for item in list2)

    @staticmethod
    def subtract_list(original, subtracted):
        return list(set(original) - set(subtracted))

    @staticmethod
    def get_list_from_string(s, sep=","):
        if s is None or s.strip() == "":
            return []
        return [x.strip() for x in s.split(sep)]

    @staticmethod
    def get_from_dict(d, key, default_value=None):
        try:
            return d[key]
        except KeyError:
            return default_value

    @staticmethod
    def change_fileinfo_times(path, creation_datetime, modification_datetime=None):
        if modification_datetime is None:
            modification_datetime = creation_datetime
        if not isinstance(creation_datetime, datetime.datetime):
            raise Exception(f"Invalid creation time: must be datetime object, got object of type {type(creation_datetime)}")
        if not isinstance(modification_datetime, datetime.datetime):
            raise Exception(f"Invalid creation time: must be datetime object, got object of type {type(modification_datetime)}")

        # Unfortunately the os module doesn't update the creation time, only the modification time, but both are required for the call here
        os.utime(path, (creation_datetime.timestamp(), modification_datetime.timestamp()))

        # path: your file path
        # ctime: Unix timestamp

        # open file and get the handle of file
        # API: http://timgolden.me.uk/pywin32-docs/win32file__CreateFile_meth.html
        handle = win32file.CreateFile(
            path,                          # file path
            win32file.GENERIC_WRITE,       # must opened with GENERIC_WRITE access
            0,
            None,
            win32file.OPEN_EXISTING,
            0,
            0
        )

        # create a PyTime object
        # API: http://timgolden.me.uk/pywin32-docs/pywintypes__Time_meth.html
        PyTime = pywintypes.Time(creation_datetime.timestamp())

        # reset the create time of file
        # API: http://timgolden.me.uk/pywin32-docs/win32file__SetFileTime_meth.html
        win32file.SetFileTime(
            handle,
            PyTime
        )

    @staticmethod
    def move(source_path, target_path):
        stat_obj = os.stat(source_path)
        creation_datetime = datetime.datetime.fromtimestamp(stat_obj.st_ctime)
        modification_datetime = datetime.datetime.fromtimestamp(stat_obj.st_mtime)
        shutil.move(source_path, target_path)
        if sys.platform == "win32":
            Utils.change_fileinfo_times(target_path, creation_datetime, modification_datetime)
        else:
            pass # TODO

    @staticmethod
    def copy(source_path, target_path):
        stat_obj = os.stat(source_path)
        creation_datetime = datetime.datetime.fromtimestamp(stat_obj.st_ctime)
        modification_datetime = datetime.datetime.fromtimestamp(stat_obj.st_mtime)
        shutil.copy2(source_path, target_path)
        if sys.platform == "win32":
            Utils.change_fileinfo_times(target_path, creation_datetime, modification_datetime)
        else:
            pass # TODO

    @staticmethod
    def stringify_list(l, one_line=False, do_print=True):
        s = "["
        for item in l:
            if not one_line: s += "\n    "
            s += f"{item}, "
        if len(l) > 0:
            s = s[:-2]
            if not one_line: s += "\n"
        s += "]"
        if do_print: print(s)
        return s

    @staticmethod
    def stringify_dict(d, one_line=False, do_print=True):
        s = "{"
        for key, value in d.items():
            if not one_line: s += "\n    "
            s += f"{key} : {value}, "
        if len(d) > 0:
            s = s[:-2]
            if not one_line: s += "\n"
        s += "]"
        if do_print: print(s)
        return s

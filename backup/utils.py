import datetime
import os
import shutil

import win32file
import pywintypes

def change_fileinfo_times(path, creation_datetime, modification_datetime=None):
    if modification_datetime is None:
        modification_datetime = creation_datetime
    if not isinstance(creation_datetime, datetime):
        raise Exception(f"Invalid creation time: must be datetime object, got object of type {type(creation_datetime)}")
    if not isinstance(modification_datetime, datetime):
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


def move(source_path, target_path):
    stat_obj = os.stat(source_path)
    creation_datetime = datetime.datetime.fromtimestamp(stat_obj.st_ctime)
    modification_datetime = datetime.datetime.fromtimestamp(stat_obj.st_mtime)
    shutil.move(source_path, target_path)
    change_fileinfo_times(target_path, creation_datetime, modification_datetime)

def copy(source_path, target_path):
    stat_obj = os.stat(source_path)
    creation_datetime = datetime.datetime.fromtimestamp(stat_obj.st_ctime)
    modification_datetime = datetime.datetime.fromtimestamp(stat_obj.st_mtime)
    shutil.copy2(source_path, target_path)
    change_fileinfo_times(target_path, creation_datetime, modification_datetime)

import os
import shutil
from pathlib import Path
import hashlib

def create_test_file(path, content="test content"):
    """Create a test file with given content"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        f.write(content)

def create_test_structure(base_path, structure):
    """Create a test directory structure from a dictionary
    Example structure:
    {
        'dir1': {
            'file1.txt': 'content1',
            'subdir': {
                'file2.txt': 'content2'
            }
        },
        'file3.txt': 'content3'
    }
    """
    for name, content in structure.items():
        path = os.path.join(base_path, name)
        if isinstance(content, dict):
            os.makedirs(path, exist_ok=True)
            create_test_structure(path, content)
        else:
            create_test_file(path, content)

def calculate_file_hash(path):
    """Calculate SHA256 hash of a file"""
    sha256 = hashlib.sha256()
    with open(path, 'rb') as f:
        while True:
            data = f.read(65536)
            if not data:
                break
            sha256.update(data)
    return sha256.hexdigest()

def compare_directories(dir1, dir2, ignore=None):
    """Compare two directories recursively
    Returns (is_identical, differences)
    where differences is a list of (path, type, details) tuples
    """
    differences = []
    dir1_files = set()
    dir2_files = set()

    for root, _, files in os.walk(dir1):
        rel_root = os.path.relpath(root, dir1)
        for f in files:
            rel_path = os.path.join(rel_root, f)
            if ignore and any(p in rel_path for p in ignore):
                continue
            dir1_files.add(rel_path)
            
    for root, _, files in os.walk(dir2):
        rel_root = os.path.relpath(root, dir2)
        for f in files:
            rel_path = os.path.join(rel_root, f)
            if ignore and any(p in rel_path for p in ignore):
                continue
            dir2_files.add(rel_path)

    # Check for missing files
    for f in dir1_files - dir2_files:
        differences.append((f, 'missing_in_target', None))
    for f in dir2_files - dir1_files:
        differences.append((f, 'missing_in_source', None))

    # Check content of files present in both
    for f in dir1_files & dir2_files:
        file1 = os.path.join(dir1, f)
        file2 = os.path.join(dir2, f)
        
        if os.path.getsize(file1) != os.path.getsize(file2):
            differences.append((f, 'size_mismatch', 
                             f'Size1: {os.path.getsize(file1)}, Size2: {os.path.getsize(file2)}'))
            continue
            
        hash1 = calculate_file_hash(file1)
        hash2 = calculate_file_hash(file2)
        if hash1 != hash2:
            differences.append((f, 'content_mismatch',
                             f'Hash1: {hash1}, Hash2: {hash2}'))

    return len(differences) == 0, differences

def clean_test_dirs(*dirs):
    """Clean up test directories"""
    for d in dirs:
        if os.path.exists(d):
            shutil.rmtree(d) 
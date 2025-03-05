import os
import pytest
import shutil
import time
from pathlib import Path

from refacdir.backup.backup_manager import BackupManager
from refacdir.backup.backup_mapping import BackupMapping, BackupMode, FileMode, HashMode
from .test_backup_helper import create_test_structure, compare_directories, clean_test_dirs

# Test directory structure
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_DIR = os.path.join(TEST_DIR, 'source')
TARGET_DIR = os.path.join(TEST_DIR, 'target')

@pytest.fixture(autouse=True)
def setup_teardown():
    """Setup and teardown for each test"""
    clean_test_dirs(SOURCE_DIR, TARGET_DIR)
    yield
    clean_test_dirs(SOURCE_DIR, TARGET_DIR)

def test_basic_push():
    """Test basic PUSH mode with simple files"""
    structure = {
        'file1.txt': 'content1',
        'dir1': {
            'file2.txt': 'content2',
            'subdir': {
                'file3.txt': 'content3'
            }
        }
    }
    create_test_structure(SOURCE_DIR, structure)
    
    mapping = BackupMapping(
        name="test",
        source_dir=SOURCE_DIR,
        target_dir=TARGET_DIR,
        mode=BackupMode.PUSH
    )
    manager = BackupManager(mappings=[mapping], skip_confirm=True)
    manager.run()
    
    identical, diffs = compare_directories(SOURCE_DIR, TARGET_DIR)
    assert identical, f"Directories should be identical, differences: {diffs}"

def test_push_and_remove():
    """Test PUSH_AND_REMOVE mode"""
    structure = {
        'file1.txt': 'content1',
        'dir1': {'file2.txt': 'content2'}
    }
    create_test_structure(SOURCE_DIR, structure)
    
    mapping = BackupMapping(
        name="test",
        source_dir=SOURCE_DIR,
        target_dir=TARGET_DIR,
        mode=BackupMode.PUSH_AND_REMOVE
    )
    manager = BackupManager(mappings=[mapping], skip_confirm=True)
    manager.run()
    
    # Check target has all files
    identical, diffs = compare_directories(SOURCE_DIR, TARGET_DIR)
    assert identical, f"Target should have all files, differences: {diffs}"
    
    # Source should be empty (except for backup data file)
    source_files = [f for f in os.listdir(SOURCE_DIR) if not f.endswith('.pkl')]
    assert len(source_files) == 0, f"Source directory should be empty, found: {source_files}"

def test_mirror():
    """Test MIRROR mode with file deletions in source"""
    # Initial structure
    structure = {
        'keep.txt': 'keep',
        'delete.txt': 'delete',
        'dir1': {
            'keep2.txt': 'keep2',
            'delete2.txt': 'delete2'
        }
    }
    create_test_structure(SOURCE_DIR, structure)
    
    # First backup
    mapping = BackupMapping(
        name="test",
        source_dir=SOURCE_DIR,
        target_dir=TARGET_DIR,
        mode=BackupMode.MIRROR
    )
    manager = BackupManager(mappings=[mapping], skip_confirm=True)
    manager.run()
    
    # Delete some files from source
    os.remove(os.path.join(SOURCE_DIR, 'delete.txt'))
    os.remove(os.path.join(SOURCE_DIR, 'dir1', 'delete2.txt'))
    
    # Run backup again
    manager.run()
    
    # Check directories match
    identical, diffs = compare_directories(SOURCE_DIR, TARGET_DIR)
    assert identical, f"Directories should be identical after mirror, differences: {diffs}"
    
    # Verify deleted files are gone from target
    assert not os.path.exists(os.path.join(TARGET_DIR, 'delete.txt'))
    assert not os.path.exists(os.path.join(TARGET_DIR, 'dir1', 'delete2.txt'))

def test_file_types():
    """Test file type filtering"""
    structure = {
        'doc1.txt': 'text',
        'img1.jpg': 'image',
        'dir1': {
            'doc2.txt': 'text2',
            'img2.jpg': 'image2'
        }
    }
    create_test_structure(SOURCE_DIR, structure)
    
    mapping = BackupMapping(
        name="test",
        source_dir=SOURCE_DIR,
        target_dir=TARGET_DIR,
        file_types=['.txt'],
        mode=BackupMode.PUSH
    )
    manager = BackupManager(mappings=[mapping], skip_confirm=True)
    manager.run()
    
    # Only .txt files should exist in target
    for root, _, files in os.walk(TARGET_DIR):
        for f in files:
            assert f.endswith('.txt'), f"Found non-txt file in target: {f}"

def test_exclude_dirs():
    """Test directory exclusion"""
    structure = {
        'file1.txt': 'content1',
        'exclude_me': {
            'file2.txt': 'content2'
        },
        'keep_me': {
            'file3.txt': 'content3'
        }
    }
    create_test_structure(SOURCE_DIR, structure)
    
    mapping = BackupMapping(
        name="test",
        source_dir=SOURCE_DIR,
        target_dir=TARGET_DIR,
        exclude_dirs=[os.path.join(SOURCE_DIR, 'exclude_me')],
        mode=BackupMode.PUSH
    )
    manager = BackupManager(mappings=[mapping], skip_confirm=True)
    manager.run()
    
    assert os.path.exists(os.path.join(TARGET_DIR, 'keep_me', 'file3.txt'))
    assert not os.path.exists(os.path.join(TARGET_DIR, 'exclude_me'))

def test_duplicate_handling():
    """Test duplicate file handling"""
    # Create identical files in different locations
    structure = {
        'dir1': {'file.txt': 'same content'},
        'dir2': {'file.txt': 'same content'},
        'dir3': {'different.txt': 'different content'}
    }
    create_test_structure(SOURCE_DIR, structure)
    
    mapping = BackupMapping(
        name="test",
        source_dir=SOURCE_DIR,
        target_dir=TARGET_DIR,
        mode=BackupMode.PUSH_DUPLICATES,
        hash_mode=HashMode.SHA256
    )
    manager = BackupManager(mappings=[mapping], skip_confirm=True, warn_duplicates=True)
    manager.run()
    
    # Verify only one copy of the duplicate file was backed up
    duplicate_count = 0
    for root, _, files in os.walk(TARGET_DIR):
        for f in files:
            if f == 'file.txt':
                duplicate_count += 1
    assert duplicate_count == 1, "Expected only one copy of duplicate file"

def test_file_mode_dirs_only():
    """Test DIRS_ONLY file mode"""
    structure = {
        'file1.txt': 'content1',
        'dir1': {
            'file2.txt': 'content2',
            'subdir': {}
        }
    }
    create_test_structure(SOURCE_DIR, structure)
    
    mapping = BackupMapping(
        name="test",
        source_dir=SOURCE_DIR,
        target_dir=TARGET_DIR,
        mode=BackupMode.PUSH,
        file_mode=FileMode.DIRS_ONLY
    )
    manager = BackupManager(mappings=[mapping], skip_confirm=True)
    manager.run()
    
    # Only directories should exist in target
    assert os.path.exists(os.path.join(TARGET_DIR, 'dir1'))
    assert os.path.exists(os.path.join(TARGET_DIR, 'dir1', 'subdir'))
    assert not os.path.exists(os.path.join(TARGET_DIR, 'file1.txt'))
    assert not os.path.exists(os.path.join(TARGET_DIR, 'dir1', 'file2.txt'))

def test_error_handling():
    """Test error handling for various scenarios"""
    structure = {'file1.txt': 'content1'}
    create_test_structure(SOURCE_DIR, structure)
    
    # Make target directory read-only
    os.makedirs(TARGET_DIR)
    os.chmod(TARGET_DIR, 0o444)
    
    mapping = BackupMapping(
        name="test",
        source_dir=SOURCE_DIR,
        target_dir=TARGET_DIR,
        mode=BackupMode.PUSH
    )
    manager = BackupManager(mappings=[mapping], skip_confirm=True)
    manager.run()
    
    # Check that failure was recorded
    assert len(mapping.failures) > 0
    
    # Restore permissions for cleanup
    os.chmod(TARGET_DIR, 0o777)

def test_multiple_backups():
    """Test multiple backup mappings in one manager"""
    structure1 = {'file1.txt': 'content1'}
    structure2 = {'file2.txt': 'content2'}
    
    source1 = os.path.join(SOURCE_DIR, 'source1')
    source2 = os.path.join(SOURCE_DIR, 'source2')
    target1 = os.path.join(TARGET_DIR, 'target1')
    target2 = os.path.join(TARGET_DIR, 'target2')
    
    create_test_structure(source1, structure1)
    create_test_structure(source2, structure2)
    
    mappings = [
        BackupMapping(
            name="test1",
            source_dir=source1,
            target_dir=target1,
            mode=BackupMode.PUSH
        ),
        BackupMapping(
            name="test2",
            source_dir=source2,
            target_dir=target2,
            mode=BackupMode.PUSH
        )
    ]
    
    manager = BackupManager(mappings=mappings, skip_confirm=True)
    manager.run()
    
    identical1, diffs1 = compare_directories(source1, target1)
    identical2, diffs2 = compare_directories(source2, target2)
    
    assert identical1, f"First backup differences: {diffs1}"
    assert identical2, f"Second backup differences: {diffs2}"

def test_atomic_operations():
    """Test atomic operations and verification"""
    # Create test structure
    structure = {'file1.txt': 'content1'}
    create_test_structure(SOURCE_DIR, structure)
    
    source_file = os.path.join(SOURCE_DIR, 'file1.txt')
    
    # Create a mapping that will use atomic operations
    mapping = BackupMapping(
        name="test",
        source_dir=SOURCE_DIR,
        target_dir=TARGET_DIR,
        mode=BackupMode.PUSH
    )
    
    # Run backup
    manager = BackupManager(mappings=[mapping], skip_confirm=True)
    manager.run()
    
    # Verify target file exists and matches
    target_file = os.path.join(TARGET_DIR, 'file1.txt')
    assert os.path.exists(target_file), "Target file should exist"
    
    # Verify no temporary files were left behind
    temp_files = [f for f in os.listdir(TARGET_DIR) if '.tmp' in f]
    assert len(temp_files) == 0, "No temporary files should remain"
    
    # Try to corrupt target file during copy
    def corrupt_copy(src, dst):
        """Simulate a corrupted copy operation"""
        with open(dst, 'w') as f:
            f.write('corrupted content')
        return False, "Simulated corruption"
    
    # Create new test file
    with open(os.path.join(SOURCE_DIR, 'file2.txt'), 'w') as f:
        f.write('content2')
    
    # Try backup with corrupted copy - should fail safely
    mapping._move_file(
        os.path.join(SOURCE_DIR, 'file2.txt'),
        move_func=corrupt_copy,
        test=False
    )
    
    # Verify the failed copy didn't leave any traces
    assert not os.path.exists(os.path.join(TARGET_DIR, 'file2.txt')), \
        "Corrupted file should not exist in target"
    temp_files = [f for f in os.listdir(TARGET_DIR) if '.tmp' in f]
    assert len(temp_files) == 0, "No temporary files should remain after failed copy"
    
    # Verify original files are unchanged
    with open(os.path.join(SOURCE_DIR, 'file2.txt'), 'r') as f:
        assert f.read() == 'content2', "Source file should be unchanged" 
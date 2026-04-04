import os
import sys
import pytest
import shutil
import time
from pathlib import Path

from refacdir.backup.backup_manager import BackupManager
from refacdir.backup.backup_mapping import BackupMapping, BackupMode, BackupTransaction, FileMode, HashMode
from refacdir.backup.backup_source_data import BackupSourceData
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
    manager = BackupManager(mappings=[mapping], skip_confirm=True, test=False)
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
    manager = BackupManager(mappings=[mapping], skip_confirm=True, test=False)
    manager.run()
    
    # Target should have the same file contents as the source had before the move
    assert os.path.isfile(os.path.join(TARGET_DIR, 'file1.txt'))
    assert open(os.path.join(TARGET_DIR, 'file1.txt'), encoding='utf-8').read() == 'content1'
    assert os.path.isfile(os.path.join(TARGET_DIR, 'dir1', 'file2.txt'))
    assert open(os.path.join(TARGET_DIR, 'dir1', 'file2.txt'), encoding='utf-8').read() == 'content2'

    # Source should have no user data files left (metadata pickle may remain)
    remaining = []
    for root, _, files in os.walk(SOURCE_DIR):
        for f in files:
            if f != BackupSourceData.FILEPATH:
                remaining.append(os.path.join(root, f))
    assert len(remaining) == 0, f"Source should have no user files left, found: {remaining}"

def test_mirror_duplicates_mode():
    """MIRROR_DUPLICATES should sync target to source like MIRROR (smoke test)."""
    structure = {
        'a.txt': 'a',
        'b.txt': 'b',
    }
    create_test_structure(SOURCE_DIR, structure)
    mapping = BackupMapping(
        name="test",
        source_dir=SOURCE_DIR,
        target_dir=TARGET_DIR,
        mode=BackupMode.MIRROR_DUPLICATES,
    )
    manager = BackupManager(mappings=[mapping], skip_confirm=True, test=False)
    manager.run()
    os.remove(os.path.join(SOURCE_DIR, 'b.txt'))
    manager.run()
    identical, diffs = compare_directories(
        SOURCE_DIR, TARGET_DIR, ignore=['backup_mapping_data.pkl', '.backup_data', 'backup_metadata']
    )
    assert identical, diffs
    assert not os.path.exists(os.path.join(TARGET_DIR, 'b.txt'))


def test_exclude_removal_dirs_with_push_and_remove():
    """Files under exclude_removal_dirs are copied but not deleted from source."""
    structure = {
        'root.txt': 'root',
        'preserve_me': {'kept.txt': 'kept'},
    }
    create_test_structure(SOURCE_DIR, structure)
    preserve = os.path.join(SOURCE_DIR, 'preserve_me')
    mapping = BackupMapping(
        name="test",
        source_dir=SOURCE_DIR,
        target_dir=TARGET_DIR,
        mode=BackupMode.PUSH_AND_REMOVE,
        exclude_removal_dirs=[preserve],
    )
    manager = BackupManager(mappings=[mapping], skip_confirm=True, test=False)
    manager.run()
    assert os.path.isfile(os.path.join(TARGET_DIR, 'root.txt'))
    assert os.path.isfile(os.path.join(TARGET_DIR, 'preserve_me', 'kept.txt'))
    assert not os.path.exists(os.path.join(SOURCE_DIR, 'root.txt'))
    assert os.path.isfile(os.path.join(SOURCE_DIR, 'preserve_me', 'kept.txt'))


def test_will_run_false_skips_mapping():
    """Mappings with will_run=False are not executed."""
    s1 = os.path.join(SOURCE_DIR, 's1')
    s2 = os.path.join(SOURCE_DIR, 's2')
    t1 = os.path.join(TARGET_DIR, 't1')
    t2 = os.path.join(TARGET_DIR, 't2')
    create_test_structure(s1, {'a.txt': 'a'})
    create_test_structure(s2, {'b.txt': 'b'})
    m1 = BackupMapping(
        name="run",
        source_dir=s1,
        target_dir=t1,
        mode=BackupMode.PUSH,
        will_run=True,
    )
    m2 = BackupMapping(
        name="skip",
        source_dir=s2,
        target_dir=t2,
        mode=BackupMode.PUSH,
        will_run=False,
    )
    manager = BackupManager(mappings=[m1, m2], skip_confirm=True, test=False)
    manager.run()
    assert os.path.isfile(os.path.join(t1, 'a.txt'))
    assert not os.path.isfile(os.path.join(t2, 'b.txt'))


def test_manager_dry_run_leaves_target_empty():
    """With test=True, BackupManager performs no file copies."""
    create_test_structure(SOURCE_DIR, {'only.txt': 'x'})
    mapping = BackupMapping(
        name="test",
        source_dir=SOURCE_DIR,
        target_dir=TARGET_DIR,
        mode=BackupMode.PUSH,
    )
    manager = BackupManager(mappings=[mapping], skip_confirm=True, test=True)
    manager.run()
    assert not os.path.exists(os.path.join(TARGET_DIR, 'only.txt'))


def test_mirror_removes_file_that_exists_only_on_target():
    """Stale removal: files on target with no counterpart on source are deleted."""
    create_test_structure(SOURCE_DIR, {'synced.txt': 'same'})
    os.makedirs(TARGET_DIR, exist_ok=True)
    with open(os.path.join(TARGET_DIR, 'synced.txt'), 'w', encoding='utf-8') as f:
        f.write('same')
    with open(os.path.join(TARGET_DIR, 'target_only.txt'), 'w', encoding='utf-8') as f:
        f.write('orphan')
    mapping = BackupMapping(
        name="test",
        source_dir=SOURCE_DIR,
        target_dir=TARGET_DIR,
        mode=BackupMode.MIRROR,
    )
    manager = BackupManager(mappings=[mapping], skip_confirm=True, test=False)
    manager.run()
    assert os.path.isfile(os.path.join(TARGET_DIR, 'synced.txt'))
    assert not os.path.isfile(os.path.join(TARGET_DIR, 'target_only.txt'))


def test_mirror_dirs_only_leaves_stray_target_files():
    """
    With FileMode.DIRS_ONLY, _is_file_excluded is true for every file path, so
    _mirror_remove_stale skips removing loose files on the target (they look 'excluded').
    Directory structure still syncs. Documents current coupling; change mapping if removal is desired.
    """
    structure = {'dir1': {'subdir': {}}}
    create_test_structure(SOURCE_DIR, structure)
    os.makedirs(TARGET_DIR, exist_ok=True)
    with open(os.path.join(TARGET_DIR, 'loose.txt'), 'w', encoding='utf-8') as f:
        f.write('x')
    mapping = BackupMapping(
        name="test",
        source_dir=SOURCE_DIR,
        target_dir=TARGET_DIR,
        mode=BackupMode.MIRROR,
        file_mode=FileMode.DIRS_ONLY,
    )
    manager = BackupManager(mappings=[mapping], skip_confirm=True, test=False)
    manager.run()
    assert os.path.isdir(os.path.join(TARGET_DIR, 'dir1', 'subdir'))
    assert os.path.isfile(os.path.join(TARGET_DIR, 'loose.txt'))


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
    manager = BackupManager(mappings=[mapping], skip_confirm=True, test=False)
    manager.run()
    
    # Delete some files from source
    os.remove(os.path.join(SOURCE_DIR, 'delete.txt'))
    os.remove(os.path.join(SOURCE_DIR, 'dir1', 'delete2.txt'))
    
    # Run backup again
    manager.run()
    
    # Ignore source-only metadata produced by BackupSourceData.save during mirror
    identical, diffs = compare_directories(
        SOURCE_DIR, TARGET_DIR, ignore=['backup_mapping_data.pkl', '.backup_data', 'backup_metadata']
    )
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
    manager = BackupManager(mappings=[mapping], skip_confirm=True, test=False)
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
    manager = BackupManager(mappings=[mapping], skip_confirm=True, test=False)
    manager.run()
    
    assert os.path.exists(os.path.join(TARGET_DIR, 'keep_me', 'file3.txt'))
    assert not os.path.exists(os.path.join(TARGET_DIR, 'exclude_me'))

def test_duplicate_handling():
    """Test duplicate file handling (same bytes in two paths; both paths exist on target)."""
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
    manager = BackupManager(mappings=[mapping], skip_confirm=True, warn_duplicates=True, test=False)
    manager.run()
    
    p1 = os.path.join(TARGET_DIR, 'dir1', 'file.txt')
    p2 = os.path.join(TARGET_DIR, 'dir2', 'file.txt')
    assert os.path.isfile(p1) and os.path.isfile(p2)
    assert open(p1, encoding='utf-8').read() == 'same content'
    assert open(p2, encoding='utf-8').read() == 'same content'

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
    manager = BackupManager(mappings=[mapping], skip_confirm=True, test=False)
    manager.run()
    
    # Only directories should exist in target
    assert os.path.exists(os.path.join(TARGET_DIR, 'dir1'))
    assert os.path.exists(os.path.join(TARGET_DIR, 'dir1', 'subdir'))
    assert not os.path.exists(os.path.join(TARGET_DIR, 'file1.txt'))
    assert not os.path.exists(os.path.join(TARGET_DIR, 'dir1', 'file2.txt'))

@pytest.mark.skipif(
    sys.platform == "win32",
    reason="chmod on a directory does not block writes the same way as on POSIX; see docs/BACKUP_TEST_COVERAGE.md",
)
def test_error_handling():
    """Test error handling when the target directory is not writable."""
    structure = {'file1.txt': 'content1'}
    create_test_structure(SOURCE_DIR, structure)
    
    os.makedirs(TARGET_DIR, exist_ok=True)
    os.chmod(TARGET_DIR, 0o444)
    try:
        mapping = BackupMapping(
            name="test",
            source_dir=SOURCE_DIR,
            target_dir=TARGET_DIR,
            mode=BackupMode.PUSH
        )
        manager = BackupManager(mappings=[mapping], skip_confirm=True, test=False)
        manager.run()
        assert len(mapping.failures) > 0
    finally:
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
    
    manager = BackupManager(mappings=mappings, skip_confirm=True, test=False)
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
    manager = BackupManager(mappings=[mapping], skip_confirm=True, test=False)
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
    
    mapping.transaction = BackupTransaction()
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
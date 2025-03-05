import os
import pytest
from refacdir.backup.backup_state import BackupState
from refacdir.backup.backup_mapping import BackupMapping
from refacdir.backup.backup_modes import BackupMode, HashMode
from .test_backup_helper import create_test_structure, clean_test_dirs

# Test directory
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_DIR = os.path.join(TEST_DIR, 'source')
TARGET_DIR = os.path.join(TEST_DIR, 'target')

@pytest.fixture(autouse=True)
def setup_teardown():
    """Setup and teardown for each test"""
    clean_test_dirs(SOURCE_DIR, TARGET_DIR)
    yield
    clean_test_dirs(SOURCE_DIR, TARGET_DIR)

def test_validate_source():
    """Test source directory validation"""
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
    state = BackupState(mapping)
    
    success, error = state.validate_source()
    assert success
    assert error is None
    assert len(state.source_files) == 3

def test_validate_source_nonexistent():
    """Test validation of nonexistent source directory"""
    mapping = BackupMapping(
        name="test",
        source_dir=os.path.join(SOURCE_DIR, 'nonexistent'),
        target_dir=TARGET_DIR,
        mode=BackupMode.PUSH
    )
    state = BackupState(mapping)
    
    success, error = state.validate_source()
    assert not success
    assert 'does not exist' in error

def test_validate_target():
    """Test target directory validation"""
    structure = {
        'file1.txt': 'content1',
        'dir1': {'file2.txt': 'content2'}
    }
    create_test_structure(TARGET_DIR, structure)
    
    mapping = BackupMapping(
        name="test",
        source_dir=SOURCE_DIR,
        target_dir=TARGET_DIR,
        mode=BackupMode.PUSH
    )
    state = BackupState(mapping)
    
    success, error = state.validate_target()
    assert success
    assert error is None
    assert len(state.target_files) == 2

def test_validate_target_nonexistent():
    """Test validation of nonexistent target directory"""
    mapping = BackupMapping(
        name="test",
        source_dir=SOURCE_DIR,
        target_dir=os.path.join(TARGET_DIR, 'nonexistent'),
        mode=BackupMode.PUSH
    )
    state = BackupState(mapping)
    
    success, error = state.validate_target()
    assert not success
    assert 'does not exist' in error

def test_verify_integrity_push():
    """Test integrity verification for PUSH mode"""
    structure = {
        'file1.txt': 'content1',
        'dir1': {'file2.txt': 'content2'}
    }
    create_test_structure(SOURCE_DIR, structure)
    create_test_structure(TARGET_DIR, structure)  # Same structure in target
    
    mapping = BackupMapping(
        name="test",
        source_dir=SOURCE_DIR,
        target_dir=TARGET_DIR,
        mode=BackupMode.PUSH
    )
    state = BackupState(mapping)
    
    # Validate both directories first
    state.validate_source()
    state.validate_target()
    
    success, error = state.verify_integrity()
    assert success
    assert error is None

def test_verify_integrity_mirror_mismatch():
    """Test integrity verification for MIRROR mode with mismatched files"""
    source_structure = {
        'keep.txt': 'keep',
        'remove.txt': 'remove'
    }
    target_structure = {
        'keep.txt': 'keep',
        'extra.txt': 'extra'  # File that shouldn't be here
    }
    create_test_structure(SOURCE_DIR, source_structure)
    create_test_structure(TARGET_DIR, target_structure)
    
    mapping = BackupMapping(
        name="test",
        source_dir=SOURCE_DIR,
        target_dir=TARGET_DIR,
        mode=BackupMode.MIRROR
    )
    state = BackupState(mapping)
    
    # Validate both directories first
    state.validate_source()
    state.validate_target()
    
    success, error = state.verify_integrity()
    assert not success
    assert 'Files missing in target' in error
    assert 'Extra files in target' in error

def test_verify_integrity_hash_mismatch():
    """Test integrity verification with hash mismatches"""
    source_structure = {'file.txt': 'content1'}
    target_structure = {'file.txt': 'content2'}  # Different content
    create_test_structure(SOURCE_DIR, source_structure)
    create_test_structure(TARGET_DIR, target_structure)
    
    mapping = BackupMapping(
        name="test",
        source_dir=SOURCE_DIR,
        target_dir=TARGET_DIR,
        mode=BackupMode.MIRROR,
        hash_mode=HashMode.SHA256
    )
    state = BackupState(mapping)
    
    # Validate both directories first
    state.validate_source()
    state.validate_target()
    
    success, error = state.verify_integrity()
    assert not success
    assert 'Hash mismatch' in error

def test_clear():
    """Test clearing backup state"""
    structure = {
        'file1.txt': 'content1',
        'dir1': {'file2.txt': 'content2'}
    }
    create_test_structure(SOURCE_DIR, structure)
    create_test_structure(TARGET_DIR, structure)
    
    mapping = BackupMapping(
        name="test",
        source_dir=SOURCE_DIR,
        target_dir=TARGET_DIR,
        mode=BackupMode.PUSH
    )
    state = BackupState(mapping)
    
    # Validate both directories to populate state
    state.validate_source()
    state.validate_target()
    
    assert len(state.source_files) > 0
    assert len(state.target_files) > 0
    
    state.clear()
    
    assert len(state.source_files) == 0
    assert len(state.target_files) == 0 
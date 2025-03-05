import os
import pytest
from refacdir.backup.hash_manager import HashManager
from refacdir.backup.backup_modes import HashMode
from .test_backup_helper import create_test_structure, clean_test_dirs

# Test directory
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
TEST_FILES_DIR = os.path.join(TEST_DIR, 'test_files')

@pytest.fixture(autouse=True)
def setup_teardown():
    """Setup and teardown for each test"""
    clean_test_dirs(TEST_FILES_DIR)
    os.makedirs(TEST_FILES_DIR)
    yield
    clean_test_dirs(TEST_FILES_DIR)

def test_filename_hash():
    """Test filename-based hashing"""
    structure = {
        'file1.txt': 'content1',
        'dir1': {'file2.txt': 'content2'}
    }
    create_test_structure(TEST_FILES_DIR, structure)
    
    manager = HashManager(HashMode.FILENAME)
    
    file1_path = os.path.join(TEST_FILES_DIR, 'file1.txt')
    file2_path = os.path.join(TEST_FILES_DIR, 'dir1', 'file2.txt')
    
    assert manager.get_file_hash(file1_path) == 'file1.txt'
    assert manager.get_file_hash(file2_path) == 'file2.txt'

def test_filename_and_parent_hash():
    """Test filename and parent directory based hashing"""
    structure = {
        'dir1': {'file.txt': 'content1'},
        'dir2': {'file.txt': 'content2'}
    }
    create_test_structure(TEST_FILES_DIR, structure)
    
    manager = HashManager(HashMode.FILENAME_AND_PARENT)
    
    file1_path = os.path.join(TEST_FILES_DIR, 'dir1', 'file.txt')
    file2_path = os.path.join(TEST_FILES_DIR, 'dir2', 'file.txt')
    
    assert manager.get_file_hash(file1_path) == os.path.join('dir1', 'file.txt')
    assert manager.get_file_hash(file2_path) == os.path.join('dir2', 'file.txt')
    assert manager.get_file_hash(file1_path) != manager.get_file_hash(file2_path)

def test_sha256_hash():
    """Test SHA256 content-based hashing"""
    structure = {
        'file1.txt': 'same content',
        'file2.txt': 'same content',
        'file3.txt': 'different content'
    }
    create_test_structure(TEST_FILES_DIR, structure)
    
    manager = HashManager(HashMode.SHA256)
    
    file1_path = os.path.join(TEST_FILES_DIR, 'file1.txt')
    file2_path = os.path.join(TEST_FILES_DIR, 'file2.txt')
    file3_path = os.path.join(TEST_FILES_DIR, 'file3.txt')
    
    # Same content should have same hash
    assert manager.get_file_hash(file1_path) == manager.get_file_hash(file2_path)
    # Different content should have different hash
    assert manager.get_file_hash(file1_path) != manager.get_file_hash(file3_path)

def test_hash_caching():
    """Test that hashes are properly cached"""
    structure = {'file1.txt': 'content1'}
    create_test_structure(TEST_FILES_DIR, structure)
    
    manager = HashManager(HashMode.SHA256)
    file_path = os.path.join(TEST_FILES_DIR, 'file1.txt')
    
    # First call should calculate hash
    hash1 = manager.get_file_hash(file_path)
    
    # Change file content
    with open(file_path, 'w') as f:
        f.write('new content')
    
    # Second call should return cached hash
    hash2 = manager.get_file_hash(file_path)
    assert hash1 == hash2
    
    # Clear cache and get new hash
    manager.clear_cache()
    hash3 = manager.get_file_hash(file_path)
    assert hash1 != hash3

def test_build_hash_dict():
    """Test building hash dictionary"""
    structure = {
        'file1.txt': 'content1',
        'file2.txt': 'content1',  # Same content as file1
        'file3.txt': 'content2'
    }
    create_test_structure(TEST_FILES_DIR, structure)
    
    manager = HashManager(HashMode.SHA256)
    files = [
        os.path.join(TEST_FILES_DIR, f)
        for f in ['file1.txt', 'file2.txt', 'file3.txt']
    ]
    
    hash_dict = manager.build_hash_dict(files)
    
    # Should have two unique hashes
    assert len(hash_dict) == 2
    
    # Files with same content should be grouped together
    for hash_list in hash_dict.values():
        if len(hash_list) == 2:
            assert all('file1.txt' in f or 'file2.txt' in f for f in hash_list)
        else:
            assert 'file3.txt' in hash_list[0]

def test_find_duplicates():
    """Test finding duplicate files"""
    structure = {
        'unique1.txt': 'content1',
        'unique2.txt': 'content2',
        'dup1.txt': 'same',
        'dup2.txt': 'same',
        'dup3.txt': 'same'
    }
    create_test_structure(TEST_FILES_DIR, structure)
    
    manager = HashManager(HashMode.SHA256)
    files = [
        os.path.join(TEST_FILES_DIR, f)
        for f in os.listdir(TEST_FILES_DIR)
    ]
    
    manager.hash_dict = manager.build_hash_dict(files)
    duplicates = manager.find_duplicates()
    
    assert len(duplicates) == 1  # One group of duplicates
    dup_group = duplicates[0]
    assert len(dup_group) == 3  # Three duplicate files
    assert all('dup' in f for f in dup_group)

def test_verify_files_match():
    """Test file verification"""
    structure = {
        'file1.txt': 'content1',
        'file2.txt': 'content1',  # Same as file1
        'file3.txt': 'content2'   # Different
    }
    create_test_structure(TEST_FILES_DIR, structure)
    
    manager = HashManager(HashMode.SHA256)
    file1 = os.path.join(TEST_FILES_DIR, 'file1.txt')
    file2 = os.path.join(TEST_FILES_DIR, 'file2.txt')
    file3 = os.path.join(TEST_FILES_DIR, 'file3.txt')
    
    assert manager.verify_files_match(file1, file2)
    assert not manager.verify_files_match(file1, file3)
    assert not manager.verify_files_match(file1, 'nonexistent.txt') 
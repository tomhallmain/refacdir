import os
import pytest
import glob
import time
import json
import threading
from datetime import datetime, timedelta
from refacdir.backup.backup_source_data import BackupSourceData, BackupMetadata, BackupLockError
from .test_backup_helper import create_test_structure, clean_test_dirs
import zlib

# Test directory
TEST_DIR = os.path.dirname(os.path.abspath(__file__))
SOURCE_DIR = os.path.join(TEST_DIR, 'source')

@pytest.fixture(autouse=True)
def setup_teardown():
    """Setup and teardown for each test"""
    clean_test_dirs(SOURCE_DIR)
    yield
    clean_test_dirs(SOURCE_DIR)

def test_init():
    """Test initialization"""
    data = BackupSourceData(SOURCE_DIR)
    assert data.source_dir == os.path.normpath(SOURCE_DIR)
    assert data.filepath == os.path.normpath(os.path.join(SOURCE_DIR, BackupSourceData.FILEPATH))
    assert isinstance(data.last_updated, int)
    assert data.version == BackupSourceData.VERSION

def test_save_load():
    """Test saving and loading backup data"""
    # Create initial data
    data = BackupSourceData(SOURCE_DIR)
    data.hash_dict['hash1'] = ['file1.txt', 'file2.txt']
    data.hash_dict['hash2'] = ['file3.txt']
    
    # Save data
    os.makedirs(SOURCE_DIR, exist_ok=True)
    data.save()
    
    # Load data
    loaded_data = BackupSourceData.load(SOURCE_DIR)
    
    assert loaded_data.source_dir == data.source_dir
    assert loaded_data.hash_dict == data.hash_dict
    assert loaded_data.version == data.version
    assert loaded_data.last_updated == data.last_updated

def test_backup_creation():
    """Test backup file creation"""
    data = BackupSourceData(SOURCE_DIR)
    data.hash_dict['hash1'] = ['file1.txt']
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # First save should create the file but no backup
    data.save()
    assert os.path.exists(data.filepath)
    assert not os.path.exists(data.backup_dir)
    
    # Second save should create a backup
    data.hash_dict['hash2'] = ['file2.txt']
    data.save()
    assert os.path.exists(data.backup_dir)
    backup_files = glob.glob(os.path.join(data.backup_dir, f"{BackupSourceData.FILEPATH}.*"))
    assert len(backup_files) == 1

def test_backup_rotation():
    """Test backup file rotation"""
    data = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # Create more than MAX_BACKUPS saves
    for i in range(BackupSourceData.MAX_BACKUPS + 2):
        data.hash_dict[f'hash{i}'] = [f'file{i}.txt']
        data.save()
    
    # Check that only MAX_BACKUPS files exist
    backup_files = glob.glob(os.path.join(data.backup_dir, f"{BackupSourceData.FILEPATH}.*"))
    assert len(backup_files) == BackupSourceData.MAX_BACKUPS
    
    # Verify files are ordered by timestamp (newest first)
    backup_times = [os.path.getmtime(f) for f in backup_files]
    assert backup_times == sorted(backup_times, reverse=True)

def test_list_backups():
    """Test listing available backups"""
    data = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # Create a few backups
    for i in range(3):
        data.hash_dict[f'hash{i}'] = [f'file{i}.txt']
        data.save()
        time.sleep(0.001)  # Ensure unique timestamps
    
    # List backups
    backups = data.list_backups()
    assert len(backups) == 2  # First save doesn't create backup
    
    # Verify backup list format
    for dt, filepath in backups:
        assert isinstance(dt, datetime)
        assert os.path.exists(filepath)
    
    # Verify ordered by time (newest first)
    assert backups[0][0] > backups[1][0]

def test_restore_from_backup():
    """Test basic restore functionality"""
    # Create and save initial data
    data = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    data.hash_dict['hash1'] = ['file1.txt']
    data.save()
    
    # Modify and save again to create backup
    data.hash_dict['hash2'] = ['file2.txt']
    data.save()
    original_hash_dict = data.hash_dict.copy()
    
    # Modify data further
    data.hash_dict['hash3'] = ['file3.txt']
    data.save()
    
    # Restore from previous version
    success, error = data.restore_from_backup()
    assert success, error
    assert data.hash_dict == original_hash_dict

def test_restore_nonexistent():
    """Test restore with no backups"""
    data = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # Try to restore with no backups
    success, error = data.restore_from_backup()
    assert not success
    assert "No backups available" in error

def test_load_nonexistent():
    """Test loading from nonexistent file"""
    data = BackupSourceData.load(SOURCE_DIR)
    assert isinstance(data, BackupSourceData)
    assert data.source_dir == os.path.normpath(SOURCE_DIR)
    assert len(data.hash_dict) == 0

def test_load_with_overwrite():
    """Test loading with overwrite flag"""
    # Create and save initial data
    data = BackupSourceData(SOURCE_DIR)
    data.hash_dict['hash1'] = ['file1.txt']
    os.makedirs(SOURCE_DIR, exist_ok=True)
    data.save()
    
    # Load with overwrite
    new_data = BackupSourceData.load(SOURCE_DIR, overwrite=True)
    assert len(new_data.hash_dict) == 0

def test_version_upgrade():
    """Test version upgrade handling"""
    # Create data with old version
    data = BackupSourceData(SOURCE_DIR)
    data.version = 0  # Old version
    os.makedirs(SOURCE_DIR, exist_ok=True)
    data.save()
    
    # Load data - should upgrade version
    loaded_data = BackupSourceData.load(SOURCE_DIR)
    assert loaded_data.version == BackupSourceData.VERSION

def test_clear():
    """Test clearing backup data"""
    data = BackupSourceData(SOURCE_DIR)
    data.hash_dict['hash1'] = ['file1.txt', 'file2.txt']
    old_updated = data.last_updated
    
    data.clear()
    
    assert len(data.hash_dict) == 0
    assert data.last_updated > old_updated 

def test_backup_metadata():
    """Test backup metadata creation and loading"""
    data = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # Create backup with description
    data.hash_dict['hash1'] = ['file1.txt', 'file2.txt']
    data.save("Initial backup with 2 files")
    
    # Create another backup
    data.hash_dict['hash2'] = ['file3.txt']
    data.save("Added one more file")
    
    # List backups and verify metadata
    backups = data.list_backups()
    assert len(backups) == 1  # First save doesn't create backup
    
    timestamp, filepath, description, file_count = backups[0]
    assert isinstance(timestamp, datetime)
    assert os.path.exists(filepath)
    assert description == "Added one more file"
    assert file_count == 3  # Total unique files

def test_backup_integrity():
    """Test backup integrity checking"""
    data = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # Create initial backup
    data.hash_dict['hash1'] = ['file1.txt']
    data.save("Initial backup")
    
    # Create second backup to test
    data.hash_dict['hash2'] = ['file2.txt']
    data.save("Second backup")
    
    # Get the backup file path
    backups = data._get_available_backups()
    assert len(backups) == 1
    backup_path = backups[0][1]
    
    # Verify integrity check passes
    success, error = data._verify_backup_integrity(backup_path)
    assert success, error
    
    # Corrupt the backup file
    with open(backup_path, "ab") as f:
        f.write(b"corrupt")
    
    # Verify integrity check fails
    success, error = data._verify_backup_integrity(backup_path)
    assert not success
    assert "checksum mismatch" in error

def test_restore_validation():
    """Test restore validation checks"""
    data = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # Try to restore with no backups
    success, error = data.restore_from_backup()
    assert not success
    assert "No backups available" in error
    
    # Create invalid backup file
    backup_path = os.path.join(data.backup_dir, f"{BackupSourceData.FILEPATH}.invalid")
    os.makedirs(data.backup_dir, exist_ok=True)
    with open(backup_path, "wb") as f:
        f.write(b"invalid data")
    
    # Try to restore invalid backup
    success, error = data.restore_from_backup(backup_path)
    assert not success
    assert "Invalid backup file format" in error

def test_metadata_persistence():
    """Test metadata persistence across saves"""
    data = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # Create backups with descriptions
    descriptions = [
        "First backup",
        "Second backup",
        "Third backup"
    ]
    
    for i, desc in enumerate(descriptions):
        data.hash_dict[f'hash{i}'] = [f'file{i}.txt']
        data.save(desc)
        time.sleep(0.001)  # Ensure unique timestamps
    
    # Verify metadata file exists
    metadata_path = os.path.join(data.backup_dir, BackupSourceData.METADATA_FILE)
    assert os.path.exists(metadata_path)
    
    # Load and verify metadata
    with open(metadata_path, "r") as f:
        metadata_dict = json.load(f)
    
    # Should have 2 backups (first save doesn't create backup)
    assert len(metadata_dict) == 2
    
    # Verify metadata contents
    for backup_path, meta in metadata_dict.items():
        assert isinstance(meta["timestamp"], str)
        assert meta["description"] in descriptions
        assert isinstance(meta["file_count"], int)
        assert len(meta["checksum"]) == 64  # SHA-256 hash length

def test_version_upgrade_with_metadata():
    """Test version upgrade handling with metadata"""
    # Create data with old version
    data = BackupSourceData(SOURCE_DIR)
    data.version = 1  # Old version
    os.makedirs(SOURCE_DIR, exist_ok=True)
    data.save("Old version backup")
    
    # Load data - should upgrade version
    loaded_data = BackupSourceData.load(SOURCE_DIR)
    assert loaded_data.version == BackupSourceData.VERSION
    
    # Verify metadata was created during upgrade
    backups = loaded_data.list_backups()
    for _, filepath, desc, _ in backups:
        metadata = loaded_data._load_metadata(filepath)
        assert metadata is not None
        assert isinstance(metadata.checksum, str) 

def test_partial_restore():
    """Test partial restore functionality"""
    data = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # Create initial backup with multiple files
    data.hash_dict['hash1'] = ['file1.txt', 'file2.txt']
    data.hash_dict['hash2'] = ['file3.txt', 'file4.txt']
    data.save("Initial backup")
    
    # Modify some files
    data.hash_dict['hash1'] = ['file1.txt', 'file2_modified.txt']
    data.hash_dict['hash3'] = ['file5.txt']
    data.save("Modified backup")
    
    # Restore only specific files
    success, error = data.restore_from_backup(files=['file2.txt', 'file3.txt'])
    assert success, error
    
    # Verify restored files
    restored_files = set(sum(data.hash_dict.values(), []))
    assert 'file2.txt' in restored_files  # Restored from backup
    assert 'file3.txt' in restored_files  # Restored from backup
    assert 'file1.txt' in restored_files  # Kept from current
    assert 'file5.txt' in restored_files  # Kept from current
    assert 'file2_modified.txt' not in restored_files  # Replaced by backup version

def test_restore_by_date():
    """Test restoring backup by date"""
    data = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # Create backups at different times
    timestamps = []
    
    # First backup
    data.hash_dict['hash1'] = ['file1.txt']
    data.save("First backup")
    time.sleep(0.001)
    timestamps.append(datetime.now())
    
    # Second backup
    data.hash_dict['hash2'] = ['file2.txt']
    data.save("Second backup")
    time.sleep(0.001)
    timestamps.append(datetime.now())
    
    # Third backup
    data.hash_dict['hash3'] = ['file3.txt']
    data.save("Third backup")
    
    # Try to restore from middle timestamp
    target_date = timestamps[1]
    success, error = data.restore_from_backup(target_date=target_date)
    assert success, error
    
    # Verify restored state matches second backup
    assert set(sum(data.hash_dict.values(), [])) == {'file1.txt', 'file2.txt'}

def test_restore_by_description():
    """Test restoring backup by description"""
    data = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # Create backups with different descriptions
    data.hash_dict['hash1'] = ['file1.txt']
    data.save("Initial commit")
    
    data.hash_dict['hash2'] = ['file2.txt']
    data.save("Added feature X")
    
    data.hash_dict['hash3'] = ['file3.txt']
    data.save("Bug fix for feature X")
    
    # Restore using partial description match
    success, error = data.restore_from_backup(description="feature X")
    assert success, error
    
    # Should restore to the most recent backup matching the description
    assert set(sum(data.hash_dict.values(), [])) == {'file1.txt', 'file2.txt'}

def test_find_backups():
    """Test backup search functionality"""
    data = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # Create backups with various characteristics
    start_time = datetime.now()
    
    # First backup - 2 files
    data.hash_dict['hash1'] = ['file1.txt', 'file2.txt']
    data.save("Small backup")
    time.sleep(0.001)
    
    # Second backup - 4 files
    data.hash_dict['hash2'] = ['file3.txt', 'file4.txt']
    data.save("Medium feature backup")
    time.sleep(0.001)
    
    # Third backup - 6 files
    data.hash_dict['hash3'] = ['file5.txt', 'file6.txt']
    data.save("Large feature backup")
    
    end_time = datetime.now()
    
    # Test date range filter
    date_backups = data.find_backups(
        start_date=start_time,
        end_date=end_time
    )
    assert len(date_backups) == 2  # First save doesn't create backup
    
    # Test description filter
    feature_backups = data.find_backups(description="feature")
    assert len(feature_backups) == 2
    assert all("feature" in b[2].lower() for b in feature_backups)
    
    # Test file count filter
    small_backups = data.find_backups(max_files=4)
    assert len(small_backups) == 1
    assert small_backups[0][3] <= 4
    
    large_backups = data.find_backups(min_files=5)
    assert len(large_backups) == 1
    assert large_backups[0][3] >= 5

def test_version_compatibility():
    """Test version compatibility handling"""
    data = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # Create backup with current version
    data.hash_dict['hash1'] = ['file1.txt']
    data.save("Current version backup")
    
    # Modify backup to have future version
    backups = data._get_available_backups()
    backup_path = backups[0][1]
    with open(backup_path, "rb") as f:
        backup_data = pickle.load(f)
    backup_data.version = BackupSourceData.VERSION + 1
    with open(backup_path, "wb") as f:
        pickle.dump(backup_data, f)
    
    # Attempt to restore from future version
    success, error = data.restore_from_backup()
    assert not success
    assert "newer than current version" in error

def test_backup_search_combined_filters():
    """Test backup search with combined filters"""
    data = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # Create backups over multiple days
    base_time = datetime.now() - timedelta(days=5)
    
    for i in range(5):
        # Set timestamp for this iteration
        current_time = base_time + timedelta(days=i)
        
        # Add files
        num_files = (i + 1) * 2  # 2, 4, 6, 8, 10 files
        for j in range(num_files):
            data.hash_dict[f'hash{i}_{j}'] = [f'file{i}_{j}.txt']
            
        # Create backup with timestamp
        data.save(f"Day {i} backup with {num_files} files")
        
    # Test combined filters
    results = data.find_backups(
        start_date=base_time + timedelta(days=1),
        end_date=base_time + timedelta(days=3),
        min_files=4,
        max_files=8,
        description="backup with"
    )
    
    assert len(results) > 0
    for timestamp, _, desc, file_count in results:
        assert base_time + timedelta(days=1) <= timestamp <= base_time + timedelta(days=3)
        assert 4 <= file_count <= 8
        assert "backup with" in desc.lower()

def test_restore_nonexistent_files():
    """Test partial restore with nonexistent files"""
    data = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # Create backup
    data.hash_dict['hash1'] = ['file1.txt', 'file2.txt']
    data.save("Initial backup")
    
    # Try to restore nonexistent files
    success, error = data.restore_from_backup(files=['nonexistent.txt', 'file1.txt'])
    assert not success
    assert "Files not found in backup" in error
    assert "nonexistent.txt" in error 

def test_concurrent_access():
    """Test concurrent access protection"""
    data1 = BackupSourceData(SOURCE_DIR)
    data2 = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # First instance acquires lock
    data1.acquire_lock()
    
    # Second instance should fail to acquire lock
    with pytest.raises(BackupLockError):
        data2.acquire_lock(timeout=1)
    
    # Release lock
    data1.release_lock()
    
    # Now second instance should be able to acquire lock
    data2.acquire_lock()
    data2.release_lock()

def test_context_manager():
    """Test context manager for automatic lock handling"""
    data1 = BackupSourceData(SOURCE_DIR)
    data2 = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # Use first instance with context manager
    with data1:
        # Second instance should fail to acquire lock
        with pytest.raises(BackupLockError):
            data2.acquire_lock(timeout=1)
    
    # After context, lock should be released
    data2.acquire_lock()
    data2.release_lock()

def test_lock_cleanup():
    """Test lock cleanup after errors"""
    data = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # Simulate error during operation
    try:
        with data:
            raise RuntimeError("Test error")
    except RuntimeError:
        pass
    
    # Lock should be released despite error
    data.acquire_lock()
    data.release_lock()

def test_concurrent_operations():
    """Test concurrent backup operations"""
    data1 = BackupSourceData(SOURCE_DIR)
    data2 = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # Create initial data
    data1.hash_dict['hash1'] = ['file1.txt']
    data1.save("Initial backup")
    
    def backup_thread():
        try:
            data1.save("Backup from thread")
        except BackupLockError:
            pass
    
    def restore_thread():
        try:
            data2.restore_from_backup()
        except BackupLockError:
            pass
    
    # Start concurrent operations
    t1 = threading.Thread(target=backup_thread)
    t2 = threading.Thread(target=restore_thread)
    
    t1.start()
    t2.start()
    t1.join()
    t2.join()
    
    # Verify operations didn't corrupt data
    assert os.path.exists(data1.filepath)
    loaded = BackupSourceData.load(SOURCE_DIR)
    assert isinstance(loaded, BackupSourceData) 

def test_disk_space_check():
    """Test disk space checking"""
    data = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # Test with reasonable space requirement
    has_space, error = data._check_disk_space(1)  # Only need 1MB
    assert has_space, error
    
    # Test with excessive space requirement
    has_space, error = data._check_disk_space(1024 * 1024)  # Try to require 1PB
    assert not has_space
    assert "Insufficient disk space" in error

def test_backup_size_limit():
    """Test backup size limits"""
    data = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # Create a backup file
    backup_path = data._get_backup_filepath()
    os.makedirs(os.path.dirname(backup_path), exist_ok=True)
    
    # Create small file
    with open(backup_path, "wb") as f:
        f.write(b"small backup")
    
    # Test small backup
    is_valid, error = data._check_backup_size(backup_path)
    assert is_valid, error
    
    # Clean up
    os.remove(backup_path)

def test_backup_with_disk_checks():
    """Test backup creation with disk space checks"""
    data = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # Add some data and create backup
    data.hash_dict['hash1'] = ['file1.txt']
    success, error = data._backup_current_file("Test backup")
    assert success, error
    
    # Verify backup was created
    backups = data._get_available_backups()
    assert len(backups) == 1
    
    # Verify backup file exists and is within size limits
    backup_path = backups[0][1]
    is_valid, error = data._check_backup_size(backup_path)
    assert is_valid, error 

def test_atomic_write():
    """Test atomic file writing"""
    data = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    test_file = os.path.join(SOURCE_DIR, "test.txt")
    test_data = b"test data"
    
    # Test successful write
    success, error = data._atomic_write(test_file, test_data)
    assert success, error
    
    # Verify file exists and temp file doesn't
    assert os.path.exists(test_file)
    assert not os.path.exists(test_file + data.TEMP_SUFFIX)
    
    # Verify content
    with open(test_file, "rb") as f:
        assert f.read() == test_data

def test_atomic_write_failure():
    """Test atomic write failure handling"""
    data = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    test_file = os.path.join(SOURCE_DIR, "test.txt")
    
    # Create a directory with the same name as temp file to force failure
    temp_path = test_file + data.TEMP_SUFFIX
    os.makedirs(temp_path, exist_ok=True)
    
    # Attempt write should fail
    success, error = data._atomic_write(test_file, b"test")
    assert not success
    assert "Failed to write file" in error
    
    # Clean up
    os.rmdir(temp_path)

def test_atomic_json_write():
    """Test atomic JSON writing"""
    data = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    test_file = os.path.join(SOURCE_DIR, "test.json")
    test_data = {"key": "value"}
    
    # Test successful write
    success, error = data._atomic_write_json(test_file, test_data)
    assert success, error
    
    # Verify file exists and content
    assert os.path.exists(test_file)
    with open(test_file, "r") as f:
        loaded = json.load(f)
        assert loaded == test_data

def test_atomic_backup_creation():
    """Test atomic backup file creation"""
    data = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # Create initial data
    data.hash_dict['hash1'] = ['file1.txt']
    data.save()
    
    # Create backup
    success, error = data._backup_current_file("Test backup")
    assert success, error
    
    # Verify no temporary files left behind
    temp_files = glob.glob(os.path.join(SOURCE_DIR, f"**/*{data.TEMP_SUFFIX}"), recursive=True)
    assert len(temp_files) == 0
    
    # Verify backup and metadata exist
    backups = data._get_available_backups()
    assert len(backups) == 1
    assert os.path.exists(os.path.join(data.backup_dir, data.METADATA_FILE))

def test_atomic_save():
    """Test atomic save operation"""
    data = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # Add some data and save
    data.hash_dict['hash1'] = ['file1.txt']
    data.save("Test save")
    
    # Verify no temporary files left behind
    temp_files = glob.glob(os.path.join(SOURCE_DIR, f"**/*{data.TEMP_SUFFIX}"), recursive=True)
    assert len(temp_files) == 0
    
    # Verify data file exists
    assert os.path.exists(data.filepath)
    
    # Load and verify data
    loaded = BackupSourceData.load(SOURCE_DIR)
    assert loaded.hash_dict == data.hash_dict

def test_interrupted_backup():
    """Test handling of interrupted backup operations"""
    data = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # Create initial data
    data.hash_dict['hash1'] = ['file1.txt']
    data.save()
    
    # Simulate interrupted backup by creating temp files
    backup_path = data._get_backup_filepath()
    temp_backup = backup_path + data.TEMP_SUFFIX
    with open(temp_backup, "wb") as f:
        f.write(b"incomplete backup")
    
    # Create another backup
    success, error = data._backup_current_file("Test backup")
    assert success, error
    
    # Verify temp file was cleaned up
    assert not os.path.exists(temp_backup)
    
    # Verify only one backup exists (plus metadata)
    files = os.listdir(data.backup_dir)
    backup_files = [f for f in files if f != data.METADATA_FILE]
    assert len(backup_files) == 1 

def test_metadata_corruption_recovery():
    """Test recovery from corrupted metadata"""
    data = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # Create backup with metadata
    data.hash_dict['hash1'] = ['file1.txt']
    data.save("Test backup")
    
    # Get paths
    metadata_path = os.path.join(data.backup_dir, data.METADATA_FILE)
    backup_metadata_path = os.path.join(data.backup_dir, data.METADATA_BACKUP_FILE)
    
    # Verify both metadata files exist
    assert os.path.exists(metadata_path)
    assert os.path.exists(backup_metadata_path)
    
    # Corrupt primary metadata file
    with open(metadata_path, "w") as f:
        f.write("corrupted json{")
    
    # Should still be able to load metadata from backup
    backups = data.list_backups()
    assert len(backups) == 1
    assert backups[0][2] == "Test backup"  # Description preserved
    
    # Primary metadata should be restored
    with open(metadata_path, "r") as f:
        json.load(f)  # Should not raise JSONDecodeError

def test_metadata_double_corruption():
    """Test handling of both metadata files being corrupted"""
    data = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # Create backup with metadata
    data.hash_dict['hash1'] = ['file1.txt']
    data.save("Test backup")
    
    # Get paths
    metadata_path = os.path.join(data.backup_dir, data.METADATA_FILE)
    backup_metadata_path = os.path.join(data.backup_dir, data.METADATA_BACKUP_FILE)
    
    # Corrupt both metadata files
    with open(metadata_path, "w") as f:
        f.write("corrupted")
    with open(backup_metadata_path, "w") as f:
        f.write("also corrupted")
    
    # Should handle gracefully by starting fresh
    backups = data.list_backups()
    assert len(backups) == 1  # Can still list backups
    assert backups[0][2] == ""  # But metadata is lost
    
    # Creating new backup should work
    data.hash_dict['hash2'] = ['file2.txt']
    data.save("New backup")
    
    # New metadata should be valid
    with open(metadata_path, "r") as f:
        metadata = json.load(f)
        assert len(metadata) == 1
        assert list(metadata.values())[0]["description"] == "New backup" 

class TestProgressCallback(ProgressCallback):
    """Test implementation of ProgressCallback"""
    def __init__(self):
        self.updates = []
        
    def on_progress(self, current: int, total: int, message: str = ""):
        self.updates.append((current, total, message))

def test_backup_progress():
    """Test progress reporting during backup"""
    callback = TestProgressCallback()
    data = BackupSourceData(SOURCE_DIR, progress_callback=callback)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # Create initial data and save
    data.hash_dict['hash1'] = ['file1.txt']
    data.save("Test backup")
    
    # Verify progress updates were received
    assert len(callback.updates) > 0
    
    # Verify progress format
    for current, total, message in callback.updates:
        assert isinstance(current, int)
        assert isinstance(total, int)
        assert current <= total
        assert isinstance(message, str)
    
    # Verify progress messages
    messages = [msg for _, _, msg in callback.updates]
    assert "Creating backup..." in messages
    assert "Finalizing backup..." in messages

def test_restore_progress():
    """Test progress reporting during restore"""
    # Create initial backup
    data = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    data.hash_dict['hash1'] = ['file1.txt']
    data.save("Initial backup")
    
    # Modify data
    data.hash_dict['hash2'] = ['file2.txt']
    data.save()
    
    # Create new instance with progress callback
    callback = TestProgressCallback()
    data = BackupSourceData(SOURCE_DIR, progress_callback=callback)
    
    # Restore from backup
    success, error = data.restore_from_backup()
    assert success, error
    
    # Verify progress updates
    assert len(callback.updates) > 0
    
    # Verify progress messages
    messages = [msg for _, _, msg in callback.updates]
    assert "Verifying backup integrity..." in messages
    assert "Creating safety backup..." in messages
    assert "Loading backup data..." in messages
    assert "Restore completed successfully" in messages

def test_partial_restore_progress():
    """Test progress reporting during partial restore"""
    # Create initial backup
    data = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    data.hash_dict['hash1'] = ['file1.txt', 'file2.txt']
    data.save("Initial backup")
    
    # Create new instance with progress callback
    callback = TestProgressCallback()
    data = BackupSourceData(SOURCE_DIR, progress_callback=callback)
    
    # Perform partial restore
    success, error = data.restore_from_backup(files=['file1.txt'])
    assert success, error
    
    # Verify progress messages
    messages = [msg for _, _, msg in callback.updates]
    assert "Performing partial restore..." in messages 

def test_compression():
    """Test backup compression"""
    data = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # Create uncompressed backup
    data.hash_dict['hash1'] = ['file1.txt']
    data.save("Uncompressed backup")
    
    # Get uncompressed size
    backups = data._get_available_backups()
    uncompressed_path = backups[0][1]
    uncompressed_size = os.path.getsize(uncompressed_path)
    
    # Enable compression and create compressed backup
    data.use_compression = True
    data.hash_dict['hash2'] = ['file2.txt']
    data.save("Compressed backup")
    
    # Get compressed size
    backups = data._get_available_backups()
    compressed_path = backups[0][1]
    compressed_size = os.path.getsize(compressed_path)
    
    # Verify compressed backup is smaller
    assert compressed_size < uncompressed_size
    
    # Verify metadata indicates compression
    metadata = data._load_metadata(compressed_path)
    assert metadata.compressed
    
    # Verify uncompressed backup metadata
    metadata = data._load_metadata(uncompressed_path)
    assert not metadata.compressed

def test_restore_compressed():
    """Test restoring from compressed backup"""
    # Create data with compression
    data = BackupSourceData(SOURCE_DIR)
    data.use_compression = True
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # Create compressed backup
    data.hash_dict['hash1'] = ['file1.txt', 'file2.txt']
    data.save("Compressed backup")
    
    # Modify data
    data.hash_dict['hash2'] = ['file3.txt']
    original_hash_dict = data.hash_dict.copy()
    
    # Restore from compressed backup
    success, error = data.restore_from_backup()
    assert success, error
    
    # Verify data was restored correctly
    assert data.hash_dict == {'hash1': ['file1.txt', 'file2.txt']}

def test_mixed_compression_restore():
    """Test restoring with mixed compressed and uncompressed backups"""
    data = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # Create uncompressed backup
    data.hash_dict['hash1'] = ['file1.txt']
    data.save("Uncompressed backup")
    
    # Create compressed backup
    data.use_compression = True
    data.hash_dict['hash2'] = ['file2.txt']
    data.save("Compressed backup")
    
    # Modify data
    data.hash_dict['hash3'] = ['file3.txt']
    
    # Restore from each backup and verify
    success, error = data.restore_from_backup(description="Uncompressed")
    assert success, error
    assert set(sum(data.hash_dict.values(), [])) == {'file1.txt'}
    
    success, error = data.restore_from_backup(description="Compressed")
    assert success, error
    assert set(sum(data.hash_dict.values(), [])) == {'file1.txt', 'file2.txt'}

def test_compression_with_progress():
    """Test progress reporting during compressed backup"""
    callback = TestProgressCallback()
    data = BackupSourceData(SOURCE_DIR, progress_callback=callback)
    data.use_compression = True
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # Create compressed backup
    data.hash_dict['hash1'] = ['file1.txt']
    data.save("Compressed backup")
    
    # Verify progress updates
    assert len(callback.updates) > 0
    
    # Verify progress format
    for current, total, message in callback.updates:
        assert isinstance(current, int)
        assert isinstance(total, int)
        assert current <= total
    
    # Verify final progress equals total size
    final_progress = callback.updates[-2][0]  # Second to last update (before "Finalizing")
    total_size = callback.updates[0][1]  # Total size from first update
    assert final_progress == total_size 

def test_interrupted_backup_resume():
    """Test resuming an interrupted backup"""
    data = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # Create initial data
    data.hash_dict['hash1'] = ['file1.txt']
    data.save()
    
    # Start a backup that gets interrupted
    backup_path = data._get_backup_filepath()
    temp_backup_path = backup_path + data.TEMP_SUFFIX
    
    # Simulate partial backup
    with open(data.filepath, "rb") as src:
        content = src.read()
        halfway = len(content) // 2
        
        # Write first half
        with open(temp_backup_path, "wb") as dst:
            dst.write(content[:halfway])
        
        # Create partial metadata
        metadata = BackupMetadata("Interrupted backup")
        metadata.partial = True
        metadata.bytes_written = halfway
        data._save_metadata(temp_backup_path, metadata)
    
    # Try to create backup again - should resume
    callback = TestProgressCallback()
    data.progress = BackupProgress(callback)
    success, error = data._backup_current_file("Resumed backup")
    assert success, error
    
    # Verify progress messages
    messages = [msg for _, _, msg in callback.updates]
    assert "Resuming interrupted backup..." in messages
    
    # Verify backup completed
    backups = data._get_available_backups()
    assert len(backups) == 1
    
    # Verify metadata shows completed backup
    metadata = data._load_metadata(backups[0][1])
    assert not metadata.partial
    assert metadata.bytes_written == 0

def test_interrupted_backup_invalid():
    """Test handling invalid interrupted backup"""
    data = BackupSourceData(SOURCE_DIR)
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # Create initial data
    data.hash_dict['hash1'] = ['file1.txt']
    data.save()
    
    # Create invalid temp backup
    backup_path = data._get_backup_filepath()
    temp_backup_path = backup_path + data.TEMP_SUFFIX
    with open(temp_backup_path, "wb") as f:
        f.write(b"invalid backup")
    
    # Try to create backup - should start fresh
    callback = TestProgressCallback()
    data.progress = BackupProgress(callback)
    success, error = data._backup_current_file("Fresh backup")
    assert success, error
    
    # Verify started fresh backup
    messages = [msg for _, _, msg in callback.updates]
    assert "Creating backup..." in messages
    assert "Resuming interrupted backup..." not in messages

def test_interrupted_compressed_backup():
    """Test resuming interrupted compressed backup"""
    data = BackupSourceData(SOURCE_DIR)
    data.use_compression = True
    os.makedirs(SOURCE_DIR, exist_ok=True)
    
    # Create initial data
    data.hash_dict['hash1'] = ['file1.txt']
    data.save()
    
    # Start a backup that gets interrupted
    backup_path = data._get_backup_filepath()
    temp_backup_path = backup_path + data.TEMP_SUFFIX
    
    # Simulate partial compressed backup
    with open(data.filepath, "rb") as src:
        content = src.read()
        halfway = len(content) // 2
        
        # Write first half compressed
        with open(temp_backup_path, "wb") as dst:
            compressor = zlib.compressobj(data.COMPRESSION_LEVEL)
            compressed = compressor.compress(content[:halfway])
            dst.write(compressed)
        
        # Create partial metadata
        metadata = BackupMetadata("Interrupted compressed backup")
        metadata.partial = True
        metadata.compressed = True
        metadata.bytes_written = halfway
        data._save_metadata(temp_backup_path, metadata)
    
    # Try to create backup again - should resume
    callback = TestProgressCallback()
    data.progress = BackupProgress(callback)
    success, error = data._backup_current_file("Resumed compressed backup")
    assert success, error
    
    # Verify progress messages
    messages = [msg for _, _, msg in callback.updates]
    assert "Resuming interrupted backup..." in messages
    
    # Verify backup completed
    backups = data._get_available_backups()
    assert len(backups) == 1
    
    # Verify metadata shows completed compressed backup
    metadata = data._load_metadata(backups[0][1])
    assert not metadata.partial
    assert metadata.compressed
    assert metadata.bytes_written == 0 
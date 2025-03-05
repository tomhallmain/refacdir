import os
import pytest
from refacdir.backup.backup_mapping import BackupTransaction
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

def test_successful_transaction():
    """Test successful transaction execution"""
    transaction = BackupTransaction()
    
    # Create test files
    file1 = os.path.join(TEST_FILES_DIR, 'file1.txt')
    file2 = os.path.join(TEST_FILES_DIR, 'file2.txt')
    
    def create_file(path, content):
        with open(path, 'w') as f:
            f.write(content)
        return True, None
        
    def rollback_create(path, _):
        if os.path.exists(path):
            os.remove(path)
    
    # Add operations
    transaction.add_operation(create_file, (file1, "content1"), rollback_create)
    transaction.add_operation(create_file, (file2, "content2"), rollback_create)
    
    # Execute transaction
    success, error = transaction.execute()
    
    assert success
    assert error is None
    assert os.path.exists(file1)
    assert os.path.exists(file2)
    with open(file1) as f:
        assert f.read() == "content1"
    with open(file2) as f:
        assert f.read() == "content2"

def test_failed_transaction():
    """Test transaction failure and rollback"""
    transaction = BackupTransaction()
    
    # Create test files
    file1 = os.path.join(TEST_FILES_DIR, 'file1.txt')
    file2 = os.path.join(TEST_FILES_DIR, 'file2.txt')
    
    def create_file(path, content):
        with open(path, 'w') as f:
            f.write(content)
        return True, None
        
    def fail_operation(*args):
        return False, "Operation failed"
        
    def rollback_create(path, _):
        if os.path.exists(path):
            os.remove(path)
    
    # Add operations - second one will fail
    transaction.add_operation(create_file, (file1, "content1"), rollback_create)
    transaction.add_operation(fail_operation, (), None)
    transaction.add_operation(create_file, (file2, "content2"), rollback_create)
    
    # Execute transaction
    success, error = transaction.execute()
    
    assert not success
    assert "Operation failed" in error
    # First file should be rolled back
    assert not os.path.exists(file1)
    # Third operation should not have executed
    assert not os.path.exists(file2)

def test_exception_handling():
    """Test handling of exceptions during transaction"""
    transaction = BackupTransaction()
    
    def raise_exception(*args):
        raise ValueError("Test exception")
        
    def dummy_rollback(*args):
        pass
    
    transaction.add_operation(raise_exception, (), dummy_rollback)
    
    success, error = transaction.execute()
    
    assert not success
    assert "Test exception" in error

def test_rollback_failure():
    """Test handling of rollback failures"""
    transaction = BackupTransaction()
    
    file1 = os.path.join(TEST_FILES_DIR, 'file1.txt')
    
    def create_file(path, content):
        with open(path, 'w') as f:
            f.write(content)
        return True, None
        
    def fail_operation(*args):
        return False, "Operation failed"
        
    def failing_rollback(*args):
        raise Exception("Rollback failed")
    
    # Add operations
    transaction.add_operation(create_file, (file1, "content1"), failing_rollback)
    transaction.add_operation(fail_operation, (), None)
    
    # Execute transaction - should handle rollback failure gracefully
    success, error = transaction.execute()
    
    assert not success
    assert "Operation failed" in error 
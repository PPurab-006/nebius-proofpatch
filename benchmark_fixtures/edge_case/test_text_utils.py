from text_utils import truncate

def test_truncate_boundary():
    # Exactly at boundary length, should not append '...'
    assert truncate("hello", 5) == "hello"

def test_truncate_long():
    assert truncate("hello world", 5) == "hello..."

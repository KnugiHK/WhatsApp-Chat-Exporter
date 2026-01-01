import os
import json
import pytest
from unittest.mock import patch, mock_open, call, MagicMock
from Whatsapp_Chat_Exporter.utility import incremental_merge
from Whatsapp_Chat_Exporter.data_model import ChatStore

# Test data setup
BASE_PATH = "AppDomainGroup-group.net.whatsapp.WhatsApp.shared"
chat_data_1 = {
    "12345678@s.whatsapp.net": {
        "name": "Friend",
        "type": "ios",
        "my_avatar": os.path.join(BASE_PATH, "Media", "Profile", "Photo.jpg"),
        "their_avatar": os.path.join(BASE_PATH, "Media", "Profile", "12345678-1709851420.thumb"),
        "their_avatar_thumb": None,
        "status": None,
        "messages": {
            "24690": {
                "from_me": True,
                "timestamp": 1463926635.571629,
                "time": "10:17",
                "media": False,
                "key_id": "34B5EF10FBCA37B7E",
                "meta": False,
                "data": "I'm here",
                "safe": False,
                "sticker": False
            },
            "24691": {  # This message only exists in target
                "from_me": False,
                "timestamp": 1463926641.571629,
                "time": "10:17",
                "media": False,
                "key_id": "34B5EF10FBCA37B8E",
                "meta": False,
                "data": "Great to see you",
                "safe": False,
                "sticker": False
            }
        }
    }
}

chat_data_2 = {
    "12345678@s.whatsapp.net": {
        "name": "Friend",
        "type": "ios",
        "my_avatar": os.path.join(BASE_PATH, "Media", "Profile", "Photo.jpg"),
        "their_avatar": os.path.join(BASE_PATH, "Media", "Profile", "12345678-1709851420.thumb"),
        "their_avatar_thumb": None,
        "status": None,
        "messages": {
            "24690": {
                "from_me": True,
                "timestamp": 1463926635.571629,
                "time": "10:17",
                "media": False,
                "key_id": "34B5EF10FBCA37B7E",
                "meta": False,
                "data": "I'm here",
                "safe": False,
                "sticker": False
            },
            "24692": {  # This message only exists in source
                "from_me": False,
                "timestamp": 1463926642.571629,
                "time": "10:17",
                "media": False,
                "key_id": "34B5EF10FBCA37B9E",
                "meta": False,
                "data": "Hi there!",
                "safe": False,
                "sticker": False
            },
        }
    }
}

# Expected merged data - should contain all messages with all fields initialized as they would be by Message class
chat_data_merged = {
    "12345678@s.whatsapp.net": {
        "name": "Friend",
        "type": "ios",
        "my_avatar": os.path.join(BASE_PATH, "Media", "Profile", "Photo.jpg"),
        "their_avatar": os.path.join(BASE_PATH, "Media", "Profile", "12345678-1709851420.thumb"),
        "their_avatar_thumb": None,
        "status": None,
        "media_base": "",
        "messages": {
            "24690": {
                "from_me": True,
                "timestamp": 1463926635.571629,
                "time": "10:17",
                "media": False,
                "key_id": "34B5EF10FBCA37B7E",
                "meta": False,
                "data": "I'm here",
                "sender": None,
                "safe": False,
                "mime": None,
                "reply": None,
                "quoted_data": None,
                "caption": None,
                "thumb": None,
                "sticker": False,
                "message_type": None,
                "received_timestamp": None,
                "read_timestamp": None
            },
            "24691": {
                "from_me": False,
                "timestamp": 1463926641.571629,
                "time": "10:17",
                "media": False,
                "key_id": "34B5EF10FBCA37B8E",
                "meta": False,
                "data": "Great to see you",
                "sender": None,
                "safe": False,
                "mime": None,
                "reply": None,
                "quoted_data": None,
                "caption": None,
                "thumb": None,
                "sticker": False,
                "message_type": None,
                "received_timestamp": None,
                "read_timestamp": None
            },
            "24692": {
                "from_me": False,
                "timestamp": 1463926642.571629,
                "time": "10:17",
                "media": False,
                "key_id": "34B5EF10FBCA37B9E",
                "meta": False,
                "data": "Hi there!",
                "sender": None,
                "safe": False,
                "mime": None,
                "reply": None,
                "quoted_data": None,
                "caption": None,
                "thumb": None,
                "sticker": False,
                "message_type": None,
                "received_timestamp": None,
                "read_timestamp": None
            },
        }
    }
}


@pytest.fixture
def mock_filesystem():
    with (
        patch("os.path.exists") as mock_exists,
        patch("os.makedirs") as mock_makedirs,
        patch("os.path.getmtime") as mock_getmtime,
        patch("os.listdir") as mock_listdir,
        patch("os.walk") as mock_walk,
        patch("shutil.copy2") as mock_copy2,
    ):
        yield {
            "exists": mock_exists,
            "makedirs": mock_makedirs,
            "getmtime": mock_getmtime,
            "listdir": mock_listdir,
            "walk": mock_walk,
            "copy2": mock_copy2,
        }


def test_incremental_merge_new_file(mock_filesystem):
    """Test merging when target file doesn't exist"""
    source_dir = "/source"
    target_dir = "/target"
    media_dir = "media"

    # Setup mock filesystem
    mock_filesystem["exists"].side_effect = lambda x: x == "/source"
    mock_filesystem["listdir"].return_value = ["chat.json"]

    # Run the function
    incremental_merge(source_dir, target_dir, media_dir, 2, True)

    # Verify the operations
    mock_filesystem["makedirs"].assert_called_once_with(target_dir, exist_ok=True)
    mock_filesystem["copy2"].assert_called_once_with(
        os.path.join(source_dir, "chat.json"),
        os.path.join(target_dir, "chat.json")
    )


def test_incremental_merge_existing_file_with_changes(mock_filesystem):
    """Test merging when target file exists and has changes"""
    source_dir = "source"
    target_dir = "target"
    media_dir = "media"

    # Setup mock filesystem
    mock_filesystem["exists"].side_effect = lambda x: True
    mock_filesystem["listdir"].return_value = ["chat.json"]

    # Mock file operations with consistent path separators
    source_file = os.path.join(source_dir, "chat.json")
    target_file = os.path.join(target_dir, "chat.json")
    mock_file_content = {
        source_file: json.dumps(chat_data_2),
        target_file: json.dumps(chat_data_1),
    }

    written_chunks = []

    def mock_file_write(data):
        written_chunks.append(data)

    mock_write = MagicMock(side_effect=mock_file_write)

    with patch("builtins.open", mock_open()) as mock_file:
        def mock_file_read(filename, mode="r"):
            if mode == 'w':
                file_mock = mock_open().return_value
                file_mock.write.side_effect = mock_write
                return file_mock
            else:
                # Use normalized path for lookup
                norm_filename = os.path.normpath(filename)
                content = mock_file_content.get(norm_filename, '')
                file_mock = mock_open(read_data=content).return_value
                return file_mock

        mock_file.side_effect = mock_file_read

        # Run the function
        incremental_merge(source_dir, target_dir, media_dir, 2, True)

        # Verify file operations using os.path.join
        mock_file.assert_any_call(source_file, "r")
        mock_file.assert_any_call(target_file, "r")
        mock_file.assert_any_call(target_file, "w")

        # Rest of verification code...
        assert mock_write.called, "Write method was never called"
        written_data = json.loads(''.join(written_chunks))
        assert written_data is not None, "No data was written"
        assert written_data == chat_data_merged, "Merged data does not match expected result"

        messages = written_data["12345678@s.whatsapp.net"]["messages"]
        assert "24690" in messages, "Common message should be present"
        assert "24691" in messages, "Target-only message should be preserved"
        assert "24692" in messages, "Source-only message should be added"
        assert len(messages) == 3, "Should have exactly 3 messages"


def test_incremental_merge_existing_file_no_changes(mock_filesystem):
    """Test merging when target file exists but has no changes"""
    source_dir = "source"
    target_dir = "target"
    media_dir = "media"

    # Setup mock filesystem
    mock_filesystem["exists"].side_effect = lambda x: True
    mock_filesystem["listdir"].return_value = ["chat.json"]

    # Mock file operations with consistent path separators
    source_file = os.path.join(source_dir, "chat.json")
    target_file = os.path.join(target_dir, "chat.json")
    mock_file_content = {
        source_file: json.dumps(chat_data_1),
        target_file: json.dumps(chat_data_1),
    }

    with patch("builtins.open", mock_open()) as mock_file:
        def mock_file_read(filename, mode="r"):
            if mode == 'w':
                file_mock = mock_open().return_value
                return file_mock
            else:
                # Use normalized path for lookup
                norm_filename = os.path.normpath(filename)
                content = mock_file_content.get(norm_filename, '')
                file_mock = mock_open(read_data=content).return_value
                return file_mock

        mock_file.side_effect = mock_file_read

        # Run the function
        incremental_merge(source_dir, target_dir, media_dir, 2, True)

        # Verify no write operations occurred on target file
        write_calls = [
            call for call in mock_file.mock_calls if call[0] == "().write"]
        assert len(write_calls) == 0


def test_incremental_merge_media_copy(mock_filesystem):
    """Test media file copying during merge"""
    source_dir = "source"
    target_dir = "target"
    media_dir = "media"

    # Setup mock filesystem
    mock_filesystem["exists"].side_effect = lambda x: True
    mock_filesystem["listdir"].return_value = ["chat.json"]
    mock_filesystem["walk"].return_value = [
        (os.path.join(source_dir, "media"), ["subfolder"], ["file1.jpg"]),
        (os.path.join(source_dir, "media", "subfolder"), [], ["file2.jpg"]),
    ]
    mock_filesystem["getmtime"].side_effect = lambda x: 1000 if "source" in x else 500

    # Mock file operations with consistent path separators
    source_file = os.path.join(source_dir, "chat.json")
    target_file = os.path.join(target_dir, "chat.json")
    mock_file_content = {
        source_file: json.dumps(chat_data_1),
        target_file: json.dumps(chat_data_1),
    }

    with patch("builtins.open", mock_open()) as mock_file:
        def mock_file_read(filename, mode="r"):
            if mode == 'w':
                file_mock = mock_open().return_value
                return file_mock
            else:
                # Use normalized path for lookup
                norm_filename = os.path.normpath(filename)
                content = mock_file_content.get(norm_filename, '')
                file_mock = mock_open(read_data=content).return_value
                return file_mock

        mock_file.side_effect = mock_file_read

        # Run the function
        incremental_merge(source_dir, target_dir, media_dir, 2, True)

        # Verify media file operations
        assert mock_filesystem["makedirs"].call_count >= 2  # At least target dir and media dir
        assert mock_filesystem["copy2"].call_count == 2  # Two media files copied

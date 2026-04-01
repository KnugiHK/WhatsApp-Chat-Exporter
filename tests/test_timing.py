from Whatsapp_Chat_Exporter.data_model import Timing


def test_format_timestamp_with_none_timezone_offset_does_not_crash():
    timing = Timing(None)

    assert timing.format_timestamp(1_700_000_000, "%Y") == "2023"

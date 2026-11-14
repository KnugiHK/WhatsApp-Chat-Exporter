import os
import time
import pytest
from Whatsapp_Chat_Exporter.data_model import Message, TimeZone, Timing
from datetime import timedelta


class TestTimeZone:
    def test_utcoffset(self):
        tz = TimeZone(5.5)
        assert tz.utcoffset(None) == timedelta(hours=5.5)

    def test_dst(self):
        tz = TimeZone(2)
        assert tz.dst(None) == timedelta(0)


class TestTiming:   
    @pytest.mark.parametrize("offset, expected_hour", [
        (8, "08:00"),      # Integer (e.g., Hong Kong Standard Time)
        (-8, "16:00"),     # Negative Integer (e.g., PST)
        (5.5, "05:30"),    # Positive Float (e.g., IST)
        (-3.5, "20:30"),   # Negative Float (e.g., Newfoundland)
    ])

    def test_format_timestamp_various_offsets(self, offset, expected_hour):
        """Verify that both int and float offsets calculate time correctly."""
        t = Timing(offset)
        result = t.format_timestamp(1672531200, "%H:%M")
        assert result == expected_hour

    @pytest.mark.parametrize("ts_input", [
        1672531200,        # Unix timestamp as int
        1672531200.0,      # Unix timestamp as float
    ])

    def test_timestamp_input_types(self, ts_input):
        """Verify the method accepts both int and float timestamps."""
        t = Timing(0)
        result = t.format_timestamp(ts_input, "%Y")
        assert result == "2023"

    def test_timing_none_offset(self):
        """Verify initialization with None doesn't crash and uses system time."""
        t = Timing(None)
        assert t.tz is None
        # Should still return a valid string based on local machine time without crashing
        result = t.format_timestamp(1672531200, "%Y")
        assert result == "2023"

    def test_millisecond_scaling(self):
        """Verify that timestamps in milliseconds are correctly scaled down."""
        t = Timing(0)
        # Milliseconds as int
        assert t.format_timestamp(1672531200000, "%Y") == "2023"
        # Milliseconds as float
        assert t.format_timestamp(1672531200000.0, "%Y") == "2023"

    def test_format_timestamp_none_returns_none(self):
        """Verify that passing None returns None without raising an error."""
        t = Timing(0)
        assert t.format_timestamp(None, "%Y-%m-%d") is None

    @pytest.mark.parametrize("invalid_ts", [
        0,           # Exact Unix epoch (non-positive)
        -1,          # Negative integer
        -1672531200, # Distant past timestamp
        -0.001,      # Negative float
    ])
    def test_format_timestamp_non_positive_returns_none(self, invalid_ts):
        """Verify that timestamps <= 0 return None."""
        t = Timing(0)
        assert t.format_timestamp(invalid_ts, "%Y-%m-%d") is None

    @pytest.mark.parametrize("boundary_ts, expected_year", [
        (9_999_999_999, "2286"),         # Exact cutoff boundary (treated as seconds)
        (10_000_000_000, "1970"),        # Value > 9999999999 (divided by 1000 => seconds in 1970)
        (10_000_000_000_000, "2286"),    # Large millisecond timestamp
    ])
    def test_millisecond_cutoff_boundary(self, boundary_ts, expected_year):
        """Verify behavior right around the 9,999,999,999 millisecond detection boundary."""
        t = Timing(0)
        assert t.format_timestamp(boundary_ts, "%Y") == expected_year

    def test_format_timestamp_overflow_raises_value_error(self):
        """Verify extreme out-of-range timestamps raise ValueError via the try/except block."""
        t = Timing(0)
        with pytest.raises(ValueError, match="Failed to format timestamp"):
            t.format_timestamp(1e25, "%Y-%m-%d")


@pytest.fixture
def local_tz(monkeypatch):
    if not hasattr(time, "tzset"):
        pytest.skip("TZ environment variable requires time.tzset")

    def _set(tz):
        monkeypatch.setenv("TZ", tz)
        time.tzset()

    yield _set
    monkeypatch.undo()
    time.tzset()


class TestTimingLocalZone:
    @pytest.mark.parametrize("tz, expected", [
        ("<-03>3", "2022/12/31 22:30"),
        ("<+07>-7", "2023/01/01 08:30"),
    ])
    def test_local_zone_date_and_time(self, local_tz, tz, expected):
        """Verify that the local zone is used when no offset is given."""
        local_tz(tz)
        assert Timing(None).format_timestamp(1672536600, "%Y/%m/%d %H:%M") == expected

    @pytest.mark.parametrize("tz, expected_time, expected_received", [
        ("<-03>3", "22:30", "2022/12/31 22:30"),
        ("<+07>-7", "08:30", "2023/01/01 08:30"),
    ])
    def test_message_in_local_zone(self, local_tz, tz, expected_time, expected_received):
        """Verify message time and date fields in the local zone."""
        local_tz(tz)
        message = Message(
            from_me=False,
            timestamp=1672536600000,
            time=1672536600000,
            key_id=1,
            received_timestamp=1672536600000,
            timezone_offset=Timing(None),
        )
        assert message.time == expected_time
        assert message.received_timestamp == expected_received

    def test_explicit_offset_ignores_local_zone(self, local_tz):
        """Verify that an explicit offset takes precedence over the local zone."""
        local_tz("<-03>3")
        assert Timing(7).format_timestamp(1672536600, "%Y/%m/%d %H:%M") == "2023/01/01 08:30"

    @pytest.mark.skipif(
        not os.path.exists("/usr/share/zoneinfo/America/Sao_Paulo"),
        reason="IANA time zone database is not available",
    )
    @pytest.mark.parametrize("timestamp, expected", [
        (1516017600, "2018/01/15 10:00"),
        (1673784000, "2023/01/15 09:00"),
    ])
    def test_local_zone_historical_dst(self, local_tz, timestamp, expected):
        """Verify that past daylight saving time rules of the local zone are applied."""
        local_tz("America/Sao_Paulo")
        assert Timing(None).format_timestamp(timestamp, "%Y/%m/%d %H:%M") == expected

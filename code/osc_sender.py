import math
import time

from pythonosc.udp_client import SimpleUDPClient


class OscSender:
    MCFX_MAX_CHANNELS = 128
    MCFX_PARAMS_PER_CHANNEL = 6
    MCFX_GAIN_MIN_DB = -18.0
    MCFX_GAIN_MAX_DB = 18.0
    MCFX_MAX_DELAY_MS = 1000.0
    MCFX_GENERATOR_LEVEL_DB = -30.0

    def __init__(self, host: str = "127.0.0.1", port: int = 8001):
        self.client = SimpleUDPClient(host, port)          # MultiEncoder portu
        self.scene_client = SimpleUDPClient(host, 8002)    # SceneRotator portu
        self.reaper_client = SimpleUDPClient(host, 8000)   # REAPER OSC control surface
        self._last_active_count = None
        self._last_active_send_time = 0.0
        self._last_speaker_state = {}
        self._last_generator_state = {}
        self._last_listener_state = None
        self._last_listener_send_time = 0.0
        self.refresh_interval_s = 1.0

    def send_speaker_params(self, speaker_result: dict):
        speaker_id = speaker_result["id"]
        iem_index = speaker_id - 1
        dynamic_state = (
            float(speaker_result["azimuth_deg"]),
            float(speaker_result["elevation_deg"]),
            float(speaker_result["gain_db"]),
            float(speaker_result["delay_ms"]),
        )
        gain_a_db, gain_b_db, applied_gain_db = self.split_mcfx_gain_db(
            speaker_result["gain_db"]
        )
        now = time.monotonic()
        previous = self._last_speaker_state.get(speaker_id)
        if (
            previous
            and previous[0] == dynamic_state
            and now - previous[1] < self.refresh_interval_s
        ):
            return applied_gain_db
        self._last_speaker_state[speaker_id] = (dynamic_state, now)

        self.client.send_message(
            f"/MultiEncoder/azimuth{iem_index}",
            float(speaker_result["azimuth_deg"])
        )

        self.client.send_message(
            f"/MultiEncoder/elevation{iem_index}",
            float(speaker_result["elevation_deg"])
        )

        self.client.send_message(
            f"/MultiEncoder/gain{iem_index}",
            0.0
        )

        delay_ms = max(
            0.0,
            min(self.MCFX_MAX_DELAY_MS, float(speaker_result["delay_ms"])),
        )

        self.reaper_client.send_message(
            f"/track/{speaker_id}/fx/1/fxparam/1/value",
            self.mcfx_gain_to_normalized(gain_a_db),
        )
        self.reaper_client.send_message(
            f"/track/{speaker_id}/fx/2/fxparam/1/value",
            delay_ms / 100.0,
        )
        self.reaper_client.send_message(
            f"/track/{speaker_id}/fx/3/fxparam/1/value",
            self.mcfx_gain_to_normalized(gain_b_db),
        )
        self.send_mcfx_generator_setup(
            speaker_id,
            float(speaker_result.get("frequency_hz") or 440.0),
        )
        return applied_gain_db

    @classmethod
    def split_mcfx_gain_db(cls, requested_gain_db):
        applied = max(
            2.0 * cls.MCFX_GAIN_MIN_DB,
            min(0.0, float(requested_gain_db)),
        )
        gain_a = max(cls.MCFX_GAIN_MIN_DB, applied)
        gain_b = applied - gain_a
        return gain_a, gain_b, applied

    @classmethod
    def mcfx_gain_to_normalized(cls, gain_db):
        clamped = max(
            cls.MCFX_GAIN_MIN_DB,
            min(cls.MCFX_GAIN_MAX_DB, float(gain_db)),
        )
        return (clamped - cls.MCFX_GAIN_MIN_DB) / (
            cls.MCFX_GAIN_MAX_DB - cls.MCFX_GAIN_MIN_DB
        )

    @staticmethod
    def mcfx_frequency_to_normalized(frequency_hz):
        frequency_hz = max(10.0, min(21618.0, float(frequency_hz)))
        return (math.log2(frequency_hz) - 3.33) / 11.07

    def send_mcfx_generator_setup(self, speaker_id, frequency_hz):
        generator_state = round(float(frequency_hz), 6)
        if self._last_generator_state.get(speaker_id) == generator_state:
            return
        self._last_generator_state[speaker_id] = generator_state

        global_start = (
            self.MCFX_MAX_CHANNELS * self.MCFX_PARAMS_PER_CHANNEL + 1
        )
        generator_gain = (
            self.MCFX_GENERATOR_LEVEL_DB + 99.0
        ) / 105.0
        sine_type = 2.0 / 6.0

        messages = (
            (6, 1.0),  # Channel 1 signal generator enabled.
            (global_start, generator_gain),
            (global_start + 1, sine_type),
            (global_start + 2, 0.0),  # Steady signal.
            (
                global_start + 3,
                self.mcfx_frequency_to_normalized(frequency_hz),
            ),
        )
        for parameter, value in messages:
            self.reaper_client.send_message(
                f"/track/{speaker_id}/fx/1/fxparam/{parameter}/value",
                value,
            )
        self.reaper_client.send_message(
            f"/track/{speaker_id}/fx/3/fxparam/6/value",
            0.0,
        )

    def send_active_source_count(self, active_count: int, maximum_sources: int = 8):
        now = time.monotonic()
        if (
            active_count == self._last_active_count
            and now - self._last_active_send_time < self.refresh_interval_s
        ):
            return

        for iem_index in range(maximum_sources):
            self.client.send_message(
                f"/MultiEncoder/mute{iem_index}",
                0.0 if iem_index < active_count else 1.0,
            )
            self.reaper_client.send_message(
                f"/track/{iem_index + 1}/mute",
                0.0 if iem_index < active_count else 1.0,
            )
        self._last_active_count = active_count
        self._last_active_send_time = now

    def send_listener(self, listener: dict):
        yaw = float(listener.get("yaw_deg", 0.0))
        pitch = 0.0
        roll = 0.0
        state = (yaw, pitch, roll)
        now = time.monotonic()
        if (
            state == self._last_listener_state
            and now - self._last_listener_send_time < self.refresh_interval_s
        ):
            return
        self._last_listener_state = state
        self._last_listener_send_time = now

        self.scene_client.send_message("/SceneRotator/yaw", yaw)
        self.scene_client.send_message("/SceneRotator/pitch", pitch)
        self.scene_client.send_message("/SceneRotator/roll", roll)

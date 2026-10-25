import json
import math
import tempfile
from pathlib import Path

from setup_state import (
    SETUP_COUNTS,
    SetupState,
    UserPresetStore,
    generate_speakers,
    player_angle_to_audio_yaw,
)


CONFIG_PATH = Path(__file__).with_name("example_room.json")
config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
rooms = {room["id"]: room for room in config["rooms"]}

assert player_angle_to_audio_yaw(0.0) == -90.0
assert player_angle_to_audio_yaw(math.pi / 2) == -180.0
assert player_angle_to_audio_yaw(math.pi) == 90.0
assert player_angle_to_audio_yaw(-math.pi / 2) == 0.0

for room in rooms.values():
    for setup_name, expected_count in SETUP_COUNTS.items():
        speakers = generate_speakers(room, setup_name)
        assert len(speakers) == expected_count
        for speaker in speakers:
            assert 0.0 <= speaker["x"] <= room["width_m"]
            assert 0.0 <= speaker["y"] <= room["depth_m"]
            assert 0.0 <= speaker["z"] <= room["height_m"]

state = SetupState(config)
state.select_setup("Stereo")
small_positions = [(speaker["x"], speaker["y"]) for speaker in state.speakers]
state.select_room("room_b")
medium_positions = [(speaker["x"], speaker["y"]) for speaker in state.speakers]
assert small_positions != medium_positions
assert state.setup_name == "Stereo"

state.set_speaker_position(0, x=2.25, y=1.75, z=1.4)
assert state.setup_name == "Custom"
assert state.selected_speaker["x"] == 2.25
state.set_custom_speaker_count(6)
assert len(state.speakers) == 6
assert state.speakers[0]["x"] == 2.25
state.set_custom_speaker_count(3)
assert len(state.speakers) == 3
assert [speaker["id"] for speaker in state.speakers] == [1, 2, 3]

with tempfile.TemporaryDirectory() as directory:
    store = UserPresetStore(Path(directory) / "user_presets.json")
    preset = state.to_preset("Test Preset")
    assert store.save(preset)
    loaded = store.load_all()
    assert len(loaded) == 1
    assert loaded[0]["speakers"] == preset["speakers"]

    restored = SetupState(config)
    restored.apply_preset(loaded[0])
    assert restored.room_id == state.room_id
    assert restored.speakers == state.speakers

print("Setup state checks passed.")

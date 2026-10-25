import json
from copy import deepcopy
from pathlib import Path
from room_model import RoomModel
from osc_sender import OscSender


with open(Path("example_room.json"), "r", encoding="utf-8") as f:
    config = json.load(f)

model = RoomModel(config)
results = model.calculate_all_speakers()

print("One-shot room calculation test:")
for r in results:
    print(r)

assert model.room["id"] == "room_a"
assert len(results) == 4
assert all(result["gain"] <= 1.0 for result in results)
listener = {"x": 0.0, "y": 0.0, "z": 0.0, "yaw_deg": 0.0}
model.listener = listener
cardinal_sources = {
    "front": ({"id": 91, "x": 0.0, "y": -1.0, "z": 0.0}, 0.0),
    "left": ({"id": 92, "x": -1.0, "y": 0.0, "z": 0.0}, 90.0),
    "right": ({"id": 93, "x": 1.0, "y": 0.0, "z": 0.0}, -90.0),
    "back": ({"id": 94, "x": 0.0, "y": 1.0, "z": 0.0}, 180.0),
}
for source, expected_azimuth in cardinal_sources.values():
    actual = model.calculate_speaker(source)["azimuth_deg"]
    if abs(expected_azimuth) == 180.0:
        assert abs(abs(actual) - 180.0) < 1e-9
    else:
        assert abs(actual - expected_azimuth) < 1e-9
model.listener = deepcopy(config["listener"])

model.set_listener_position(1.0, 0.8, 1.5)
near_result = model.calculate_speaker(model.speakers[0])
assert near_result["gain"] <= 1.0
model.set_listener_position(
    model.room["width_m"] / 2,
    model.room["depth_m"] / 2,
    config["listener"]["z"],
)

test_speaker = {"id": 99, "x": 0.0, "y": 0.0, "z": 0.0}
model.listener = {"x": 2.0, "y": 0.0, "z": 0.0, "yaw_deg": 0.0}
gain_at_2m = model.calculate_speaker(test_speaker)["gain_db"]
model.listener["x"] = 4.0
gain_at_4m = model.calculate_speaker(test_speaker)["gain_db"]
assert abs((gain_at_4m - gain_at_2m) + 6.0205999133) < 1e-6
model.set_distance_rolloff(1.660964)
model.listener["x"] = 2.0
gain_at_2m = model.calculate_speaker(test_speaker)["gain_db"]
model.listener["x"] = 4.0
gain_at_4m = model.calculate_speaker(test_speaker)["gain_db"]
assert abs((gain_at_4m - gain_at_2m) + 10.0) < 0.01
model.set_distance_rolloff(1.0)
model.listener = deepcopy(config["listener"])

before_yaw = [
    (r["distance_m"], r["gain"], r["delay_s"], r["azimuth_deg"], r["elevation_deg"])
    for r in model.calculate_all_speakers()
]
model.set_listener_yaw(90.0)
after_yaw = [
    (r["distance_m"], r["gain"], r["delay_s"], r["azimuth_deg"], r["elevation_deg"])
    for r in model.calculate_all_speakers()
]
assert before_yaw == after_yaw

model.set_active_speaker_count(2)
assert len(model.calculate_all_speakers()) == 2

model.set_speaker_position(1, x=2.5, y=1.25, z=1.6)
assert model.speakers[0]["x"] == 2.5
assert model.speakers[0]["y"] == 1.25
assert model.speakers[0]["z"] == 1.6

model.set_active_room("room_b")
assert model.room["id"] == "room_b"
assert model.room["width_m"] == 8.0

legacy_config = {
    "room": {
        "width_m": 6.0,
        "depth_m": 4.0,
        "height_m": 3.0,
        "wall_absorption": 0.35,
    },
    "atmosphere": deepcopy(config["atmosphere"]),
    "listener": deepcopy(config["listener"]),
    "speakers": deepcopy(config["speaker_presets"]["4"]),
}
legacy_model = RoomModel(legacy_config)
assert len(legacy_model.calculate_all_speakers()) == 4

print("Regression checks passed.")

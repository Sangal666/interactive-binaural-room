import json
import math
from copy import deepcopy
from pathlib import Path


SETUP_COUNTS = {
    "Mono": 1,
    "Stereo": 2,
    "Quad": 4,
    "Octagon": 8,
}

FREQUENCIES = (440, 444, 448, 452, 456, 460, 464, 468)


def player_angle_to_audio_yaw(angle_radians):
    # Pygame heading: +X=0, +Y=+90°. AmbiX/IEM yaw:
    # front (-Y)=0°, left (-X)=+90°, right (+X)=-90°.
    yaw = -(angle_radians + math.pi / 2)
    while yaw > math.pi:
        yaw -= 2 * math.pi
    while yaw < -math.pi:
        yaw += 2 * math.pi
    return math.degrees(yaw)


def generate_speakers(room, setup_name):
    width = float(room["width_m"])
    depth = float(room["depth_m"])
    height = min(1.5, float(room["height_m"]) * 0.5)

    if setup_name == "Mono":
        points = [(0.5, 0.2)]
    elif setup_name == "Stereo":
        points = [(0.3, 0.2), (0.7, 0.2)]
    elif setup_name == "Quad":
        points = [(0.2, 0.2), (0.8, 0.2), (0.2, 0.8), (0.8, 0.8)]
    elif setup_name == "Octagon":
        points = []
        for index in range(8):
            angle = -math.pi / 2 + index * math.pi / 4
            points.append(
                (
                    0.5 + math.cos(angle) * 0.38,
                    0.5 + math.sin(angle) * 0.38,
                )
            )
    else:
        raise ValueError(f"Unknown setup: {setup_name}")

    speakers = []
    for index, (x_ratio, y_ratio) in enumerate(points):
        speakers.append(
            {
                "id": index + 1,
                "name": f"Source {index + 1}",
                "x": round(x_ratio * width, 4),
                "y": round(y_ratio * depth, 4),
                "z": height,
                "frequency_hz": FREQUENCIES[index],
            }
        )
    return speakers


def generate_custom_speakers(room, count):
    count = max(1, min(len(FREQUENCIES), int(count)))
    width = float(room["width_m"])
    depth = float(room["depth_m"])
    height = min(1.5, float(room["height_m"]) * 0.5)

    if count == 1:
        points = [(0.5, 0.2)]
    else:
        points = []
        for index in range(count):
            angle = -math.pi / 2 + index * (2 * math.pi / count)
            points.append(
                (
                    0.5 + math.cos(angle) * 0.38,
                    0.5 + math.sin(angle) * 0.38,
                )
            )

    return [
        {
            "id": index + 1,
            "name": f"Source {index + 1}",
            "x": round(x_ratio * width, 4),
            "y": round(y_ratio * depth, 4),
            "z": height,
            "frequency_hz": FREQUENCIES[index],
        }
        for index, (x_ratio, y_ratio) in enumerate(points)
    ]


class SetupState:
    def __init__(self, config):
        self.config = config
        self.rooms = {room["id"]: room for room in config["rooms"]}
        self.room_id = config.get("active_room_id", next(iter(self.rooms)))
        count = int(config.get("active_speaker_count", 4))
        self.setup_name = next(
            (name for name, value in SETUP_COUNTS.items() if value == count),
            "Quad",
        )
        self.speakers = generate_speakers(self.room, self.setup_name)
        self.selected_index = 0

    @property
    def room(self):
        return self.rooms[self.room_id]

    @property
    def selected_speaker(self):
        return self.speakers[self.selected_index]

    def select_room(self, room_id):
        if room_id not in self.rooms:
            raise ValueError(f"Unknown room: {room_id}")
        self.room_id = room_id
        if self.setup_name != "Custom":
            self.speakers = generate_speakers(self.room, self.setup_name)
        else:
            self._clamp_all_speakers()
        self.selected_index = min(self.selected_index, len(self.speakers) - 1)

    def select_setup(self, setup_name):
        if setup_name == "Custom":
            self.setup_name = "Custom"
            return
        self.speakers = generate_speakers(self.room, setup_name)
        self.setup_name = setup_name
        self.selected_index = min(self.selected_index, len(self.speakers) - 1)

    def set_custom_speaker_count(self, count):
        count = max(1, min(len(FREQUENCIES), int(count)))
        generated = generate_custom_speakers(self.room, count)
        preserved_count = min(len(self.speakers), count)
        generated[:preserved_count] = deepcopy(self.speakers[:preserved_count])
        for index, speaker in enumerate(generated):
            speaker["id"] = index + 1
            speaker["name"] = f"Source {index + 1}"
            speaker["frequency_hz"] = FREQUENCIES[index]
        self.speakers = generated
        self.setup_name = "Custom"
        self.selected_index = min(self.selected_index, count - 1)

    def reset(self):
        setup_name = self.setup_name if self.setup_name != "Custom" else "Quad"
        self.select_setup(setup_name)

    def set_speaker_position(self, index, x=None, y=None, z=None):
        speaker = self.speakers[index]
        if x is not None:
            speaker["x"] = self._clamp(float(x), 0.0, float(self.room["width_m"]))
        if y is not None:
            speaker["y"] = self._clamp(float(y), 0.0, float(self.room["depth_m"]))
        if z is not None:
            speaker["z"] = self._clamp(float(z), 0.0, float(self.room["height_m"]))
        self.setup_name = "Custom"

    def apply_preset(self, preset):
        room_id = preset.get("room_id")
        if room_id not in self.rooms:
            raise ValueError("Preset room is not available.")
        speakers = preset.get("speakers")
        if not speakers:
            raise ValueError("Preset does not contain speakers.")

        self.room_id = room_id
        self.setup_name = preset.get("setup_name", "Custom")
        self.speakers = deepcopy(speakers)
        self._clamp_all_speakers()
        self.selected_index = 0

    def to_preset(self, name):
        clean_name = name.strip()
        if not clean_name:
            raise ValueError("Preset name cannot be empty.")
        return {
            "name": clean_name,
            "room_id": self.room_id,
            "setup_name": self.setup_name,
            "speaker_count": len(self.speakers),
            "speakers": deepcopy(self.speakers),
        }

    def _clamp_all_speakers(self):
        for speaker in self.speakers:
            speaker["x"] = self._clamp(
                float(speaker["x"]),
                0.0,
                float(self.room["width_m"]),
            )
            speaker["y"] = self._clamp(
                float(speaker["y"]),
                0.0,
                float(self.room["depth_m"]),
            )
            speaker["z"] = self._clamp(
                float(speaker["z"]),
                0.0,
                float(self.room["height_m"]),
            )

    @staticmethod
    def _clamp(value, lower, upper):
        return min(upper, max(lower, value))


class UserPresetStore:
    def __init__(self, path):
        self.path = Path(path)
        self.error = ""

    def load_all(self):
        self.error = ""
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            presets = data.get("presets", [])
            if not isinstance(presets, list):
                raise ValueError("presets must be a list")
            return presets
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            self.error = f"Could not load user presets: {exc}"
            return []

    def save(self, preset):
        presets = self.load_all()
        presets = [item for item in presets if item.get("name") != preset["name"]]
        presets.append(preset)
        try:
            self.path.write_text(
                json.dumps({"presets": presets}, indent=2),
                encoding="utf-8",
            )
            self.error = ""
            return True
        except OSError as exc:
            self.error = f"Could not save user preset: {exc}"
            return False

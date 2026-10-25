import math
from typing import Dict, List


def speed_of_sound_from_temperature(temperature_c: float) -> float:
    """
    Basit ses hızı modeli.
    Yaklaşık: c = 331.3 + 0.606 * T
    T: Celsius
    """
    return 331.3 + 0.606 * temperature_c


def db_from_gain(gain: float) -> float:
    if gain <= 0:
        return -120.0
    return 20.0 * math.log10(gain)


def normalize_degrees(angle: float) -> float:
    """
    Açıyı -180 ile +180 arasına sıkıştırır.
    """
    while angle > 180.0:
        angle -= 360.0
    while angle < -180.0:
        angle += 360.0
    return angle


class RoomModel:
    """
    Oda, speaker ve listener değerlerinden spatial parametre hesaplar.

    Koordinat sistemi:
    - x: sol-sağ
    - y: ön-arka
    - z: yükseklik

    Azimuth:
    - oda koordinatlarına göre dünya-sabit yatay açı
    - listener orientation ayrı olarak SceneRotator tarafından uygulanır
    - derece cinsinden
    """

    def __init__(self, config: Dict):
        self.config = config
        self.room = self._resolve_active_room()
        self.atmosphere = config.get("atmosphere", {})
        self.listener = config["listener"]
        self.speakers = self._resolve_active_speakers()
        propagation = config.get("propagation", {})
        self.reference_distance_m = max(
            1e-6,
            float(propagation.get("reference_distance_m", 1.0)),
        )
        self.distance_rolloff = max(
            0.0,
            float(propagation.get("distance_rolloff", 1.0)),
        )

        self.speed_of_sound = speed_of_sound_from_temperature(
            self.atmosphere.get("temperature_c", 20.0)
        )

    def _resolve_active_room(self) -> Dict:
        if "rooms" not in self.config:
            return self.config["room"]

        active_room_id = self.config.get("active_room_id")
        rooms = self.config.get("rooms", [])

        for room in rooms:
            if room.get("id") == active_room_id:
                return room

        if rooms:
            return rooms[0]

        raise ValueError("Config must define at least one room.")

    def _resolve_active_speakers(self) -> List[Dict]:
        if "speaker_presets" not in self.config:
            return self.config["speakers"]

        speaker_count = int(self.config.get("active_speaker_count", 4))
        presets = self.config.get("speaker_presets", {})
        preset = presets.get(str(speaker_count))

        if preset is not None:
            return preset[:speaker_count]

        available_counts = sorted(int(count) for count in presets.keys())
        for count in available_counts:
            if count >= speaker_count:
                return presets[str(count)][:speaker_count]

        if available_counts:
            largest_count = available_counts[-1]
            return presets[str(largest_count)]

        raise ValueError("Config must define at least one speaker preset.")

    def set_active_room(self, room_id: str):
        if "rooms" in self.config and not any(
            room.get("id") == room_id for room in self.config["rooms"]
        ):
            raise ValueError(f"Unknown room: {room_id}")
        self.config["active_room_id"] = room_id
        self.room = self._resolve_active_room()

    def set_active_speaker_count(self, speaker_count: int):
        self.config["active_speaker_count"] = int(speaker_count)
        self.speakers = self._resolve_active_speakers()

    def set_distance_rolloff(self, distance_rolloff: float):
        self.distance_rolloff = max(0.0, float(distance_rolloff))
        self.config.setdefault("propagation", {})["distance_rolloff"] = (
            self.distance_rolloff
        )

    def set_speaker_position(
        self,
        speaker_id: int,
        x: float = None,
        y: float = None,
        z: float = None,
    ):
        for speaker in self.speakers:
            if speaker["id"] != int(speaker_id):
                continue

            if x is not None:
                speaker["x"] = min(
                    float(self.room["width_m"]),
                    max(0.0, float(x)),
                )
            if y is not None:
                speaker["y"] = min(
                    float(self.room["depth_m"]),
                    max(0.0, float(y)),
                )
            if z is not None:
                speaker["z"] = min(
                    float(self.room["height_m"]),
                    max(0.0, float(z)),
                )
            return

        raise ValueError(f"Speaker {speaker_id} is not active.")

    def set_listener_position(self, x: float, y: float, z: float = None):
        self.listener["x"] = min(
            float(self.room["width_m"]),
            max(0.0, float(x)),
        )
        self.listener["y"] = min(
            float(self.room["depth_m"]),
            max(0.0, float(y)),
        )
        if z is not None:
            self.listener["z"] = min(
                float(self.room["height_m"]),
                max(0.0, float(z)),
            )

    def set_listener_yaw(self, yaw_deg: float):
        self.listener["yaw_deg"] = float(yaw_deg)

    def calculate_all_speakers(self) -> List[Dict]:
        return [self.calculate_speaker(speaker) for speaker in self.speakers]

    def calculate_speaker(self, speaker: Dict) -> Dict:
        lx = self.listener["x"]
        ly = self.listener["y"]
        lz = self.listener["z"]

        sx = speaker["x"]
        sy = speaker["y"]
        sz = speaker["z"]

        dx = sx - lx
        dy = sy - ly
        dz = sz - lz

        horizontal_distance = math.sqrt(dx * dx + dy * dy)
        distance = math.sqrt(dx * dx + dy * dy + dz * dz)

        # AmbiX/IEM convention:
        # room front (-Y) = 0°, left (-X) = +90°, right (+X) = -90°.
        azimuth = math.degrees(math.atan2(-dx, -dy))
        relative_azimuth = normalize_degrees(azimuth)

        elevation = math.degrees(math.atan2(dz, max(horizontal_distance, 1e-9)))

        delay_seconds = distance / self.speed_of_sound
        delay_ms = delay_seconds * 1000.0

        # Free-field point-source pressure attenuation. The reference distance
        # prevents the idealized 1/r model from diverging near the source.
        distance_ratio = self.reference_distance_m / max(
            distance,
            self.reference_distance_m,
        )
        gain = distance_ratio ** self.distance_rolloff

        return {
            "id": speaker["id"],
            "name": speaker.get("name", f"Speaker {speaker['id']}"),
            "frequency_hz": speaker.get("frequency_hz"),
            "x": sx,
            "y": sy,
            "z": sz,
            "dx": dx,
            "dy": dy,
            "dz": dz,
            "distance_m": distance,
            "horizontal_distance_m": horizontal_distance,
            "azimuth_deg": relative_azimuth,
            "elevation_deg": elevation,
            "delay_s": delay_seconds,
            "delay_ms": delay_ms,
            "gain": gain,
            "gain_db": db_from_gain(gain),
        }

import json
import math
import threading
import time
from pathlib import Path
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient

from room_model import RoomModel
from osc_sender import OscSender


CONFIG_PATH = Path("example_room.json")

config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
model = RoomModel(config)
model_lock = threading.Lock()

osc_cfg = config.get("osc", {})
sender = OscSender(
    host=osc_cfg.get("host", "127.0.0.1"),
    port=osc_cfg.get("port", 8001),
)
feedback_sender = SimpleUDPClient(
    osc_cfg.get("host", "127.0.0.1"),
    osc_cfg.get("feedback_port", 9001),
)

dispatcher = Dispatcher()


def listener_x_handler(address, value):
    with model_lock:
        model.set_listener_position(float(value), model.listener["y"])


def listener_y_handler(address, value):
    with model_lock:
        model.set_listener_position(model.listener["x"], float(value))


def listener_z_handler(address, value):
    with model_lock:
        model.set_listener_position(
            model.listener["x"],
            model.listener["y"],
            float(value),
        )


def listener_yaw_handler(address, value):
    with model_lock:
        model.set_listener_yaw(float(value))


def active_room_handler(address, value):
    with model_lock:
        model.set_active_room(str(value))
        room_name = model.room.get("name", model.room.get("id", value))
    print("Active room:", room_name)


def speaker_count_handler(address, value):
    with model_lock:
        model.set_active_speaker_count(int(value))
        active_count = len(model.speakers)
    print("Active speakers:", active_count)


def distance_rolloff_handler(address, value):
    with model_lock:
        model.set_distance_rolloff(float(value))
        rolloff = model.distance_rolloff
    db_per_doubling = 20.0 * rolloff * math.log10(2.0)
    print(
        f"Distance rolloff: {rolloff:.3f} "
        f"(-{db_per_doubling:.1f} dB per distance doubling)"
    )


def speaker_position_handler(address, speaker_id, x, y, z):
    with model_lock:
        model.set_speaker_position(
            int(speaker_id),
            x=float(x),
            y=float(y),
            z=float(z),
        )
    print(
        f"Speaker {int(speaker_id)} position: "
        f"x={float(x):.2f}, y={float(y):.2f}, z={float(z):.2f}"
    )


dispatcher.map("/listener/x", listener_x_handler)
dispatcher.map("/listener/y", listener_y_handler)
dispatcher.map("/listener/z", listener_z_handler)
dispatcher.map("/listener/yaw", listener_yaw_handler)
dispatcher.map("/config/room", active_room_handler)
dispatcher.map("/config/speaker_count", speaker_count_handler)
dispatcher.map("/config/distance_rolloff", distance_rolloff_handler)
dispatcher.map("/speaker/position", speaker_position_handler)

server = ThreadingOSCUDPServer(("127.0.0.1", 9000), dispatcher)


def main():
    print("Interactive listener mode started.")
    print("Receiving listener OSC on 127.0.0.1:9000")
    print("Active room:", model.room.get("name", model.room.get("id", "room")))
    print("Active speakers:", len(model.speakers))
    print("Press Ctrl+C to stop.")

    server_thread = threading.Thread(target=server.serve_forever)
    server_thread.daemon = True
    server_thread.start()

    update_rate_hz = max(1.0, float(osc_cfg.get("update_rate_hz", 20)))
    update_interval = 1.0 / update_rate_hz
    last_status_print = 0.0

    try:
        while True:
            with model_lock:
                results = model.calculate_all_speakers()
                listener = dict(model.listener)

            sender.send_listener(listener)
            sender.send_active_source_count(len(results))

            for r in results:
                applied_gain_db = sender.send_speaker_params(r)
                feedback_sender.send_message(
                    "/source/state",
                    [
                        r["id"],
                        r["distance_m"],
                        r["azimuth_deg"],
                        r["elevation_deg"],
                        r["gain_db"],
                        applied_gain_db,
                        r["delay_ms"],
                    ],
                )

            now = time.monotonic()
            if now - last_status_print >= 1.0:
                print(
                    f"listener x={listener['x']:.2f}, "
                    f"y={listener['y']:.2f}, "
                    f"yaw={listener.get('yaw_deg', 0.0):.1f}"
                )
                last_status_print = now

            time.sleep(update_interval)

    except KeyboardInterrupt:
        server.shutdown()
        print("\\nStopped.")


if __name__ == "__main__":
    main()

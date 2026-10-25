import math

import osc_sender


class FakeClient:
    instances = []

    def __init__(self, host, port):
        self.host = host
        self.port = port
        self.messages = []
        self.instances.append(self)

    def send_message(self, address, value):
        self.messages.append((address, value))


osc_sender.SimpleUDPClient = FakeClient
sender = osc_sender.OscSender()
clients = {client.port: client for client in FakeClient.instances}

result = {
    "id": 2,
    "azimuth_deg": 45.0,
    "elevation_deg": 10.0,
    "gain_db": -6.0205999133,
    "delay_ms": 5.824,
}
sender.send_speaker_params(result)

assert ("/MultiEncoder/azimuth1", 45.0) in clients[8001].messages
assert ("/MultiEncoder/elevation1", 10.0) in clients[8001].messages
assert ("/MultiEncoder/gain1", 0.0) in clients[8001].messages

reaper_messages = dict(clients[8000].messages)
gain_a, gain_b, applied = sender.split_mcfx_gain_db(result["gain_db"])
assert abs(
    reaper_messages["/track/2/fx/1/fxparam/1/value"]
    - sender.mcfx_gain_to_normalized(gain_a)
) < 1e-9
assert abs(
    reaper_messages["/track/2/fx/2/fxparam/1/value"] - 0.05824
) < 1e-9
assert abs(
    reaper_messages["/track/2/fx/3/fxparam/1/value"]
    - sender.mcfx_gain_to_normalized(gain_b)
) < 1e-9
assert applied == result["gain_db"]
assert reaper_messages["/track/2/fx/1/fxparam/6/value"] == 1.0
assert reaper_messages["/track/2/fx/3/fxparam/6/value"] == 0.0

message_count = len(clients[8000].messages)
assert sender.send_speaker_params(result) == result["gain_db"]
assert len(clients[8000].messages) == message_count

for requested, expected in (
    (0.0, (0.0, 0.0, 0.0)),
    (-18.0, (-18.0, 0.0, -18.0)),
    (-26.0, (-18.0, -8.0, -26.0)),
    (-36.0, (-18.0, -18.0, -36.0)),
    (-50.0, (-18.0, -18.0, -36.0)),
):
    assert sender.split_mcfx_gain_db(requested) == expected

trim_db = sender.send_active_source_count(4)
reaper_messages = dict(clients[8000].messages)
assert trim_db is None
assert reaper_messages["/track/5/mute"] == 1.0

sender.send_listener({"yaw_deg": 90.0})
assert ("/SceneRotator/yaw", 90.0) in clients[8002].messages

print("OSC mapping checks passed.")

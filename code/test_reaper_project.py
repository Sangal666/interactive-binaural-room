import base64
from pathlib import Path


PROJECT_PATH = Path(__file__).resolve().parent.parent / "Project1.RPP"
project = PROJECT_PATH.read_text(encoding="utf-8")

assert project.count("  <TRACK ") == 9
assert project.count("mcfx_gain_delay.vst3") == 16
assert project.count("<JS TEZ/TEZ_Smooth_Propagation_Delay") == 8
assert "<JS synthesis/tonegenerator" not in project
assert "<JS TEZ/TEZ_DirectSound_GainDelay" not in project
assert project.count("    AUXRECV ") == 8
assert project.count("    MAINSEND 0 0") == 8

for plugin in (
    "MultiEncoder.vst3",
    "SceneRotator.vst3",
    "EnergyVisualizer.vst3",
    "BinauralDecoder.vst3",
):
    assert plugin in project

scene_start = project.index('<VST "VST3: SceneRotator')
scene_end = project.index("\n      >", scene_start)
chunks = []
for line in project[scene_start:scene_end].splitlines()[1:]:
    try:
        chunks.append(base64.b64decode(line.strip(), validate=True))
    except ValueError:
        pass
scene_state = b"".join(chunks[3:])
assert b'invertYaw" value="1.0"' in scene_state
assert b'ReceiverPort="8002"' in scene_state

print("REAPER project checks passed.")

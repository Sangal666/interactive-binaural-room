import json
import math
import os
import threading
from pathlib import Path

import pygame
from pythonosc.dispatcher import Dispatcher
from pythonosc.osc_server import ThreadingOSCUDPServer
from pythonosc.udp_client import SimpleUDPClient

from setup_state import (
    SETUP_COUNTS,
    SetupState,
    UserPresetStore,
    player_angle_to_audio_yaw,
)


WIDTH = 1200
HEIGHT = 700
HALF_HEIGHT = HEIGHT // 2
CONFIG_PATH = Path(__file__).with_name("example_room.json")
USER_PRESETS_PATH = Path(__file__).with_name("user_presets.json")

WORLD_MAP = [
    "##########",
    "#........#",
    "#........#",
    "#........#",
    "#........#",
    "#........#",
    "#........#",
    "#........#",
    "#........#",
    "##########",
]

FOV = math.pi / 3
HALF_FOV = FOV / 2
NUM_RAYS = 120
MAX_DEPTH = 20
DELTA_ANGLE = FOV / NUM_RAYS
SCALE = WIDTH / NUM_RAYS
MOVE_SPEED = 0.045
ROT_SPEED = 0.003

config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
state = SetupState(config)
preset_store = UserPresetStore(USER_PRESETS_PATH)
user_presets = preset_store.load_all()

client = SimpleUDPClient("127.0.0.1", 9000)
source_states = {}

player_x = 5.0
player_y = 5.0
player_angle = 0.0
mode = "setup"
dragging_speaker = False
preset_name = "User Preset 1"
preset_name_active = False
loaded_preset_index = -1
status_message = preset_store.error

pygame.init()
screen = pygame.display.set_mode((WIDTH, HEIGHT))
pygame.display.set_caption("Spatial Audio Direct Sound Simulator")
clock = pygame.time.Clock()
font = pygame.font.SysFont(None, 24)
small_font = pygame.font.SysFont(None, 19)
title_font = pygame.font.SysFont(None, 36)
large_font = pygame.font.SysFont(None, 48)

pygame.mouse.set_visible(True)
pygame.event.set_grab(False)

room_buttons = []
setup_buttons = []
speaker_buttons = []
position_buttons = []
command_buttons = {}
custom_count_buttons = []
distance_mode_buttons = []
room_preview_rect = pygame.Rect(300, 175, 530, 390)
preset_name_rect = pygame.Rect(900, 480, 230, 38)
distance_rolloff = float(config.get("propagation", {}).get("distance_rolloff", 1.0))


def source_state_handler(
    address,
    source_id,
    distance,
    azimuth,
    elevation,
    gain_db,
    output_gain_db,
    delay_ms,
):
    if gain_db is None or output_gain_db is None:
        return
    source_states[int(source_id)] = {
        "distance_m": float(distance),
        "azimuth_deg": float(azimuth),
        "elevation_deg": float(elevation),
        "gain_db": float(gain_db),
        "output_gain_db": float(output_gain_db),
        "delay_ms": float(delay_ms),
    }


feedback_dispatcher = Dispatcher()
feedback_dispatcher.map("/source/state", source_state_handler)
try:
    feedback_server = ThreadingOSCUDPServer(("127.0.0.1", 9001), feedback_dispatcher)
    feedback_thread = threading.Thread(target=feedback_server.serve_forever, daemon=True)
    feedback_thread.start()
except OSError:
    feedback_server = None
    status_message = "Feedback port 9001 is busy; live HUD is unavailable."


def draw_button(rect, label, active=False, accent=False):
    if accent:
        fill = (30, 126, 108)
        border = (125, 235, 207)
    elif active:
        fill = (55, 116, 158)
        border = (140, 210, 235)
    else:
        fill = (35, 42, 52)
        border = (80, 93, 108)
    pygame.draw.rect(screen, fill, rect, border_radius=5)
    pygame.draw.rect(screen, border, rect, 2, border_radius=5)
    text = small_font.render(label, True, (244, 247, 249))
    screen.blit(text, text.get_rect(center=rect.center))


def draw_label(text, x, y, color=(176, 190, 202), selected=False):
    rendered = font.render(text, True, (235, 242, 246) if selected else color)
    screen.blit(rendered, (x, y))


def room_to_preview(x, y):
    room = state.room
    return (
        room_preview_rect.left + (x / room["width_m"]) * room_preview_rect.width,
        room_preview_rect.top + (y / room["depth_m"]) * room_preview_rect.height,
    )


def preview_to_room(x, y):
    room = state.room
    return (
        ((x - room_preview_rect.left) / room_preview_rect.width) * room["width_m"],
        ((y - room_preview_rect.top) / room_preview_rect.height) * room["depth_m"],
    )


def room_to_world(x, y):
    room = state.room
    return (
        1.0 + (x / room["width_m"]) * 8.0,
        1.0 + (y / room["depth_m"]) * 8.0,
    )


def world_to_room(x, y):
    room = state.room
    return (
        ((x - 1.0) / 8.0) * room["width_m"],
        ((y - 1.0) / 8.0) * room["depth_m"],
    )


def center_listener():
    global player_x, player_y
    player_x = 5.0
    player_y = 5.0


def send_configuration():
    client.send_message("/config/room", state.room_id)
    client.send_message("/config/speaker_count", len(state.speakers))
    client.send_message("/config/distance_rolloff", distance_rolloff)
    for speaker in state.speakers:
        client.send_message(
            "/speaker/position",
            [speaker["id"], speaker["x"], speaker["y"], speaker["z"]],
        )


def send_speaker_position(speaker):
    client.send_message(
        "/speaker/position",
        [speaker["id"], speaker["x"], speaker["y"], speaker["z"]],
    )


def enter_simulation():
    global mode, status_message
    send_configuration()
    mode = "simulation"
    status_message = ""
    pygame.mouse.set_visible(False)
    pygame.event.set_grab(True)
    pygame.mouse.get_rel()


def enter_setup():
    global mode, dragging_speaker
    mode = "setup"
    dragging_speaker = False
    pygame.mouse.set_visible(True)
    pygame.event.set_grab(False)


def is_wall(x, y):
    if x < 0 or y < 0 or y >= len(WORLD_MAP) or x >= len(WORLD_MAP[0]):
        return True
    return WORLD_MAP[int(y)][int(x)] == "#"


def normalize_angle(angle):
    while angle > math.pi:
        angle -= 2 * math.pi
    while angle < -math.pi:
        angle += 2 * math.pi
    return angle


def draw_setup_screen():
    global room_buttons, setup_buttons, speaker_buttons, position_buttons
    global command_buttons, custom_count_buttons, distance_mode_buttons

    screen.fill((10, 14, 18))
    pygame.draw.rect(screen, (18, 24, 30), (0, 0, WIDTH, 86))
    screen.blit(large_font.render("Direct Sound Setup", True, (240, 246, 248)), (40, 23))
    subtitle = small_font.render(
        "Direct sound only: room size changes distance, level and propagation delay",
        True,
        (137, 157, 170),
    )
    screen.blit(subtitle, (360, 39))

    pygame.draw.rect(screen, (18, 23, 29), (25, 110, 245, 555), border_radius=6)
    pygame.draw.rect(screen, (18, 23, 29), (855, 110, 320, 555), border_radius=6)

    draw_label("ROOM", 45, 132)
    room_buttons = []
    for index, room_id in enumerate(("room_a", "room_b", "room_c")):
        rect = pygame.Rect(45, 170 + index * 52, 205, 40)
        room_buttons.append((rect, room_id))
        room = state.rooms[room_id]
        label = (
            f"{room_id[-1].upper()}  "
            f"{room['width_m']:g} x {room['depth_m']:g} x {room['height_m']:g} m"
        )
        draw_button(rect, label, state.room_id == room_id)

    draw_label("SPEAKER SETUP", 45, 345)
    setup_buttons = []
    for index, setup_name in enumerate(("Mono", "Stereo", "Quad", "Octagon", "Custom")):
        rect = pygame.Rect(45, 380 + index * 48, 205, 36)
        setup_buttons.append((rect, setup_name))
        draw_button(rect, setup_name, state.setup_name == setup_name)

    custom_count_buttons = []
    if state.setup_name == "Custom":
        draw_label("COUNT", 45, 625)
        minus_rect = pygame.Rect(115, 620, 36, 30)
        plus_rect = pygame.Rect(210, 620, 36, 30)
        custom_count_buttons = [(minus_rect, -1), (plus_rect, 1)]
        draw_button(minus_rect, "-")
        draw_button(plus_rect, "+")
        count_text = font.render(str(len(state.speakers)), True, (237, 243, 246))
        screen.blit(count_text, count_text.get_rect(center=(181, 635)))

    draw_label("DISTANCE EFFECT", 300, 105)
    distance_mode_buttons = [
        (pygame.Rect(485, 103, 175, 34), 1.0),
        (pygame.Rect(670, 103, 160, 34), 1.660964),
    ]
    draw_button(
        distance_mode_buttons[0][0],
        "Physical  -6 dB / 2x",
        abs(distance_rolloff - 1.0) < 0.01,
    )
    draw_button(
        distance_mode_buttons[1][0],
        "Exaggerated Demo",
        abs(distance_rolloff - 1.660964) < 0.01,
    )

    pygame.draw.rect(screen, (13, 18, 23), room_preview_rect)
    pygame.draw.rect(screen, (104, 126, 139), room_preview_rect, 2)
    for index in range(1, 5):
        x = room_preview_rect.left + room_preview_rect.width * index / 5
        y = room_preview_rect.top + room_preview_rect.height * index / 5
        pygame.draw.line(screen, (31, 42, 49), (x, room_preview_rect.top), (x, room_preview_rect.bottom))
        pygame.draw.line(screen, (31, 42, 49), (room_preview_rect.left, y), (room_preview_rect.right, y))

    floor_area = state.room["width_m"] * state.room["depth_m"]
    room_title = font.render(
        f"{state.room['name']}  |  floor {floor_area:g} m2",
        True,
        (225, 233, 237),
    )
    screen.blit(room_title, (room_preview_rect.left, 135))

    listener_x, listener_y = world_to_room(player_x, player_y)
    listener_point = room_to_preview(listener_x, listener_y)
    pygame.draw.circle(screen, (245, 247, 248), listener_point, 7)
    pygame.draw.circle(screen, (45, 54, 60), listener_point, 7, 2)

    for index, speaker in enumerate(state.speakers):
        point = room_to_preview(speaker["x"], speaker["y"])
        selected = index == state.selected_index
        color = (102, 215, 235) if selected else (70, 144, 181)
        pygame.draw.circle(screen, color, point, 14 if selected else 11)
        pygame.draw.circle(screen, (225, 246, 250), point, 14 if selected else 11, 2)
        label = small_font.render(f"S{speaker['id']}", True, (8, 16, 20))
        screen.blit(label, label.get_rect(center=point))

    help_text = small_font.render(
        "Select a source, then drag it. Moving a preset changes the mode to Custom.",
        True,
        (135, 154, 166),
    )
    screen.blit(help_text, (room_preview_rect.left, 585))
    scale_note = small_font.render(
        "The plan auto-fits the screen; dimensions above are the real simulation scale.",
        True,
        (135, 154, 166),
    )
    screen.blit(scale_note, (room_preview_rect.left, 608))
    if abs(distance_rolloff - 1.0) >= 0.01:
        warning = small_font.render(
            "NON-PHYSICAL: presentation only; do not use for thesis measurements.",
            True,
            (242, 153, 105),
        )
        screen.blit(warning, (room_preview_rect.left, 631))

    draw_label("SOURCE", 880, 132)
    speaker_buttons = []
    for index, speaker in enumerate(state.speakers):
        row = index // 4
        column = index % 4
        rect = pygame.Rect(880 + column * 68, 168 + row * 44, 58, 34)
        speaker_buttons.append((rect, index))
        draw_button(rect, f"S{speaker['id']}", index == state.selected_index)

    selected = state.selected_speaker
    value_y = 270
    position_buttons = []
    for row, (axis, step, unit) in enumerate((("x", 0.25, "m"), ("y", 0.25, "m"), ("z", 0.10, "m"))):
        y = value_y + row * 62
        draw_label(axis.upper(), 885, y + 7)
        minus_rect = pygame.Rect(930, y, 38, 38)
        plus_rect = pygame.Rect(1105, y, 38, 38)
        position_buttons.extend(
            [(minus_rect, axis, -step), (plus_rect, axis, step)]
        )
        draw_button(minus_rect, "-")
        draw_button(plus_rect, "+")
        value = font.render(f"{selected[axis]:.2f} {unit}", True, (237, 243, 246))
        screen.blit(value, value.get_rect(center=(1037, y + 19)))

    draw_label("PRESET NAME", 880, 450)
    pygame.draw.rect(
        screen,
        (28, 35, 43) if preset_name_active else (22, 28, 34),
        preset_name_rect,
        border_radius=4,
    )
    pygame.draw.rect(
        screen,
        (126, 205, 224) if preset_name_active else (72, 86, 98),
        preset_name_rect,
        2,
        border_radius=4,
    )
    name_render = small_font.render(preset_name or "Preset name", True, (235, 241, 244))
    screen.blit(name_render, (preset_name_rect.x + 10, preset_name_rect.y + 10))

    command_buttons = {
        "save": pygame.Rect(880, 530, 110, 38),
        "load": pygame.Rect(1005, 530, 125, 38),
        "reset": pygame.Rect(880, 580, 110, 38),
        "enter": pygame.Rect(1005, 580, 125, 38),
    }
    draw_button(command_buttons["save"], "Save Preset")
    load_label = "Load Preset"
    if user_presets:
        load_label = f"Load ({len(user_presets)})"
    draw_button(command_buttons["load"], load_label)
    draw_button(command_buttons["reset"], "Reset")
    draw_button(command_buttons["enter"], "Enter", accent=True)

    if status_message:
        status = small_font.render(status_message, True, (236, 164, 112))
        screen.blit(status, (300, 630))


def select_speaker_at(position):
    for index, speaker in enumerate(state.speakers):
        point = room_to_preview(speaker["x"], speaker["y"])
        if math.hypot(position[0] - point[0], position[1] - point[1]) <= 18:
            state.selected_index = index
            return True
    return False


def update_dragged_speaker(position):
    x = min(room_preview_rect.right, max(room_preview_rect.left, position[0]))
    y = min(room_preview_rect.bottom, max(room_preview_rect.top, position[1]))
    room_x, room_y = preview_to_room(x, y)
    state.set_speaker_position(state.selected_index, x=room_x, y=room_y)
    send_speaker_position(state.selected_speaker)


def save_user_preset():
    global user_presets, status_message
    try:
        preset = state.to_preset(preset_name)
    except ValueError as exc:
        status_message = str(exc)
        return
    if preset_store.save(preset):
        user_presets = preset_store.load_all()
        status_message = f"Saved preset: {preset['name']}"
    else:
        status_message = preset_store.error


def load_next_preset():
    global loaded_preset_index, status_message, preset_name
    if not user_presets:
        status_message = "No user presets saved yet."
        return
    loaded_preset_index = (loaded_preset_index + 1) % len(user_presets)
    preset = user_presets[loaded_preset_index]
    try:
        state.apply_preset(preset)
        preset_name = preset.get("name", preset_name)
        center_listener()
        send_configuration()
        status_message = f"Loaded preset: {preset_name}"
    except ValueError as exc:
        status_message = f"Could not load preset: {exc}"


def handle_setup_mouse_down(position):
    global dragging_speaker, preset_name_active, status_message
    global distance_rolloff

    preset_name_active = preset_name_rect.collidepoint(position)
    if select_speaker_at(position):
        dragging_speaker = True
        return
    for rect, room_id in room_buttons:
        if rect.collidepoint(position):
            state.select_room(room_id)
            center_listener()
            send_configuration()
            return
    for rect, setup_name in setup_buttons:
        if rect.collidepoint(position):
            state.select_setup(setup_name)
            send_configuration()
            return
    for rect, delta in custom_count_buttons:
        if rect.collidepoint(position):
            state.set_custom_speaker_count(len(state.speakers) + delta)
            send_configuration()
            status_message = f"Custom setup: {len(state.speakers)} sources"
            return
    for rect, rolloff in distance_mode_buttons:
        if rect.collidepoint(position):
            distance_rolloff = rolloff
            client.send_message("/config/distance_rolloff", distance_rolloff)
            status_message = (
                "Physical direct-sound attenuation selected."
                if rolloff == 1.0
                else "Exaggerated non-physical demo selected."
            )
            return
    for rect, index in speaker_buttons:
        if rect.collidepoint(position):
            state.selected_index = index
            return
    for rect, axis, delta in position_buttons:
        if rect.collidepoint(position):
            speaker = state.selected_speaker
            state.set_speaker_position(
                state.selected_index,
                **{axis: speaker[axis] + delta},
            )
            send_speaker_position(state.selected_speaker)
            return
    if command_buttons.get("save", pygame.Rect(0, 0, 0, 0)).collidepoint(position):
        save_user_preset()
    elif command_buttons.get("load", pygame.Rect(0, 0, 0, 0)).collidepoint(position):
        load_next_preset()
    elif command_buttons.get("reset", pygame.Rect(0, 0, 0, 0)).collidepoint(position):
        state.reset()
        center_listener()
        send_configuration()
        status_message = "Preset reset."
    elif command_buttons.get("enter", pygame.Rect(0, 0, 0, 0)).collidepoint(position):
        enter_simulation()


def draw_floor_grid():
    for index in range(1, 20):
        y = HALF_HEIGHT + int(index * index * 1.8)
        if y < HEIGHT:
            brightness = max(18, 70 - index * 3)
            pygame.draw.line(screen, (brightness, brightness, brightness + 10), (0, y), (WIDTH, y))
    for index in range(-20, 21):
        x = WIDTH // 2 + index * 80
        pygame.draw.line(
            screen,
            (25, 28, 35),
            (x, HALF_HEIGHT),
            (WIDTH // 2 + index * 250, HEIGHT),
        )


def cast_rays():
    start_angle = player_angle - HALF_FOV
    for ray in range(NUM_RAYS):
        angle = start_angle + ray * DELTA_ANGLE
        sin_a = math.sin(angle)
        cos_a = math.cos(angle)
        depth = 0
        while depth < MAX_DEPTH:
            depth += 0.02
            target_x = player_x + cos_a * depth
            target_y = player_y + sin_a * depth
            if is_wall(int(target_x), int(target_y)):
                corrected = depth * math.cos(player_angle - angle)
                wall_height = min(int(650 / (corrected + 0.0001)), HEIGHT)
                base = max(35, 220 - int(corrected * 28))
                stripe = 18 if ray % 12 < 6 else 0
                color = (
                    max(20, base - stripe),
                    max(25, base - stripe + 8),
                    max(35, base + 18),
                )
                x = int(ray * SCALE)
                y = HALF_HEIGHT - wall_height // 2
                pygame.draw.rect(screen, color, (x, y, int(SCALE) + 2, wall_height))
                pygame.draw.line(screen, (8, 8, 10), (x, y), (x, y + wall_height), 2)
                break


def draw_sources():
    animation_time = pygame.time.get_ticks() * 0.004
    for speaker in state.speakers:
        sx, sy = room_to_world(speaker["x"], speaker["y"])
        dx = sx - player_x
        dy = sy - player_y
        distance = math.hypot(dx, dy)
        relative = normalize_angle(math.atan2(dy, dx) - player_angle)
        if abs(relative) >= HALF_FOV or distance <= 0.2:
            continue
        screen_x = int((relative + HALF_FOV) / FOV * WIDTH)
        size = max(14, min(int(190 / distance), 120))
        pulse = int(8 * math.sin(animation_time * 2 + sx + sy))
        final_size = max(10, size + pulse)
        screen_y = HALF_HEIGHT + int(90 / distance) - final_size // 2
        rect = pygame.Rect(
            screen_x - final_size // 2,
            screen_y - final_size,
            final_size,
            final_size * 2,
        )
        pygame.draw.rect(screen, (35, 43, 55), rect, border_radius=4)
        pygame.draw.rect(screen, (92, 178, 205), rect, 3, border_radius=4)
        pygame.draw.circle(screen, (170, 230, 242), (screen_x, rect.centery), max(4, final_size // 4))
        label = font.render(f"S{speaker['id']}", True, (236, 245, 248))
        screen.blit(label, label.get_rect(center=(screen_x, rect.top - 15)))


def draw_minimap():
    map_scale = 18
    offset_x = 20
    offset_y = 20
    pygame.draw.rect(screen, (5, 8, 12), (12, 12, 196, 196))
    pygame.draw.rect(screen, (70, 90, 120), (12, 12, 196, 196), 2)
    for y, row in enumerate(WORLD_MAP):
        for x, char in enumerate(row):
            color = (105, 123, 142) if char == "#" else (24, 30, 38)
            pygame.draw.rect(screen, color, (offset_x + x * map_scale, offset_y + y * map_scale, map_scale, map_scale))
    for index, speaker in enumerate(state.speakers):
        sx, sy = room_to_world(speaker["x"], speaker["y"])
        color = (135, 230, 242) if index == state.selected_index else (78, 154, 190)
        pygame.draw.circle(screen, color, (offset_x + int(sx * map_scale), offset_y + int(sy * map_scale)), 5)
    px = offset_x + int(player_x * map_scale)
    py = offset_y + int(player_y * map_scale)
    pygame.draw.circle(screen, (250, 250, 250), (px, py), 5)
    pygame.draw.line(
        screen,
        (250, 250, 250),
        (px, py),
        (px + int(math.cos(player_angle) * 15), py + int(math.sin(player_angle) * 15)),
        2,
    )


def draw_source_hud():
    speaker = state.selected_speaker
    source_data = source_states.get(speaker["id"])
    rect = pygame.Rect(WIDTH - 280, 20, 250, 205)
    pygame.draw.rect(screen, (10, 15, 20), rect, border_radius=6)
    pygame.draw.rect(screen, (79, 104, 120), rect, 2, border_radius=6)
    draw_label(f"S{speaker['id']}  {speaker['frequency_hz']} Hz", rect.x + 18, rect.y + 15, selected=True)
    if not source_data:
        pending = small_font.render("Waiting for engine feedback on port 9001", True, (160, 177, 188))
        screen.blit(pending, (rect.x + 18, rect.y + 58))
        return
    values = (
        ("Distance", f"{source_data['distance_m']:.2f} m"),
        ("Az / El", f"{source_data['azimuth_deg']:.1f} / {source_data['elevation_deg']:.1f} deg"),
        ("Distance level", f"{source_data['gain_db']:.1f} dB"),
        ("Final level", f"{source_data['output_gain_db']:.1f} dB"),
        ("Travel delay", f"{source_data['delay_ms']:.2f} ms"),
    )
    for index, (label, value) in enumerate(values):
        y = rect.y + 52 + index * 29
        screen.blit(small_font.render(label, True, (144, 164, 176)), (rect.x + 18, y))
        rendered = small_font.render(value, True, (235, 242, 246))
        screen.blit(rendered, (rect.right - 18 - rendered.get_width(), y))


def draw_simulation():
    screen.fill((8, 10, 16))
    pygame.draw.rect(screen, (20, 24, 36), (0, 0, WIDTH, HALF_HEIGHT))
    pygame.draw.rect(screen, (12, 14, 18), (0, HALF_HEIGHT, WIDTH, HALF_HEIGHT))
    draw_floor_grid()
    pygame.draw.rect(screen, (35, 42, 60), (0, HALF_HEIGHT - 4, WIDTH, 8))
    cast_rays()
    draw_sources()
    draw_minimap()
    draw_source_hud()
    footer = small_font.render("WASD move   Mouse look   SPACE setup   ESC exit", True, (205, 216, 223))
    screen.blit(footer, footer.get_rect(center=(WIDTH // 2, HEIGHT - 22)))


def update_simulation(keys):
    global player_x, player_y, player_angle
    mouse_dx, _ = pygame.mouse.get_rel()
    player_angle += mouse_dx * ROT_SPEED
    cos_a = math.cos(player_angle)
    sin_a = math.sin(player_angle)
    next_x = player_x
    next_y = player_y
    if keys[pygame.K_w]:
        next_x += cos_a * MOVE_SPEED
        next_y += sin_a * MOVE_SPEED
    if keys[pygame.K_s]:
        next_x -= cos_a * MOVE_SPEED
        next_y -= sin_a * MOVE_SPEED
    if keys[pygame.K_a]:
        next_x += sin_a * MOVE_SPEED
        next_y -= cos_a * MOVE_SPEED
    if keys[pygame.K_d]:
        next_x -= sin_a * MOVE_SPEED
        next_y += cos_a * MOVE_SPEED
    if not is_wall(next_x, next_y):
        player_x = next_x
        player_y = next_y
    audio_x, audio_y = world_to_room(player_x, player_y)
    client.send_message("/listener/x", float(audio_x))
    client.send_message("/listener/y", float(audio_y))
    client.send_message("/listener/yaw", player_angle_to_audio_yaw(player_angle))


running = True
while running:
    clock.tick(60)
    for event in pygame.event.get():
        if event.type == pygame.QUIT:
            running = False
        elif event.type == pygame.KEYDOWN:
            if event.key == pygame.K_ESCAPE:
                running = False
            elif mode == "setup" and preset_name_active:
                if event.key == pygame.K_BACKSPACE:
                    preset_name = preset_name[:-1]
                elif event.key == pygame.K_RETURN:
                    preset_name_active = False
                elif event.unicode.isprintable() and len(preset_name) < 32:
                    preset_name += event.unicode
            elif event.key == pygame.K_SPACE:
                if mode == "simulation":
                    enter_setup()
                else:
                    enter_simulation()
        elif mode == "setup" and event.type == pygame.MOUSEBUTTONDOWN and event.button == 1:
            handle_setup_mouse_down(event.pos)
        elif mode == "setup" and event.type == pygame.MOUSEBUTTONUP and event.button == 1:
            dragging_speaker = False
        elif mode == "setup" and event.type == pygame.MOUSEMOTION and dragging_speaker:
            update_dragged_speaker(event.pos)

    if mode == "setup":
        draw_setup_screen()
    else:
        update_simulation(pygame.key.get_pressed())
        draw_simulation()
    pygame.display.flip()
    screenshot_path = os.environ.get("SPATIAL_GUI_SCREENSHOT")
    if screenshot_path:
        pygame.image.save(screen, screenshot_path)
        running = False

if feedback_server is not None:
    feedback_server.shutdown()
pygame.quit()

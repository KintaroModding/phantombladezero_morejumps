"""Offline test of Scripts/main.lua with lupa (Lua 5.4) and small mocks of UE4SS and the game.

The mocks stand in for the UE4SS functions that the script uses (the game-thread loops LoopInGameThreadAfterFrames
and LoopInGameThreadWithDelay, EngineTickAvailable, the old LoopAsync, ExecuteInGameThread, StaticFindObject, FName,
UEHelpers) and for the game: a player controller with its key states, analog stick and camera, a pawn with its
movement mode, LaunchCharacter and location, the pause state, the Enhanced Input subsystem that names the keys of the
game's jump action, and the Niagara library with the blue effect. As in UE4SS, a struct or array that a game function
returns is a Lua table, and a key goes into the game as a struct with a KeyName. The clock (os.clock) is the test's.

FRAME() runs one frame of the mod; SETMODE(n) sets the player's movement mode (1 walking, 3 falling); TAP(key)
presses a key for one frame; JUMP(keys, yaw, pitch, key) holds direction keys, taps the jump key in the air and gives
the launch as "X, Y, Z", or "none".

The checks: the loops; a press on the ground and in the air, the hold, the cooldown, the pause; the direction from
the keys, the camera and the gamepad stick; the effect; the movement modes and FallingOnly; the jump keys from the
game, from config.lua and the standard ones; live settings; the kept player controller; errors and the stop; the
UE4SS variants. Then the settings files a player may have instead of the shipped config.lua: main.lua must start, and
every setting the file does not give keeps its default; the shipped config.lua must hold exactly the defaults of
main.lua.

Usage:
    python tests/test_main.py        (needs lupa: python -m pip install lupa)

Exit code: 0 = all checks passed, 1 = a check failed.
"""

import json
import sys
import tempfile
from pathlib import Path

from lupa import lua54

ROOT = Path(__file__).resolve().parent.parent
MAIN = ROOT / "src" / "phantombladezero_morejumps" / "Scripts" / "main.lua"
CONFIG = MAIN.parent / "config.lua"

MOCKS = r"""
LOG = {}
print = function(...) LOG[#LOG + 1] = table.concat({...}, "") end

LOOPS, DELAYS, KINDS = {}, {}, {}
ASYNC_LOOPS = 0
GAME_THREAD_CALLS = 0
EngineTickAvailable = true
local function Loop(kind, delay, callback)
    LOOPS[#LOOPS + 1] = callback DELAYS[#DELAYS + 1] = delay KINDS[#KINDS + 1] = kind
    return #LOOPS
end
function LoopInGameThreadWithDelay(ms, callback) return Loop("delay", ms, callback) end
function LoopInGameThreadAfterFrames(frames, callback) return Loop("frames", frames, callback) end
function LoopAsync(ms, callback) ASYNC_LOOPS = ASYNC_LOOPS + 1 Loop("async", ms, callback) end
function ExecuteInGameThread(callback) GAME_THREAD_CALLS = GAME_THREAD_CALLS + 1 callback() end

-- The test's clock; one frame is 1/60 s.
NOW = 100
os.clock = function() return NOW end
function FRAME(count) for _ = 1, count or 1 do NOW = NOW + 1 / 60 LOOPS[1]() end end
function CONFIG() for i = 1, #LOOPS do if DELAYS[i] == 5000 then LOOPS[i]() end end end

local function Invalid() return { IsValid = function() return false end } end
local function Object(fields)
    fields = fields or {}
    fields.IsValid = function(self) return self.valid ~= false end
    return fields
end
local function Name(text) return { name = text, ToString = function() return text end } end
FNAMES = 0
function FName(text) FNAMES = FNAMES + 1 return Name(text) end

-- The player: key states, the stick, the camera, the movement mode, the launches.
DOWN = {}
AXES = {}
KEY_READS = 0
ANALOG_READS = 0
CAMERA = { Pitch = -15, Yaw = 0, Roll = 0 }
LAUNCHES = {}
MOVEMENT = Object({ MovementMode = 1 })
function SETMODE(mode) MOVEMENT.MovementMode = mode end
PAWN = Object({
    CharacterMovement = MOVEMENT,
    LaunchCharacter = function(self, velocity, xyOverride, zOverride)
        if LAUNCH_ERROR then error(LAUNCH_ERROR, 0) end
        LAUNCHES[#LAUNCHES + 1] = { X = velocity.X, Y = velocity.Y, Z = velocity.Z, xy = xyOverride, z = zOverride }
    end,
    K2_GetActorLocation = function() return { X = 10, Y = 20, Z = 30 } end,
    GetAddress = function() return PAWN_ADDRESS end,
    CapsuleComponent = { GetScaledCapsuleHalfHeight = function()
        if CAPSULE_ERROR then error(CAPSULE_ERROR, 0) end
        return 88
    end },
})
-- The pawn's address; a new value stands for a new pawn (after a death or a map load).
PAWN_ADDRESS = 0x1000
local function KeyName(key)
    if type(key) ~= "table" or type(key.KeyName) ~= "table" or type(key.KeyName.name) ~= "string" then
        error("the key is no key struct with a KeyName", 0)
    end
    return key.KeyName.name
end
CONTROLLER = Object({
    Pawn = PAWN,
    PlayerCameraManager = Object({ GetCameraRotation = function() return CAMERA end }),
    IsInputKeyDown = function(self, key)
        KEY_READS = KEY_READS + 1
        if KEY_ERROR then error(KEY_ERROR, 0) end
        return DOWN[KeyName(key)] == true
    end,
    GetInputAnalogKeyState = function(self, key)
        ANALOG_READS = ANALOG_READS + 1
        if STICK_ERROR then error(STICK_ERROR, 0) end
        return AXES[KeyName(key)] or 0
    end,
})
PAUSED = false
STATICS = { IsGamePaused = function(self, context)
    if PAUSE_ERROR then error("IsGamePaused failed", 0) end
    return PAUSED
end }
HAS_CONTROLLER = true
SEARCHES = 0
package.preload["UEHelpers"] = function()
    return {
        GetPlayerController = function() SEARCHES = SEARCHES + 1 return HAS_CONTROLLER and CONTROLLER or Invalid() end,
        GetGameplayStatics = function() return STATICS end,
    }
end

-- Enhanced Input: the keys of the game's jump action in the player's key settings.
GAME_KEYS = { "SpaceBar", "Gamepad_FaceButton_Bottom" }
QUERIES = 0
QUERY_MODE = "tables"
JUMP_ACTION = Object()
local function Query(action)
    QUERIES = QUERIES + 1
    if action ~= JUMP_ACTION then error("QueryKeysMappedToAction: wrong action", 0) end
    if QUERY_MODE == "throws" then error("QueryKeysMappedToAction failed\nstack traceback:\n    [C]: in ?", 0) end
    local keys = {}
    for i, name in ipairs(GAME_KEYS) do
        local key = { KeyName = Name(name) }
        keys[i] = QUERY_MODE == "params" and { get = function() return key end } or key
    end
    return keys
end
-- The function belongs to an interface: UE4SS may find it on the subsystem (DIRECT), or only as the interface's
-- function object, called with CallFunction.
INTERFACE_QUERY = Object()
INTERFACE_CALLS = 0
SUBSYSTEM = Object({
    QueryKeysMappedToAction = function(self, action) return Query(action) end,
    CallFunction = function(self, query, action)
        if query ~= INTERFACE_QUERY then error("CallFunction: wrong function", 0) end
        INTERFACE_CALLS = INTERFACE_CALLS + 1
        return Query(action)
    end,
})
-- What UE4SS gives for a member it does not find: an invalid object, which cannot be called.
function NOT_DIRECT() SUBSYSTEM.QueryKeysMappedToAction = Invalid() end
HAS_SUBSYSTEM = true
SUBSYSTEM_CLASS = Object()
SUBSYSTEM_LIBRARY = Object({ GetLocalPlayerSubSystemFromPlayerController = function(self, controller, class)
    if controller ~= CONTROLLER or class ~= SUBSYSTEM_CLASS then error("wrong subsystem parameters", 0) end
    return HAS_SUBSYSTEM and SUBSYSTEM or Invalid()
end })

-- Niagara: the three effects of the choice Effect, each a system object with its name.
EFFECTS = {}
DUST_PATH = "/PBZVFXPack/VFX/BattleFX/Common/Footsteps/NS_Hun_FootSteps_Dust_101.NS_Hun_FootSteps_Dust_101"
JUMPFX_PATH = "/PBZVFXPack/VFX/BattleFX/Common/Jump/NS_Jump_Stone_301.NS_Jump_Stone_301"
SHADOW_PATH = "/PBZVFXPack/VFX/BattleFX/Hun/NS_Hun_SpecialDash_Show_001.NS_Hun_SpecialDash_Show_001"
SYSTEMS = { [DUST_PATH] = Object({ fx = "dust" }), [JUMPFX_PATH] = Object({ fx = "jump" }),
    [SHADOW_PATH] = Object({ fx = "shadow" }) }
NIAGARA = Object({ SpawnSystemAtLocation = function(self, context, system, location, rotation, scale, destroy,
        activate, pool, cull)
    if EFFECT_ERROR then error(EFFECT_ERROR, 0) end
    EFFECTS[#EFFECTS + 1] = string.format("%s %s at %g/%g/%g rot %g/%g/%g scale %g/%g/%g %s %s %s %s",
        context == PAWN and "pawn" or "?", system.fx or "?", location.X, location.Y, location.Z,
        rotation.Pitch, rotation.Yaw, rotation.Roll, scale.X, scale.Y, scale.Z, tostring(destroy), tostring(activate),
        tostring(pool), tostring(cull))
end })

JUMP_PATH = "/PBZInput/InputActions/IA_Jump.IA_Jump"
INTERFACE_PATH = "/Script/EnhancedInput.EnhancedInputSubsystemInterface:QueryKeysMappedToAction"
OBJECTS = {
    [JUMP_PATH] = JUMP_ACTION,
    [INTERFACE_PATH] = INTERFACE_QUERY,
    ["/Script/Engine.Default__SubsystemBlueprintLibrary"] = SUBSYSTEM_LIBRARY,
    ["/Script/EnhancedInput.EnhancedInputLocalPlayerSubsystem"] = SUBSYSTEM_CLASS,
    ["/Script/Niagara.Default__NiagaraFunctionLibrary"] = NIAGARA,
    [DUST_PATH] = SYSTEMS[DUST_PATH], [JUMPFX_PATH] = SYSTEMS[JUMPFX_PATH], [SHADOW_PATH] = SYSTEMS[SHADOW_PATH],
}
FINDS = {}
function StaticFindObject(path) FINDS[path] = (FINDS[path] or 0) + 1 return OBJECTS[path] or Invalid() end
-- UE4SS's LoadAsset: puts the effect into OBJECTS when LOADABLE says so; LOADS counts the calls per path.
LOADS = {}
LOADABLE = {}
function LoadAsset(path)
    LOADS[path] = (LOADS[path] or 0) + 1
    if LOAD_ERROR then error(LOAD_ERROR, 0) end
    if LOADABLE[path] then OBJECTS[path] = SYSTEMS[path] end
    return OBJECTS[path]
end

-- One press: `gap` seconds later the key goes down for one frame, then up for one frame.
function TAP(key, gap)
    NOW = NOW + (gap or 1)
    DOWN[key] = true FRAME() DOWN[key] = nil FRAME()
end
function LAST()
    local launch = LAUNCHES[#LAUNCHES]
    -- Rounded to one decimal; a tiny negative number must not print as -0.0.
    local function Round(value) return math.floor(value * 10 + 0.5) / 10 + 0.0 end
    return string.format("%.1f, %.1f, %.1f", Round(launch.X), Round(launch.Y), Round(launch.Z))
end
-- One frame on the ground, then back to the movement mode before: the count of air jumps starts again.
function LAND()
    local mode = MOVEMENT.MovementMode
    SETMODE(1) FRAME() SETMODE(mode) FRAME()
end
-- In a fresh jump (it lands first while in the air): holds the direction keys, taps the jump key; the launch as
-- "X, Y, Z", or "none".
function JUMP(keys, yaw, pitch, key)
    if MOVEMENT.MovementMode ~= 1 then LAND() end
    local before = #LAUNCHES
    for name in (keys or ""):gmatch("%S+") do DOWN[name] = true end
    CAMERA.Yaw, CAMERA.Pitch = yaw or 0, pitch or -15
    TAP(key or "SpaceBar")
    for name in (keys or ""):gmatch("%S+") do DOWN[name] = nil end
    return #LAUNCHES > before and LAST() or "none"
end

function DESCRIBE(t)
    local names = {}
    for name in pairs(t) do names[#names + 1] = tostring(name) end
    table.sort(names)
    local parts = {}
    for i, name in ipairs(names) do parts[i] = name .. "=" .. tostring(t[name]) end
    return table.concat(parts, ", ")
end
"""

UP = "0.0, 0.0, 800.0"
FORWARD = "600.0, 0.0, 800.0"
GAME_KEYS_LINE = "Jump keys: Gamepad_FaceButton_Bottom, SpaceBar (the keys of the game's own jump)."
PAD = "Gamepad_FaceButton_Bottom"

PLAYER_CONFIGS = [
    ("no config.lua", None, "No config.lua"),
    ("an empty or older config.lua", "return {}\n", None),
    ("a broken config.lua", "return {\n    Enable =\n", "config.lua not read"),
    ("a config.lua without a table", "-- nothing here\n", "does not return a table"),
    ("a config.lua with wrong types", "wrong types", "must be a"),
    ("a config.lua with an unknown setting", "return { NoSuchSetting = 1 }\n", "unknown setting NoSuchSetting"),
]


def lua_path(path: Path) -> str:
    return "[[" + path.as_posix() + "]]"


class Run:
    """main.lua in a fresh Lua state, with config.lua read from config_folder; before: Lua run before main.lua."""

    def __init__(self, config_folder: Path, before: str = ""):
        self.folder = config_folder
        self.lua = lua54.LuaRuntime(unpack_returned_tuples=True)
        self.lua.execute(MOCKS)
        self.lua.execute(f'package.path = {lua_path(config_folder)} .. "/?.lua"; package.cpath = ""')
        if before:
            self.lua.execute(before)
        self.g = self.lua.globals()
        self.do(MAIN.read_text(encoding="utf-8"))

    def do(self, code: str):
        """Runs Lua code; a Lua error that stops it becomes an "Error" line in the log, so the checks fail."""
        try:
            return self.lua.execute(code)
        except lua54.LuaError as error:
            self.g.LOG[len(self.g.LOG) + 1] = "Error: main.lua stopped: " + str(error).splitlines()[0]

    def eval(self, expression: str):
        return self.lua.eval(expression)

    def log(self):
        return [self.g.LOG[i].rstrip() for i in range(1, len(self.g.LOG) + 1)]

    def count(self, text: str) -> int:
        return sum(text in line for line in self.log())

    def write_config(self, text: str):
        (self.folder / "config.lua").write_text(text, encoding="utf-8")


def settings_lines(log):
    return [line.split("] Settings: ", 1)[1] for line in log if "] Settings: " in line]


def main() -> None:
    version = json.loads((ROOT / "mod.json").read_text(encoding="utf-8"))["version"]
    failures = []

    def check(condition, text):
        print(("ok    " if condition else "FAIL  ") + text)
        if not condition:
            failures.append(text)

    with tempfile.TemporaryDirectory() as temp:
        temp = Path(temp)
        shipped_text = CONFIG.read_text(encoding="utf-8")
        made = []

        def folder(text=shipped_text):
            f = temp / f"run{len(made)}"
            made.append(f)
            f.mkdir()
            if text is not None:
                (f / "config.lua").write_text(text, encoding="utf-8")
            return f

        def config(**values):
            """The shipped config.lua with other values, for example config(Effect="false")."""
            text = shipped_text
            for name, value in values.items():
                lines = [line for line in text.splitlines() if line.strip().startswith(name + " = ")]
                assert len(lines) == 1, name
                old = lines[0].split(",", 1)[0]
                text = text.replace(old + ",", f"    {name} = {value},")
            return text

        def air(before="", text=shipped_text):
            """A run whose player is in the air, with the first frames done."""
            run = Run(folder(text), before)
            run.do("SETMODE(3) FRAME(2)")
            return run

        # --- The mod as players get it.
        r = Run(folder())
        e = r.eval
        log = r.log()
        for line in log:
            print("      log: " + line)
        check(list(r.g.KINDS.values()) == ["frames", "delay"] and list(r.g.DELAYS.values()) == [1, 5000]
              and r.g.ASYNC_LOOPS == 0,
              "game-thread loops: the frame step once per frame, the config read every 5 s")
        check(any(f"{version} loaded." in line for line in log), f"load line with the version {version} of mod.json")
        shipped = e(f"DESCRIBE(dofile({lua_path(CONFIG)}))")
        check(settings_lines(log) == [shipped] and not any("config.lua" in line for line in log),
              "one settings line with the shipped values, no warning")

        # --- A press on the ground and in the air.
        r.do("DOWN.SpaceBar = true FRAME(3)")
        check(e("#LAUNCHES") == 0 and e("KEY_READS") == 0 and e("SEARCHES") == 1,
              "on the ground: no launch and no key read; one search for the player controller")
        check(r.count(GAME_KEYS_LINE) == 1 and e("QUERIES") == 1,
              "the jump keys come from the game's key settings: one question, one log line")
        r.do("SETMODE(3) FRAME(3)")
        check(e("#LAUNCHES") == 0 and e("KEY_READS") > 0,
              "the press that began on the ground, still held in the air: no air jump")
        r.do("DOWN.SpaceBar = nil FRAME() DOWN.SpaceBar = true FRAME()")
        check(e("#LAUNCHES") == 1 and e("LAST()") == UP and e("LAUNCHES[1].xy") is False
              and e("LAUNCHES[1].z") is True,
              "released and pressed again in the air: one launch, 800 up; X and Y are added, Z is replaced")
        check(r.count("air jump 1 (1 of 1 before landing): key SpaceBar, movement mode 3, launch 0 / 0 / 800 "
                      "(direction: none), effect Dust shown. LogDetail = true logs every air jump.") == 1,
              "the first air jump has a log line")
        r.do("FRAME(3)")
        check(e("#LAUNCHES") == 1, "the key held: no second jump")
        r.do("DOWN.SpaceBar = nil FRAME() TAP('SpaceBar') TAP('SpaceBar')")
        check(e("#LAUNCHES") == 1, "Jumps = 2 (the default, a double jump): no second air jump before landing")
        r.do("SETMODE(6) FRAME() SETMODE(3) FRAME() TAP('SpaceBar')")
        check(e("#LAUNCHES") == 1, "a change between air modes (Custom, Falling) does not start the count again")
        r.do("SETMODE(1) FRAME() SETMODE(3) FRAME() TAP('SpaceBar')")
        check(e("#LAUNCHES") == 2, "on the ground for one frame: the next jump has its air jump again")
        r.do("PAWN_ADDRESS = 0x2000 FRAME() TAP('SpaceBar')")
        check(e("#LAUNCHES") == 3, "a new pawn (a death, a map load) in the air: the count starts again")
        r.write_config(config(Jumps="3"))
        r.do("CONFIG() LAND() TAP('SpaceBar')")
        check(e("#LAUNCHES") == 4 and any("Jumps=3" in line for line in settings_lines(r.log())),
              "Jumps = 3 (live, a triple jump): the first air jump")
        r.do("DOWN.SpaceBar = true FRAME() DOWN.SpaceBar = nil FRAME()")
        check(e("#LAUNCHES") == 4, "a press less than 0.1 s after the last air jump is ignored")
        r.do("NOW = NOW + 0.1 DOWN.SpaceBar = true FRAME() DOWN.SpaceBar = nil FRAME()")
        check(e("#LAUNCHES") == 5, "0.1 s after the last air jump: the second air jump of a triple jump")
        r.do("TAP('SpaceBar')")
        check(e("#LAUNCHES") == 5, "Jumps = 3: no third air jump before landing")
        check(e("#EFFECTS") == 5 and e("EFFECTS[2]") == "pawn dust at 10/20/-58 rot 0/0/0 scale 1/1/1 true true 0 true",
              "each air jump spawns the default effect Dust at the player's feet (location minus the capsule's half "
              "height, 88), with the source's spawn parameters")
        r.write_config(shipped_text)
        r.do("CONFIG() LAND()")
        r.do("SETMODE(1) FRAME() PAUSED = true")
        reads = e("KEY_READS")
        check(e("JUMP()") == "none" and e("KEY_READS") == reads, "a tap on the ground: nothing, no key read")
        r.do("SETMODE(3) FRAME()")
        check(e("JUMP()") == "none", "the game is paused: no air jump")
        r.do("PAUSED = false PAUSE_ERROR = true")
        check(e("JUMP()") == UP, "a pause check that fails does not stop the jump (as in the source)")
        r.do("PAUSE_ERROR = nil")

        # --- The direction: keys, camera, stick.
        for keys, yaw, pitch, expected, text in [
            ("W", 0, -15, FORWARD, "W: forward along the camera"),
            ("W", 90, -15, "0.0, 600.0, 800.0", "W with the camera turned by 90 degrees"),
            ("W", 180, -15, "-600.0, 0.0, 800.0", "W with the camera turned by 180 degrees"),
            ("S", 0, -15, "-600.0, 0.0, 800.0", "S: back"),
            ("A", 0, -15, "0.0, -600.0, 800.0", "A: left"),
            ("D", 0, -15, "0.0, 600.0, 800.0", "D: right"),
            ("W D", 0, -15, "424.3, 424.3, 800.0", "W and D: the diagonal, 600 in total"),
            ("W A", 0, -15, "424.3, -424.3, 800.0", "W and A"),
            ("S A", 0, -15, "-424.3, -424.3, 800.0", "S and A"),
            ("S D", 0, -15, "-424.3, 424.3, 800.0", "S and D"),
            ("W S", 0, -15, UP, "W and S cancel: only up"),
            ("A D", 0, -15, UP, "A and D cancel: only up"),
            ("W S D", 0, -15, "0.0, 600.0, 800.0", "W, S and D: right"),
            ("D", 0, -60, "0.0, 600.0, 800.0", "sideways at a steep camera: the full 600"),
            ("W D", 0, 45, "424.3, 424.3, 800.0", "a diagonal with the camera looking up: 600 in total"),
            ("W", 0, -90, UP, "the camera straight down: only up"),
        ]:
            got = e(f"JUMP('{keys}', {yaw}, {pitch})")
            check(got == expected, f"{text} ({got})")
        reads = e("ANALOG_READS")
        check(e(f"JUMP('', 0, -15, '{PAD}')") == UP and e("ANALOG_READS") == reads + 2,
              "the gamepad's jump button jumps; without a direction key the stick is asked (centre: only up)")
        r.do("AXES.Gamepad_LeftY = 1")
        check(e(f"JUMP('', 0, -15, '{PAD}')") == FORWARD, "the stick forward: forward along the camera")
        r.do("AXES.Gamepad_LeftY = 0 AXES.Gamepad_LeftX = -1")
        check(e(f"JUMP('', 90, -15, '{PAD}')") == "600.0, 0.0, 800.0", "the stick left with the camera turned by 90 degrees")
        r.do("AXES.Gamepad_LeftX = 0.3 AXES.Gamepad_LeftY = 0.4")
        check(e(f"JUMP('', 0, -15, '{PAD}')") == "480.0, 360.0, 800.0", "a half pushed stick: its direction, 600 in total")
        r.do("AXES.Gamepad_LeftX = 0.2 AXES.Gamepad_LeftY = 0.1")
        check(e(f"JUMP('', 0, -15, '{PAD}')") == UP, "a stick inside the dead zone: only up")
        r.do("AXES.Gamepad_LeftX = 1 AXES.Gamepad_LeftY = 0")
        reads = e("ANALOG_READS")
        check(e("JUMP('W')") == FORWARD and e("JUMP('W S')") == UP and e("ANALOG_READS") == reads,
              "a held direction key wins over the stick, and the stick is not asked")
        r.do("STICK_ERROR = 'GetInputAnalogKeyState failed'")
        check(e("JUMP()") == UP and e("JUMP()") == UP and e("JUMP('D')") == "0.0, 600.0, 800.0"
              and r.count("left stick could not be read (GetInputAnalogKeyState failed)") == 1
              and e("ANALOG_READS") == reads + 1,
              "a stick that cannot be read: one line, the jump and the direction keys still work, no second try")
        r.do("STICK_ERROR = nil AXES = {}")
        names, reads = e("FNAMES"), e("KEY_READS")
        r.do("FRAME(100) JUMP('W') JUMP('A D')")
        check(names == 8 and e("FNAMES") == names and e("KEY_READS") >= reads + 200,
              "a key struct is made once per key (2 jump keys, 4 direction keys, 2 stick axes), not per frame")

        # --- The movement modes.
        modes = {}
        for mode in (0, 1, 2, 3, 4, 5, 6):
            r.do(f"SETMODE({mode}) FRAME()")
            modes[mode] = e("JUMP()") != "none"
        check(modes == {0: True, 1: False, 2: True, 3: True, 4: True, 5: False, 6: True},
              f"an air jump in every movement mode but Walking (1) and Flying (5), the source's rule ({modes})")
        r.write_config(config(FallingOnly="true"))
        r.do("CONFIG()")
        for mode in (0, 1, 2, 3, 4, 5, 6):
            r.do(f"SETMODE({mode}) FRAME()")
            modes[mode] = e("JUMP()") != "none"
        check(modes == {0: False, 1: False, 2: False, 3: True, 4: False, 5: False, 6: False},
              f"FallingOnly = true (live): an air jump only while falling ({modes})")
        r.do("SETMODE(3) FRAME()")

        # --- Live settings.
        r.write_config(config(UpSpeed="1200", DirectionSpeed="0"))
        r.do("CONFIG() FRAME()")
        reads = e("KEY_READS")
        check(e("JUMP('W')") == "0.0, 0.0, 1200.0" and any("UpSpeed=1200" in line for line in settings_lines(r.log()))
              and e("KEY_READS") == reads + 6,
              "UpSpeed 1200 and DirectionSpeed 0 (live): only up, 1200, and no direction key is read (6 reads: the "
              "two jump keys in JUMP's frame in the air after landing and in the tap's two frames)")
        r.write_config(config(UpSpeed="99999", DirectionSpeed="-5"))
        r.do("CONFIG()")
        check(r.count("UpSpeed = 99999 is outside 0 to 5000; 5000 is used") == 1
              and r.count("DirectionSpeed = -5 is outside 0 to 5000; 0 is used") == 1
              and e("JUMP('W')") == "0.0, 0.0, 5000.0", "speeds out of range are clamped")
        for value, expected, text in [
            ('"Jump"', "pawn jump at 10/20/-58", "Effect = \"Jump\" (live): the take-off dust at the feet"),
            ('"shadow"', "pawn shadow at 10/20/-58", "Effect = \"shadow\" (live, any case): the dash at the feet"),
            ('"DUST"', "pawn dust at 10/20/-58", "Effect = \"DUST\" (live, any case): the dust at the feet"),
        ]:
            r.write_config(config(Effect=value))
            r.do("CONFIG()")
            check(e("JUMP()") == UP and e("EFFECTS[#EFFECTS]").startswith(expected), text)
        effects = e("#EFFECTS")
        r.write_config(config(Effect='"Off"'))
        r.do("CONFIG()")
        check(e("JUMP()") == UP and e("#EFFECTS") == effects and r.count("could not be shown") == 0
              and r.count("could not be loaded") == 0,
              'Effect = "Off" (live): the jump without an effect, and no effect is looked for')
        r.write_config(config(Effect='"Blue"'))
        r.do("CONFIG()")
        check(r.count('config.lua: Effect = "Blue" is not one of Dust, Jump, Shadow, Off; "Dust" is used.') == 1
              and e("JUMP()") == UP and e("EFFECTS[#EFFECTS]").startswith("pawn dust"),
              "an unknown effect name: one line, the default Dust")
        r.write_config(config(ForwardKey='"Up"', LeftKey='"A B"', BackKey='""'))
        r.do("CONFIG()")
        check(e("JUMP('Up')") == FORWARD and e("JUMP('W')") == UP and e("JUMP('A')") == UP and e("JUMP('S')") == UP
              and e("JUMP('D')") == "0.0, 600.0, 800.0"
              and r.count('config.lua: LeftKey = "A B" is not a key name; that direction is not read.') == 1,
              "other direction keys (live); a wrong name is named in the log, an empty one reads nothing")
        r.write_config(config(Enable="false"))
        r.do("CONFIG()")
        reads, searches, queries = e("KEY_READS"), e("SEARCHES"), e("QUERIES")
        check(e("JUMP()") == "none" and e("JUMP('W')") == "none" and e("KEY_READS") == reads
              and e("SEARCHES") == searches and e("QUERIES") == queries,
              "Enable = false (live): no air jump, and the mod asks the game nothing")
        r.do("DOWN.SpaceBar = true FRAME()")
        r.write_config(shipped_text)
        r.do("CONFIG() FRAME(3)")
        launches = e("#LAUNCHES")
        r.do("DOWN.SpaceBar = nil FRAME()")
        check(e("#LAUNCHES") == launches and e("JUMP('W')") == FORWARD,
              "Enable = true again (live): a key held since before does not count, the next press jumps")
        r.write_config("return {\n    Enable =\n")
        r.do("CONFIG()")
        check(any("config.lua not read (line" in line and "the last settings stay" in line for line in r.log())
              and e("JUMP('W')") == FORWARD, "a broken (half-saved) file keeps the last settings")
        r.write_config(shipped_text)
        r.do("CONFIG()")
        check(not any("Error" in line for line in r.log()), "no error line in this run")

        # --- The jump keys: the game's key settings, config.lua, the standard keys.
        k = air()
        ke = k.eval
        k.do("GAME_KEYS = { 'F', 'Gamepad_FaceButton_Right', 'F', 'None' } NOW = NOW + 10 FRAME()")
        check(k.count("Jump keys: F, Gamepad_FaceButton_Right (the keys of the game's own jump).") == 1
              and ke("JUMP('W', 0, -15, 'F')") == FORWARD and ke("JUMP('', 0, -15, 'Gamepad_FaceButton_Right')") == UP
              and ke("JUMP()") == "none",
              "other keys in the game's key settings: read within 10 s; the old key no longer jumps")
        lines = k.count("Jump keys:")
        k.do("GAME_KEYS = {} NOW = NOW + 10 FRAME()")
        check(ke("JUMP('', 0, -15, 'F')") == UP and k.count("Jump keys:") == lines,
              "the game names no key for a while (a menu): the last keys stay, no new line")
        queries = ke("QUERIES")
        k.write_config(config(JumpKeys='"LeftShift, Q; LeftShift  Bad-Key"'))
        k.do("CONFIG() FRAME()")
        check(k.count("Jump keys: LeftShift, Q (JumpKeys in config.lua).") == 1
              and k.count('config.lua: JumpKeys: "Bad-Key" is not a key name; it is ignored.') == 1
              and ke("JUMP('', 0, -15, 'LeftShift')") == UP and ke("JUMP('', 0, -15, 'Q')") == UP
              and ke("JUMP('', 0, -15, 'F')") == "none",
              "JumpKeys in config.lua (live): these keys jump, a wrong name is named in the log")
        k.do("NOW = NOW + 60 FRAME(5)")
        check(ke("QUERIES") == queries, "with JumpKeys set, the game is not asked for its keys")
        k.do("GAME_KEYS = { 'SpaceBar' }")
        k.write_config(shipped_text)
        k.do("CONFIG() FRAME()")
        check(ke("QUERIES") == queries + 1 and k.count("Jump keys: SpaceBar (the keys of the game's own jump).") == 1
              and ke("JUMP()") == UP, 'JumpKeys = "" again (live): the game is asked at once')
        params = air("QUERY_MODE = 'params'")
        check(params.count(GAME_KEYS_LINE) == 1 and params.eval("JUMP('W')") == FORWARD,
              "an answer whose items are params (get): the keys are read")
        check(e("INTERFACE_CALLS") == 0 and k.eval("INTERFACE_CALLS") == 0,
              "UE4SS finds the game's function on the subsystem: it is called there")
        by_interface = air("NOT_DIRECT()")
        by_interface.do("GAME_KEYS = { 'F' } NOW = NOW + 10 FRAME()")
        check(by_interface.count(GAME_KEYS_LINE) == 1 and by_interface.count("Jump keys: F (the keys of the game's own "
                                                                          "jump).") == 1
              and by_interface.eval("INTERFACE_CALLS") == 2 and by_interface.eval("JUMP('W', 0, -15, 'F')") == FORWARD,
              "UE4SS does not find the function on the subsystem: it is called through its interface, with the same "
              "result")
        for case, before, reason in [
            ("the game's function cannot be called either way", "NOT_DIRECT() OBJECTS[INTERFACE_PATH] = nil",
             "attempt to call"),
            ("the game's function fails", "QUERY_MODE = 'throws'", "QueryKeysMappedToAction failed)."),
            ("the jump action is not loaded", "OBJECTS[JUMP_PATH] = nil", "the game's jump action IA_Jump is not loaded)."),
            ("the player has no input subsystem", "HAS_SUBSYSTEM = false", "the player has no input subsystem)."),
            ("the game names no key", "GAME_KEYS = {}", "the game names no key for its jump right now)."),
        ]:
            s = air(before)
            line = [x for x in s.log() if "Jump keys:" in x]
            check(len(line) == 1 and "Jump keys: Gamepad_FaceButton_Bottom, SpaceBar (the standard keys; the game's "
                  "own jump keys could not be read: " in line[0] and reason in line[0]
                  and "traceback" not in line[0] and s.eval("JUMP('W')") == FORWARD
                  and s.eval(f"JUMP('', 0, -15, '{PAD}')") == UP,
                  f"{case}: the standard keys jump, the log says why")
        s.do("for _ = 1, 60 do NOW = NOW + 1 FRAME() end")
        tries = s.eval("QUERIES")
        check(6 <= tries <= 14 and s.count("Jump keys:") == 1,
              f"while the game gives no keys, the mod asks again every 2 s, later every 10 s ({tries} in a minute), "
              "and logs no new line")
        s.do("GAME_KEYS = { 'F' } NOW = NOW + 10 FRAME()")
        check(s.count("Jump keys: F (the keys of the game's own jump).") == 1 and s.eval("JUMP('', 0, -15, 'F')") == UP,
              "the game names keys later: they are used from then on")

        # --- The effect.
        loaded = air("OBJECTS[DUST_PATH] = nil")
        check(loaded.eval("LOADS[DUST_PATH]") == 1
              and loaded.count("The effect Dust could not be loaded (not found): air jumps show it only while the "
                               "game has it loaded; the mod tries again every 30 s.") == 1,
              "the effect is missing: the mod tries to load it once, before any jump, and logs the result")
        check(loaded.eval("JUMP()") == UP and loaded.eval("#EFFECTS") == 0 and loaded.count("effect Dust not loaded") == 1
              and loaded.eval("LOADS[DUST_PATH]") == 1,
              "the effect is not loaded in the game: the jump without it, no second load")
        late = air("OBJECTS[SHADOW_PATH] = nil LOADABLE[SHADOW_PATH] = true")
        late.write_config(config(Effect='"Shadow"'))
        late.do("CONFIG() FRAME()")
        check(late.count("The effect Shadow was not loaded in the game; the mod loaded it.") == 1
              and late.eval("JUMP()") == UP and late.eval("EFFECTS[#EFFECTS]").startswith("pawn shadow"),
              "a missing effect that UE4SS can load: loaded when it is chosen (live), then shown")
        noload = air("OBJECTS[DUST_PATH] = nil LoadAsset = nil")
        check(noload.count("this UE4SS cannot load it (no LoadAsset)") == 1 and noload.eval("JUMP()") == UP,
              "a UE4SS without LoadAsset: one line, the jump works")
        failing = air("OBJECTS[DUST_PATH] = nil LOAD_ERROR = 'LoadAsset failed\\nstack traceback'")
        check(failing.count("The effect Dust could not be loaded (LoadAsset failed): air jumps") == 1
              and failing.eval("JUMP()") == UP, "LoadAsset fails: its first line in the log, the jump works")
        failing.do("FRAME(60)")
        check(failing.eval("LOADS[DUST_PATH]") == 1, "after a failed load: no new try within 30 s")
        failing.do("LOAD_ERROR = nil LOADABLE[DUST_PATH] = true NOW = NOW + 30 FRAME()")
        check(failing.eval("LOADS[DUST_PATH]") == 2 and failing.eval("JUMP()") == UP
              and failing.eval("EFFECTS[#EFFECTS]").startswith("pawn dust")
              and failing.count("could not be loaded") == 1,
              "30 s after a failed load the mod tries again; it works now: the jump shows it, no new line")
        dropped = air("OBJECTS[DUST_PATH] = nil LOADABLE[DUST_PATH] = true")
        check(dropped.eval("LOADS[DUST_PATH]") == 1 and dropped.count("The effect Dust was not loaded in the game; the "
                                                                     "mod loaded it.") == 1,
              "a missing effect that UE4SS can load: loaded at once, one line")
        dropped.do("OBJECTS[DUST_PATH] = nil FRAME(70)")
        check(dropped.eval("LOADS[DUST_PATH]") == 2 and dropped.count("loaded it") == 1,
              "the game drops the effect again (as Dust in the game test of 1.2): within 1 s the mod loads it again, "
              "without a new log line")
        dropped.do("OBJECTS[DUST_PATH] = nil")
        check(dropped.eval("JUMP()") == UP and dropped.eval("EFFECTS[#EFFECTS]").startswith("pawn dust")
              and dropped.eval("LOADS[DUST_PATH]") == 3,
              "dropped right before a jump: loaded again, the jump shows it")
        finds = dropped.eval("FINDS[DUST_PATH]")
        dropped.do("FRAME(60)")
        check(dropped.eval("FINDS[DUST_PATH]") - finds <= 2,
              "the effect is looked for about once a second, not every frame")
        nocapsule = air("CAPSULE_ERROR = 'no capsule'")
        check(nocapsule.eval("JUMP()") == UP and nocapsule.eval("EFFECTS[1]").startswith("pawn dust at 10/20/-60"),
              "no capsule to read: the feet 90 below the location")
        broken = air("EFFECT_ERROR = 'SpawnSystemAtLocation failed'")
        check(broken.eval("JUMP()") == UP and broken.eval("JUMP()") == UP
              and broken.count("The effect Dust could not be shown (SpawnSystemAtLocation failed)") == 1,
              "the effect call fails: the jump works, one line")

        # --- The log.
        check(loaded.eval("JUMP()") == UP and loaded.eval("JUMP()") == UP and loaded.count("] air jump ") == 1,
              "three air jumps: one log line (the first)")
        detail = air(text=config(LogDetail="true"))
        detail.do("JUMP() JUMP('W') PAUSED = true JUMP() PAUSED = false SETMODE(1) FRAME() SETMODE(3) FRAME()")
        check(detail.count("air jump") == 2 and detail.count("press ignored: the game is paused") == 1
              and detail.count("movement mode nil -> 3") == 1 and detail.count("movement mode 3 -> 1") == 4
              and detail.count("movement mode 1 -> 3") == 4
              and detail.count("air jump 2 (1 of 1 before landing): key SpaceBar, movement mode 3, launch 600 / 0 / "
                               "800 (direction: keys), effect Dust shown") == 1,
              "LogDetail = true: a line for every air jump, every ignored press and every change of the movement mode")
        detail.do("JUMP() TAP('SpaceBar')")
        check(detail.count("press ignored: no air jump left (Jumps = 2)") == 1,
              "LogDetail = true: a press with no air jump left has a line")

        # --- Jumps: the range and whole numbers.
        for value, expected_line, jumps, text in [
            ("5", "Jumps = 5 is outside 2 to 3; 3 is used", 2, "Jumps = 5 is clamped to 3 (a triple jump)"),
            ("1", "Jumps = 1 is outside 2 to 3; 2 is used", 1, "Jumps = 1 is clamped to 2 (a double jump)"),
            ("2.6", "Jumps = 2.6 is not a whole number; 3 is used", 2, "Jumps = 2.6 is rounded to 3"),
            ("2.4", "Jumps = 2.4 is not a whole number; 2 is used", 1, "Jumps = 2.4 is rounded to 2"),
        ]:
            run = air("", config(Jumps=value))
            run.do("TAP('SpaceBar') TAP('SpaceBar') TAP('SpaceBar')")
            check(run.count(expected_line) == 1 and run.eval("#LAUNCHES") == jumps,
                  f"{text}: {jumps} air jump(s) before landing")

        # --- The player controller and the pawn.
        none = Run(folder(), "HAS_CONTROLLER = false")
        none.do("SETMODE(3) DOWN.SpaceBar = true FRAME(200)")
        check(none.eval("SEARCHES") == 2 and none.eval("KEY_READS") == 0 and none.eval("QUERIES") == 0,
              "no player controller (menus): one search every 2 s (2 in 200 frames), nothing else")
        none.do("HAS_CONTROLLER = true FRAME(200)")
        check(none.eval("SEARCHES") == 3 and none.eval("#LAUNCHES") == 0,
              "the controller is found at the next search and kept; a key held since before does not jump")
        none.do("DOWN.SpaceBar = nil FRAME()")
        check(none.eval("JUMP()") == UP, "then a press in the air jumps")
        none.do("CONTROLLER.valid = false FRAME(10) CONTROLLER.valid = true NOW = NOW + 2 FRAME()")
        check(none.eval("SEARCHES") >= 4 and none.eval("JUMP()") == UP,
              "a controller that is no longer valid is searched again")
        none.do("PAWN.valid = false")
        check(none.eval("JUMP()") == "none", "no pawn: nothing")
        none.do("PAWN.valid = true PAWN.CharacterMovement = { IsValid = function() return false end }")
        check(none.eval("JUMP()") == "none", "a pawn without a character movement: nothing")
        none.do("PAWN.CharacterMovement = MOVEMENT FRAME()")
        check(none.eval("JUMP()") == UP and not any("Error" in line for line in none.log()),
              "the player again: the press jumps; no error line in this run")

        # --- Errors.
        bad = air()
        bad.do("LAUNCH_ERROR = 'LaunchCharacter failed\\nstack traceback:\\n    [C]: in ?'")
        results = {bad.eval("JUMP()") for _ in range(8)}
        check(results == {"none"} and bad.count("Error: LaunchCharacter failed") == 5
              and not any("traceback" in line for line in bad.log()) and bad.count("frames in a row failed") == 0,
              "a launch that fails 8 times: 5 error lines (their first line), the mod does not stop")
        bad.do("LAUNCH_ERROR = nil")
        check(bad.eval("JUMP()") == UP, "the launch works again: the press jumps")
        stop = air()
        stop.do("KEY_ERROR = 'IsInputKeyDown failed' FRAME(30)")
        reads = stop.eval("KEY_READS")
        stop.do("KEY_ERROR = nil FRAME(30)")
        check(stop.count("20 frames in a row failed: the mod stops until the game starts again") == 1
              and stop.count("Error: IsInputKeyDown failed") == 5 and stop.eval("KEY_READS") == reads
              and stop.eval("JUMP()") == "none", "20 failed frames in a row: the mod stops, one line")
        mode = air()
        mode.do("MOVEMENT.MovementMode = { IsValid = function() return false end } FRAME(25)")
        check(mode.count("Error: the player's movement mode reads as") == 5 and mode.count("the mod stops") == 1,
              "a movement mode that is no number: errors, then the stop")
        camera = air()
        camera.do("CONTROLLER.PlayerCameraManager.GetCameraRotation = function() return { Pitch = 0 } end")
        check(camera.eval("JUMP('W')") == "none" and camera.count("Error: the camera's rotation reads as nil / 0") == 1
              and camera.eval("JUMP()") == UP, "a camera rotation without a yaw: no jump with a direction, an error line")

        # --- UE4SS variants.
        for case, before in [("without the engine tick hook", "EngineTickAvailable = false"),
                             ("without LoopInGameThreadAfterFrames", "LoopInGameThreadAfterFrames = nil")]:
            tick = air(before)
            check(list(tick.g.KINDS.values()) == ["delay", "delay"] and list(tick.g.DELAYS.values()) == [16, 5000]
                  and tick.eval("JUMP('W')") == FORWARD, f"a UE4SS {case}: the frame step every 16 ms")
        old = air("LoopInGameThreadWithDelay = nil")
        check(old.eval("ASYNC_LOOPS") == 2 and old.count("no game-thread loops") == 1 and old.eval("GAME_THREAD_CALLS") > 0
              and old.eval("JUMP('W')") == FORWARD, "a UE4SS without game-thread loops: LoopAsync, and a log line")

        # --- The settings files a player may have.
        folders = {}
        for case, content, _ in PLAYER_CONFIGS:
            if content == "wrong types":
                content = r.eval(f"""(function()
                    local lines = {{}}
                    for name, value in pairs(dofile({lua_path(CONFIG)})) do
                        lines[#lines + 1] = string.format("    [%q] = %s,", name, type(value) == "string" and "0" or '"wrong"')
                    end
                    return "return {{\\n" .. table.concat(lines, "\\n") .. "\\n}}\\n"
                end)()""")
            folders[case] = folder(content)
        defaults = settings_lines(Run(folders["an empty or older config.lua"]).log())
        check(defaults == [shipped], f"config.lua ships exactly the defaults of main.lua ({defaults})")
        count = len(list(r.eval(f"dofile({lua_path(CONFIG)})").keys()))
        for case, _, expected in PLAYER_CONFIGS:
            run = Run(folders[case])
            run.do("SETMODE(3) FRAME(2)")
            jumped = run.eval("JUMP('W')")
            run.do("CONFIG()")
            log = run.log()
            fine = (settings_lines(log) == defaults and len(run.g.LOOPS) == 2 and jumped == FORWARD
                    and run.eval("#EFFECTS") == 1 and not any("Error" in line for line in log))
            if expected is None:
                fine = fine and not any("config.lua" in line for line in log)
            else:
                fine = fine and sum(expected in line for line in log) == (count if case.endswith("wrong types") else 1)
            check(fine, f"{case}: starts with the defaults and jumps"
                  + (f", logs '{expected}' once per setting" if case.endswith("wrong types")
                     else (f", logs '{expected}' once" if expected else ", no warning")))
            if not fine:
                for line in log:
                    print("      log: " + line)
        off = Run(folder("return { Enable = false }\n"))
        off.do("SETMODE(3) FRAME(2)")
        check(len(off.g.LOOPS) == 2 and off.eval("JUMP('W')") == "none" and off.eval("SEARCHES") == 0
              and off.count("does nothing until it is true") == 1,
              "Enable = false at start: the loops are there (live settings), no air jump, no search")
        off.write_config(shipped_text)
        off.do("CONFIG() FRAME()")
        check(off.eval("JUMP('W')") == FORWARD, "Enable = true later (live): the next press jumps")

    print(f"{len(failures)} failed" if failures else "all checks passed")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()

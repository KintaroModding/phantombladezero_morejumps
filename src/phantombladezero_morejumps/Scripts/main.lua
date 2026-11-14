-- More Jumps for Phantom Blade Zero.
--
-- A double or triple jump: a press of the jump key in the air launches the player again, until the player has jumped
-- Jumps times in all (2 = a double jump, 3 = a triple jump; the game's own jump on the ground is the first). Each air
-- jump goes UpSpeed upwards, plus DirectionSpeed in the direction the player holds, relative to the camera, and shows
-- one of the game's own effects at the player's feet (Effect: "Dust", the player's footstep dust, the default;
-- "Jump", the game's take-off dust; "Shadow", the player's special dash; "Off"). The count starts again when the
-- player is on the ground (movement mode Walking) or has a new pawn.
--
-- How: once per frame, on the game thread, the mod looks at the player's movement mode (CharacterMovement). While it
-- allows an air jump (not Walking and not Flying; with FallingOnly only Falling), the mod asks the player controller
-- whether a jump key is down (IsInputKeyDown). A press counts when a key goes down after all were seen up in that
-- state, so the press that starts the game's own jump on the ground is not an air jump. Then, unless the player has no
-- air jump left, the game is paused or the last air jump is less than COOLDOWN_S ago, it calls the engine's
-- LaunchCharacter on the player: X and Y are added to the current speed, Z replaces it. On the ground the mod reads no
-- key at all.
--
-- The jump keys: with JumpKeys = "" the mod asks the game which keys its own jump action (IA_Jump) has in the
-- player's key settings, keyboard and gamepad (Enhanced Input, QueryKeysMappedToAction; the game's own debug script
-- reads keys the same way), and asks again every KEYS_INTERVAL_S. When the game gives no answer, the mod uses
-- STANDARD_JUMP_KEYS, and the log says why. JumpKeys with key names replaces both. UE4SS's own key binds
-- (RegisterKeyBind) are not used: they know only fixed keyboard keys, and their callbacks run on another thread.
--
-- The direction: the four direction keys (ForwardKey, BackKey, LeftKey, RightKey); two opposite keys cancel. Without
-- a held key, the left stick of a gamepad. The camera's yaw turns it into a direction in the world.
--
-- The player controller is kept while it is valid; while there is none (menus), the mod searches at most every
-- SEARCH_INTERVAL_S. After MAX_FAILS failed frames in a row (a game update can change one of these parts) the mod
-- stops until the game starts again, and the log says so.
--
-- Settings: the player edits Scripts\config.lua. The mod reads it at start and again every CONFIG_INTERVAL_MS, so a
-- change shows without a restart; a broken or half-saved file keeps the last settings. DEFAULTS holds every setting
-- with its default. A player (or a mod manager) keeps their config.lua across updates, so a new main.lua can meet an
-- older file: a setting that the file lacks, or has with another type, keeps its default, and the log says so. Read a
-- setting only from Settings, never as `config.X or default`: for a true/false setting, `false or true` is true.

local MOD_NAME = "More Jumps"
local VERSION = "1.3"
local CONFIG_INTERVAL_MS = 5000
-- The frame step runs once per frame; a UE4SS without the engine tick hook runs it this often instead.
local FRAME_MS = 16
-- Seconds between two air jumps (real time).
local COOLDOWN_S = 0.1
-- Seconds between two questions to the game about its jump keys; after a failed one, the first tries come sooner.
local KEYS_INTERVAL_S = 10
local KEYS_RETRY_S = 2
local KEYS_FAST_RETRIES = 5
-- Seconds between two searches for the player controller while there is none.
local SEARCH_INTERVAL_S = 2

local JUMP_ACTION_PATH = "/PBZInput/InputActions/IA_Jump.IA_Jump"
local SUBSYSTEM_LIBRARY_PATH = "/Script/Engine.Default__SubsystemBlueprintLibrary"
local INPUT_SUBSYSTEM_CLASS_PATH = "/Script/EnhancedInput.EnhancedInputLocalPlayerSubsystem"
local INTERFACE_QUERY_PATH = "/Script/EnhancedInput.EnhancedInputSubsystemInterface:QueryKeysMappedToAction"
local NIAGARA_LIBRARY_PATH = "/Script/Niagara.Default__NiagaraFunctionLibrary"
-- The choices of Effect: the game's own Niagara systems; feet = true puts it at the player's feet, else at the middle
-- of the body. "Off" shows none.
local EFFECTS = {
    Dust = { feet = true,
        path = "/PBZVFXPack/VFX/BattleFX/Common/Footsteps/NS_Hun_FootSteps_Dust_101.NS_Hun_FootSteps_Dust_101" },
    Jump = { feet = true, path = "/PBZVFXPack/VFX/BattleFX/Common/Jump/NS_Jump_Stone_301.NS_Jump_Stone_301" },
    -- At the feet too: the dash's afterimage is made for the character's feet (at the middle of the body it showed
    -- around the head, game test of 1.2).
    Shadow = { feet = true,
        path = "/PBZVFXPack/VFX/BattleFX/Hun/NS_Hun_SpecialDash_Show_001.NS_Hun_SpecialDash_Show_001" },
}
local EFFECT_CHOICES = { "Dust", "Jump", "Shadow", "Off" }
-- The feet below the player's location (cm) when the capsule cannot be read.
local FEET_FALLBACK = 90
-- Seconds between two looks for the chosen effect; after a failed load, the next try.
local KEEP_LOADED_S = 1
local LOAD_RETRY_S = 30
-- The jump keys when the game's own ones cannot be read: the keys of the game's default key settings.
local STANDARD_JUMP_KEYS = { "Gamepad_FaceButton_Bottom", "SpaceBar" }
local MAX_JUMP_KEYS = 8
-- An Unreal key name, for example SpaceBar, W, LeftShift, Gamepad_FaceButton_Bottom.
local KEY_PATTERN = "^[%w_]+$"
local MAX_KEY_LENGTH = 64
-- The left stick of a gamepad: -1 to 1 each; below the dead zone it counts as not held.
local STICK_X = "Gamepad_LeftX"
local STICK_Y = "Gamepad_LeftY"
local STICK_DEAD_ZONE = 0.3
-- The engine's movement modes (EMovementMode).
local MOVE_WALKING = 1
local MOVE_FALLING = 3
local MOVE_FLYING = 5
-- After this many failed frames in a row the mod stops until the game starts again.
local MAX_FAILS = 20
-- Log at most this many error lines in total.
local MAX_ERROR_LOGS = 5
-- LogDetail: at most this many lines per game start.
local MAX_DETAIL_LOGS = 400

-- Every setting with its default; config.lua ships the same names and values (tests\test_main.py checks it).
local DEFAULTS = {
    Enable = true,
    Jumps = 2,
    UpSpeed = 800,
    DirectionSpeed = 600,
    Effect = "Dust",
    FallingOnly = false,
    JumpKeys = "",
    ForwardKey = "W",
    BackKey = "S",
    LeftKey = "A",
    RightKey = "D",
    LogDetail = false,
}
-- Number settings outside their range are clamped.
local LIMITS = {
    Jumps = { 2, 3 },
    UpSpeed = { 0, 5000 },
    DirectionSpeed = { 0, 5000 },
}
-- Number settings that must be whole numbers; others are rounded.
local WHOLE = { Jumps = true }
-- Text settings with a fixed set of values (any case); another value means the default.
local CHOICES = { Effect = EFFECT_CHOICES }
local DIRECTION_KEYS = { "ForwardKey", "BackKey", "LeftKey", "RightKey" }

local UEHelpers = require("UEHelpers")

local errors = 0
local details = 0

local function Log(message)
    print(string.format("[%s] %s\n", MOD_NAME, message))
end

local function LogError(message)
    errors = errors + 1
    if errors <= MAX_ERROR_LOGS then
        Log(message)
    end
end

local Settings = {}

-- LogDetail lines; message is a function, so nothing is built while LogDetail is off.
local function Detail(message)
    if Settings.LogDetail and details < MAX_DETAIL_LOGS then
        details = details + 1
        Log(message())
    end
end

local function IsValidCall(object)
    return object:IsValid()
end

local function Valid(object)
    if object == nil then
        return false
    end
    local ok, valid = pcall(IsValidCall, object)
    return ok and valid == true
end

-- The first line of an error message (the rest can be a stack trace).
local function FirstLine(message)
    return (tostring(message):match("^[^\r\n]*"))
end

---------------------------------------------------------------------------------------------------------------------
-- Settings
---------------------------------------------------------------------------------------------------------------------

local function CopyDefaults()
    local settings = {}
    for name, value in pairs(DEFAULTS) do
        settings[name] = value
    end
    return settings
end

-- One line for the log: every setting, sorted by name.
local function Describe(settings)
    local names = {}
    for name in pairs(settings) do
        names[#names + 1] = name
    end
    table.sort(names)
    local parts = {}
    for i, name in ipairs(names) do
        parts[i] = name .. "=" .. tostring(settings[name])
    end
    return table.concat(parts, ", ")
end

-- Lua's line number and reason, without the chunk name.
local function Reason(message)
    message = tostring(message)
    local line, reason = message:match("config%.lua:(%d+): ([^\n]*)")
    return line and ("line " .. line .. ": " .. reason) or (message:gsub("%s*\n%s*", " "))
end

-- DEFAULTS with the values of config.lua's text over them; nil and the reason when the text is not a usable file.
local function ParseConfig(text)
    local chunk, problem = load(text, "=config.lua", "t", {})
    if not chunk then
        return nil, "config.lua not read (" .. Reason(problem) .. ")"
    end
    local ok, config = pcall(chunk)
    if not ok then
        return nil, "config.lua not read (" .. Reason(config) .. ")"
    end
    if type(config) ~= "table" then
        return nil, "config.lua does not return a table"
    end
    local settings = CopyDefaults()
    for name, value in pairs(config) do
        local default = DEFAULTS[name]
        local limit = LIMITS[name]
        if default == nil then
            Log("config.lua: unknown setting " .. tostring(name) .. " ignored.")
        elseif type(value) ~= type(default) then
            Log(string.format("config.lua: %s must be a %s; the default %s is used.", name, type(default),
                tostring(default)))
        elseif limit and value ~= value then
            Log(string.format("config.lua: %s is not a number; the default %s is used.", name, tostring(default)))
        elseif limit and (value < limit[1] or value > limit[2]) then
            local clamped = math.min(limit[2], math.max(limit[1], value))
            if WHOLE[name] then
                clamped = math.floor(clamped + 0.5)
            end
            Log(string.format("config.lua: %s = %s is outside %s to %s; %s is used.", name, tostring(value),
                tostring(limit[1]), tostring(limit[2]), tostring(clamped)))
            settings[name] = clamped
        elseif WHOLE[name] and value % 1 ~= 0 then
            local rounded = math.floor(value + 0.5)
            Log(string.format("config.lua: %s = %s is not a whole number; %s is used.", name, tostring(value),
                tostring(rounded)))
            settings[name] = rounded
        elseif CHOICES[name] then
            local chosen = nil
            for _, choice in ipairs(CHOICES[name]) do
                if choice:lower() == value:lower() then
                    chosen = choice
                end
            end
            if not chosen then
                Log(string.format('config.lua: %s = "%s" is not one of %s; "%s" is used.', name, value,
                    table.concat(CHOICES[name], ", "), default))
            end
            settings[name] = chosen or default
        else
            settings[name] = value
        end
    end
    return settings
end

local function IsKeyName(text)
    return #text <= MAX_KEY_LENGTH and text:match(KEY_PATTERN) ~= nil
end

-- The key names in a JumpKeys text (separated by commas, semicolons or spaces), each once, and the parts that are no
-- key names.
local function SplitKeys(text)
    local names, wrong, seen = {}, {}, {}
    for part in text:gmatch("[^,;%s]+") do
        if not IsKeyName(part) then
            wrong[#wrong + 1] = part
        elseif not seen[part] and #names < MAX_JUMP_KEYS then
            seen[part] = true
            names[#names + 1] = part
        end
    end
    return names, wrong
end

-- Names the key settings that the mod cannot use.
local function CheckKeySettings(settings)
    for _, name in ipairs(DIRECTION_KEYS) do
        local key = settings[name]
        if key ~= "" and not IsKeyName(key) then
            Log(string.format('config.lua: %s = "%s" is not a key name; that direction is not read.', name, key))
        end
    end
    local _, wrong = SplitKeys(settings.JumpKeys)
    for _, part in ipairs(wrong) do
        Log(string.format('config.lua: JumpKeys: "%s" is not a key name; it is ignored.', part))
    end
end

local configPath = nil
-- The text of the last read; false: no file at the last read; nil: not read yet.
local configText = nil

-- Reads config.lua when its text changed since the last read. At start, a missing or broken file means the defaults;
-- later, a broken file keeps the last settings (a half-saved file), and a missing one means the defaults.
local function ReadConfig()
    local atStart = configText == nil
    configPath = configPath or package.searchpath("config", package.path)
    local text = false
    if configPath then
        local file = io.open(configPath, "rb")
        if file then
            text = file:read("a") or false
            file:close()
        end
    end
    if text == configText then
        return
    end
    configText = text
    local settings, problem
    if text == false then
        settings, problem = CopyDefaults(), nil
        Log("No config.lua; every setting uses its default.")
    else
        settings, problem = ParseConfig(text)
    end
    if not settings then
        if atStart then
            Log(problem .. "; every setting uses its default.")
            settings = CopyDefaults()
        else
            Log(problem .. "; the last settings stay.")
            return
        end
    end
    local line = Describe(settings)
    if atStart or line ~= Describe(Settings) then
        Log("Settings: " .. line)
        CheckKeySettings(settings)
    end
    Settings = settings
end

---------------------------------------------------------------------------------------------------------------------
-- Keys
---------------------------------------------------------------------------------------------------------------------

-- A key as the game's key struct (FKey), made once per name.
local keyStructs = {}

local function Key(name)
    local key = keyStructs[name]
    if not key then
        key = { KeyName = FName(name) }
        keyStructs[name] = key
    end
    return key
end

local function KeyDown(controller, name)
    return controller:IsInputKeyDown(Key(name)) == true
end

-- The value of a returned array item: UE4SS gives a Lua table for a returned struct; a param has get().
local function Unwrap(value)
    if type(value) == "table" or type(value) == "userdata" then
        local ok, result = pcall(function()
            return value:get()
        end)
        if ok and result ~= nil then
            return result
        end
    end
    return value
end

-- A key's name as Lua text (UE4SS gives an FName); nil when it is none.
local function KeyText(value)
    if type(value) ~= "string" then
        if type(value) ~= "userdata" and type(value) ~= "table" then
            return nil
        end
        local ok, text = pcall(function()
            return value:ToString()
        end)
        if not ok then
            return nil
        end
        value = text
    end
    if type(value) ~= "string" or not IsKeyName(value) or value == "None" then
        return nil
    end
    return value
end

local queryByInterface = false

-- The game's answer to QueryKeysMappedToAction. The function belongs to an interface of the subsystem
-- (EnhancedInputSubsystemInterface); when UE4SS does not find it on the subsystem itself, the mod calls the
-- interface's function object on the subsystem (CallFunction), and keeps to that way once it worked.
local function QueryKeys(subsystem, action)
    local problem = nil
    if not queryByInterface then
        local ok, keys = pcall(function()
            return subsystem:QueryKeysMappedToAction(action)
        end)
        if ok then
            return keys
        end
        problem = keys
    end
    local query = StaticFindObject(INTERFACE_QUERY_PATH)
    if not Valid(query) then
        error(problem or "the engine's function QueryKeysMappedToAction is not there", 0)
    end
    local keys = subsystem:CallFunction(query, action)
    queryByInterface = true
    return keys
end

-- The keys of the game's own jump action in the player's current key settings, sorted; nil and the reason when the
-- game does not name any. Errors are the caller's (pcall).
local function GameJumpKeys(controller)
    local action = StaticFindObject(JUMP_ACTION_PATH)
    if not Valid(action) then
        return nil, "the game's jump action IA_Jump is not loaded"
    end
    local library = StaticFindObject(SUBSYSTEM_LIBRARY_PATH)
    local class = StaticFindObject(INPUT_SUBSYSTEM_CLASS_PATH)
    if not Valid(library) or not Valid(class) then
        return nil, "the engine's input subsystem class is not there"
    end
    local subsystem = library:GetLocalPlayerSubSystemFromPlayerController(controller, class)
    if not Valid(subsystem) then
        return nil, "the player has no input subsystem"
    end
    local keys = QueryKeys(subsystem, action)
    local items = {}
    if type(keys) == "table" then
        for _, item in pairs(keys) do
            items[#items + 1] = item
        end
    else
        -- A UE4SS array: check its length before reading an item (an index past the end grows the array).
        for i = 1, math.min(#keys, MAX_JUMP_KEYS) do
            items[#items + 1] = keys[i]
        end
    end
    local names, seen = {}, {}
    for _, item in ipairs(items) do
        local key = Unwrap(item)
        local name = (type(key) == "table" or type(key) == "userdata") and KeyText(key.KeyName) or nil
        if name and not seen[name] and #names < MAX_JUMP_KEYS then
            seen[name] = true
            names[#names + 1] = name
        end
    end
    if #names == 0 then
        return nil, "the game names no key for its jump right now"
    end
    table.sort(names)
    return names
end

local jumpKeys = {}         -- the key names the mod looks at
local keysLine = nil        -- the last log line about them
local keysSetting = nil     -- the JumpKeys text of the last look
local nextKeysRead = 0      -- os.clock() of the next question to the game
local keysFails = 0         -- failed questions in a row
local gameKeys = nil        -- the game's last answer that named keys

local function UseKeys(names, origin)
    jumpKeys = names
    local line = "Jump keys: " .. table.concat(names, ", ") .. " (" .. origin .. ")."
    if line ~= keysLine then
        keysLine = line
        Log(line)
    end
end

-- Keeps jumpKeys in step with the settings and with the game's key settings.
local function UpdateJumpKeys(controller, now)
    local setting = Settings.JumpKeys
    if setting ~= keysSetting then
        keysSetting = setting
        nextKeysRead = 0
    end
    if now < nextKeysRead then
        return
    end
    local named = SplitKeys(setting)
    if #named > 0 then
        nextKeysRead = math.huge
        UseKeys(named, "JumpKeys in config.lua")
        return
    end
    local ok, names, reason = pcall(GameJumpKeys, controller)
    if ok and names then
        keysFails = 0
        nextKeysRead = now + KEYS_INTERVAL_S
        gameKeys = names
        UseKeys(names, "the keys of the game's own jump")
        return
    end
    keysFails = keysFails + 1
    nextKeysRead = now + (keysFails <= KEYS_FAST_RETRIES and KEYS_RETRY_S or KEYS_INTERVAL_S)
    reason = FirstLine(ok and reason or names)
    if gameKeys then
        -- A menu or a state without the jump in its key set: the last answer stays.
        UseKeys(gameKeys, "the keys of the game's own jump")
        Detail(function() return "the game's jump keys were not read (" .. reason .. "); the last ones stay" end)
    else
        UseKeys(STANDARD_JUMP_KEYS, "the standard keys; the game's own jump keys could not be read: " .. reason)
    end
end

---------------------------------------------------------------------------------------------------------------------
-- The air jump
---------------------------------------------------------------------------------------------------------------------

local stickOff = false

-- The left stick of a gamepad: right and forward, -1 to 1 each. After a failed read the stick is not asked again.
local function Stick(controller)
    if stickOff then
        return 0, 0
    end
    local ok, x, y = pcall(function()
        return controller:GetInputAnalogKeyState(Key(STICK_X)), controller:GetInputAnalogKeyState(Key(STICK_Y))
    end)
    if not ok or type(x) ~= "number" or type(y) ~= "number" or x ~= x or y ~= y then
        stickOff = true
        Log("The gamepad's left stick could not be read (" .. FirstLine(ok and "no number" or x)
            .. "): the direction comes from the direction keys only.")
        return 0, 0
    end
    return x, y
end

local function DirectionKeyDown(controller, setting)
    local name = Settings[setting]
    return name ~= "" and IsKeyName(name) and KeyDown(controller, name)
end

-- The held direction as a unit vector in the world (X, Y) and where it came from ("keys", "stick", "none", or "off"
-- with DirectionSpeed 0, when nothing is read): forward and right from the direction keys or the stick, turned by
-- the camera's yaw.
local function Direction(controller)
    if Settings.DirectionSpeed == 0 then
        return 0, 0, "off"
    end
    local forward, right, from = 0, 0, "keys"
    local f, b = DirectionKeyDown(controller, "ForwardKey"), DirectionKeyDown(controller, "BackKey")
    local l, r = DirectionKeyDown(controller, "LeftKey"), DirectionKeyDown(controller, "RightKey")
    if f and not b then
        forward = 1
    elseif b and not f then
        forward = -1
    end
    if r and not l then
        right = 1
    elseif l and not r then
        right = -1
    end
    if forward == 0 and right == 0 and not (f or b or l or r) then
        local x, y = Stick(controller)
        if x * x + y * y >= STICK_DEAD_ZONE * STICK_DEAD_ZONE then
            forward, right, from = y, x, "stick"
        end
    end
    if forward == 0 and right == 0 then
        return 0, 0, "none"
    end
    local camera = controller.PlayerCameraManager
    if not Valid(camera) then
        error("the player has no camera manager", 0)
    end
    local rotation = camera:GetCameraRotation()
    local yaw, pitch = rotation.Yaw, rotation.Pitch
    if type(yaw) ~= "number" or type(pitch) ~= "number" or yaw ~= yaw or pitch ~= pitch then
        error("the camera's rotation reads as " .. tostring(yaw) .. " / " .. tostring(pitch), 0)
    end
    -- The camera looks straight up or down: it has no forward direction on the ground plane.
    if math.abs(math.cos(math.rad(pitch))) <= 0.001 then
        return 0, 0, "none"
    end
    local length = math.sqrt(forward * forward + right * right)
    forward, right = forward / length, right / length
    local cos, sin = math.cos(math.rad(yaw)), math.sin(math.rad(yaw))
    return forward * cos - right * sin, forward * sin + right * cos, from
end

local effectLoads = {}      -- choice -> { loads = n, failedAt = os.clock() of the last failed load, logged = true }

-- The Niagara system of an effect choice; nil when it is not there. A system that the game has not loaded, or has
-- thrown out of memory again (nothing in the game holds it; game test of 1.2: Dust was gone before the first jump),
-- the mod loads with UE4SS's LoadAsset, on the game thread. After a failed load it tries again LOAD_RETRY_S later.
local function EffectSystem(choice, now)
    local effect = EFFECTS[choice]
    local system = StaticFindObject(effect.path)
    if Valid(system) then
        return system
    end
    local state = effectLoads[choice] or { loads = 0 }
    effectLoads[choice] = state
    if state.failedAt and now - state.failedAt < LOAD_RETRY_S then
        return nil
    end
    if type(LoadAsset) ~= "function" then
        state.failedAt = now
        if not state.logged then
            state.logged = true
            Log("The effect " .. choice .. " is not loaded in the game, and this UE4SS cannot load it (no LoadAsset): "
                .. "air jumps show it only while the game has it loaded.")
        end
        return nil
    end
    local ok, problem = pcall(LoadAsset, effect.path)
    system = StaticFindObject(effect.path)
    if Valid(system) then
        state.loads = state.loads + 1
        state.failedAt = nil
        if state.loads == 1 then
            Log("The effect " .. choice .. " was not loaded in the game; the mod loaded it.")
        else
            Detail(function() return "the game had dropped the effect " .. choice .. "; loaded again (load "
                .. state.loads .. ")" end)
        end
        return system
    end
    state.failedAt = now
    if not state.logged then
        state.logged = true
        Log("The effect " .. choice .. " could not be loaded (" .. (ok and "not found" or FirstLine(problem))
            .. "): air jumps show it only while the game has it loaded; the mod tries again every " .. LOAD_RETRY_S
            .. " s.")
    end
    return nil
end

-- The height of the player's feet below its location: the capsule's half height.
local function FeetHeight(pawn)
    local ok, half = pcall(function()
        return pawn.CapsuleComponent:GetScaledCapsuleHalfHeight()
    end)
    if ok and type(half) == "number" and half > 0 and half < 1000 then
        return half
    end
    return FEET_FALLBACK
end

-- The chosen effect at the player; false while the effect is not there.
local function SpawnEffect(pawn, choice, now)
    local library = StaticFindObject(NIAGARA_LIBRARY_PATH)
    local system = EffectSystem(choice, now)
    if not Valid(library) or not system then
        return false
    end
    local location = pawn:K2_GetActorLocation()
    local x, y, z = location.X, location.Y, location.Z
    if type(x) ~= "number" or type(y) ~= "number" or type(z) ~= "number" then
        error("the player's location reads as " .. tostring(x), 0)
    end
    if EFFECTS[choice].feet then
        z = z - FeetHeight(pawn)
    end
    -- Auto destroy, auto activate, no pooling, pre-cull check: the values of the mod this one comes from.
    library:SpawnSystemAtLocation(pawn, system, { X = x, Y = y, Z = z }, { Pitch = 0, Yaw = 0, Roll = 0 },
        { X = 1, Y = 1, Z = 1 }, true, true, 0, true)
    return true
end

local controller = nil      -- the player controller, kept while it is valid
local nextSearch = 0        -- os.clock() of the next search for it
local wasDown = true        -- a jump key was down at the last look; true also means "not seen up yet"
local lastMode = nil
local lastJump = -math.huge
local jumps = 0             -- air jumps since the game start, for the log
local airJumps = 0          -- air jumps since the player was last on the ground
local lastPawn = nil        -- the pawn's address at the last frame; a new pawn starts the count again
local preparedEffect = nil  -- the Effect choice the mod looked for last
local nextEffectCheck = 0   -- os.clock() of the next look for the chosen effect
local effectFailed = false

local function AirJump(pawn, mode, key, now)
    local x, y, from = Direction(controller)
    local velocity = { X = x * Settings.DirectionSpeed, Y = y * Settings.DirectionSpeed, Z = Settings.UpSpeed }
    local choice = Settings.Effect
    local effect = "off"
    if EFFECTS[choice] then
        local ok, shown = pcall(SpawnEffect, pawn, choice, now)
        effect = choice .. " " .. (ok and (shown and "shown" or "not loaded") or "failed")
        if not ok and not effectFailed then
            effectFailed = true
            Log("The effect " .. choice .. " could not be shown (" .. FirstLine(shown) .. "); the air jump works "
                .. "without it.")
        end
    end
    -- X and Y are added to the current speed, Z replaces it.
    pawn:LaunchCharacter(velocity, false, true)
    lastJump = now
    jumps = jumps + 1
    airJumps = airJumps + 1
    local line = function()
        return string.format("air jump %d (%d of %d before landing): key %s, movement mode %d, launch %.0f / %.0f / "
            .. "%.0f (direction: %s), effect %s", jumps, airJumps, Settings.Jumps - 1, key, mode, velocity.X,
            velocity.Y, velocity.Z, from, effect)
    end
    if jumps == 1 then
        Log(line() .. ". LogDetail = true logs every air jump.")
    else
        Detail(line)
    end
end

-- One frame: looks for a new press of a jump key while the player's movement mode allows an air jump.
local function Frame()
    if not Settings.Enable then
        wasDown = true
        return
    end
    local now = os.clock()
    if not Valid(controller) then
        controller = nil
        wasDown = true
        if now < nextSearch then
            return
        end
        nextSearch = now + SEARCH_INTERVAL_S
        local found = UEHelpers.GetPlayerController()
        if not Valid(found) then
            return
        end
        controller = found
    end
    local pawn = controller.Pawn
    if not Valid(pawn) then
        wasDown = true
        return
    end
    local pawnAddress = pawn:GetAddress()
    if pawnAddress ~= lastPawn then
        lastPawn = pawnAddress
        airJumps = 0
    end
    local movement = pawn.CharacterMovement
    if not Valid(movement) then
        wasDown = true
        return
    end
    UpdateJumpKeys(controller, now)
    -- Keep the chosen effect loaded: look for it when it is chosen and every KEEP_LOADED_S (a cheap lookup by path),
    -- and load it again when the game has dropped it, so the load rarely falls into a jump.
    if Settings.Effect ~= preparedEffect or now >= nextEffectCheck then
        preparedEffect = Settings.Effect
        nextEffectCheck = now + KEEP_LOADED_S
        if EFFECTS[preparedEffect] then
            EffectSystem(preparedEffect, now)
        end
    end
    local mode = movement.MovementMode
    if type(mode) ~= "number" then
        error("the player's movement mode reads as " .. tostring(mode), 0)
    end
    if mode ~= lastMode then
        local before = lastMode
        lastMode = mode
        Detail(function() return "movement mode " .. tostring(before) .. " -> " .. mode end)
    end
    if mode == MOVE_WALKING then
        airJumps = 0
    end
    local allowed
    if Settings.FallingOnly then
        allowed = mode == MOVE_FALLING
    else
        allowed = mode ~= MOVE_WALKING and mode ~= MOVE_FLYING
    end
    if not allowed then
        wasDown = true
        return
    end
    local down = nil
    for _, name in ipairs(jumpKeys) do
        if KeyDown(controller, name) then
            down = name
            break
        end
    end
    local pressed = down ~= nil and not wasDown
    wasDown = down ~= nil
    if not pressed then
        return
    end
    if airJumps >= Settings.Jumps - 1 then
        Detail(function() return "press ignored: no air jump left (Jumps = " .. Settings.Jumps .. ")" end)
        return
    end
    if now - lastJump < COOLDOWN_S then
        Detail(function() return "press ignored: less than " .. COOLDOWN_S .. " s after the last air jump" end)
        return
    end
    -- As in the mod this one comes from: a pause check that fails does not stop the jump.
    local ok, paused = pcall(function()
        return UEHelpers.GetGameplayStatics():IsGamePaused(pawn)
    end)
    if ok and paused == true then
        Detail(function() return "press ignored: the game is paused" end)
        return
    end
    AirJump(pawn, mode, down, now)
end

---------------------------------------------------------------------------------------------------------------------
-- Start
---------------------------------------------------------------------------------------------------------------------

Settings = CopyDefaults()
Log(VERSION .. " loaded.")
local read, problem = pcall(ReadConfig)
if not read then
    LogError("Error while reading config.lua: " .. tostring(problem))
end
if not Settings.Enable then
    Log("Enable = false in config.lua: the mod does nothing until it is true.")
end

local fails = 0
local stopped = false

local function Step()
    if stopped then
        return
    end
    local ok, err = pcall(Frame)
    if ok then
        fails = 0
        return
    end
    -- The press that failed does not count again in the next frame.
    wasDown = true
    fails = fails + 1
    LogError("Error: " .. FirstLine(err))
    if fails >= MAX_FAILS then
        stopped = true
        Log(MAX_FAILS .. " frames in a row failed: the mod stops until the game starts again. A game update may need a "
            .. "new version of the mod.")
    end
end

local function ConfigStep()
    local ok, err = pcall(ReadConfig)
    if not ok then
        LogError("Error while reading config.lua: " .. tostring(err))
    end
end

-- Both loops run on the game thread (UE4SS's Delayed Action API): no Lua on a second thread (Witch Time's crash
-- lesson). The frame step runs once per frame when UE4SS has its engine tick hook (EngineTickAvailable), else every
-- FRAME_MS. A UE4SS without the Delayed Action API gets the old LoopAsync loops, and the log says so.
if type(LoopInGameThreadWithDelay) == "function" then
    if EngineTickAvailable == true and type(LoopInGameThreadAfterFrames) == "function" then
        LoopInGameThreadAfterFrames(1, Step)
    else
        LoopInGameThreadWithDelay(FRAME_MS, Step)
    end
    LoopInGameThreadWithDelay(CONFIG_INTERVAL_MS, ConfigStep)
else
    Log("This UE4SS has no game-thread loops (LoopInGameThreadWithDelay): the older LoopAsync is used; a newer UE4SS "
        .. "is safer.")
    LoopAsync(FRAME_MS, function()
        ExecuteInGameThread(Step)
        -- false keeps the loop running.
        return false
    end)
    LoopAsync(CONFIG_INTERVAL_MS, function()
        ExecuteInGameThread(ConfigStep)
        return false
    end)
end

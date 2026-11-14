# More Jumps

A double or triple jump: press the jump key in the air to jump again, up and in the direction you hold, relative to the camera. Two jumps by default, three with Jumps = 3; jumps, speeds, keys and the effect are set in config.lua, live in game.

A [UE4SS](https://github.com/UE4SS-RE/RE-UE4SS) Lua mod for Phantom Blade Zero (Unreal Engine 5.7), made with
game version `CL-302256_JKS-17280` and UE4SS `v3.0.1-1195-g1ceefac8`, tested in game with UE4SS `v4.0.0` (1.3, 2026-11-13). This README is for developers; what the mod does and
how to install it are in [openmods.md](openmods.md), the mod page on [openmods](https://openmods.nexus).

## How it works

`Scripts/main.lua` runs one step per frame on the game thread (`LoopInGameThreadAfterFrames(1, ...)`; every 16 ms on
a UE4SS without the engine tick hook). The step takes the player controller (kept while it is valid; while there is
none, one search every 2 seconds), its `Pawn` and the pawn's `CharacterMovement.MovementMode`.

- **When an air jump is allowed:** in every movement mode but Walking (1) and Flying (5); with `FallingOnly = true`
  only in Falling (3). In the other modes the step ends there and reads no key.
- **How many:** `Jumps` counts all jumps before landing, the game's own jump included: 2 (the default) allows one
  air jump, a double jump; 3 allows two, a triple jump. The count starts again in movement mode Walking and with a
  new pawn (its address changed: a death, a map load); a change between air modes does not start it again.
- **The press:** the step asks `PlayerController:IsInputKeyDown` for each jump key. A press counts when a key is down
  after all were seen up in an allowed mode, so the press that starts the game's own jump on the ground, still held in
  the air, is not an air jump. A press with no air jump left is ignored, so is one less than 0.1 seconds after the last air
  jump, and one while `GameplayStatics:IsGamePaused` says yes.
- **The launch:** `LaunchCharacter({X, Y, Z}, false, true)` on the pawn: Z = `UpSpeed` replaces the vertical speed, X
  and Y = the held direction times `DirectionSpeed` are added to the current speed.
- **The direction:** the four direction keys (`ForwardKey`, `BackKey`, `LeftKey`, `RightKey`); two opposite keys
  cancel. Without a held direction key, the gamepad's left stick (`GetInputAnalogKeyState` of `Gamepad_LeftX` and
  `Gamepad_LeftY`, dead zone 0.3). The yaw of `PlayerCameraManager:GetCameraRotation()` turns it into a direction in
  the world; every direction has the same speed. With the camera straight up or down there is only the upward part.
- **The jump keys:** with `JumpKeys = ""` the mod asks the game for the keys of its own jump action
  (`/PBZInput/InputActions/IA_Jump`) in the player's current key settings:
  `SubsystemBlueprintLibrary:GetLocalPlayerSubSystemFromPlayerController` gives the `EnhancedInputLocalPlayerSubsystem`,
  and its `QueryKeysMappedToAction` the keys (the game's own script `System/Debug/DebugObj.js` reads keys the same
  way). That function belongs to an interface of the subsystem; when UE4SS does not find it on the subsystem, the
  mod calls the interface's function object on it (`CallFunction`). It asks again every 10 seconds. When the game gives no keys, the mod uses `SpaceBar` and
  `Gamepad_FaceButton_Bottom` and asks again (every 2 seconds five times, then every 10); an answer without keys
  after a good one keeps the last keys. The log line `Jump keys: ...` names the keys and where they come from.
  `JumpKeys` with key names replaces all of this.
- **The effect:** `NiagaraFunctionLibrary:SpawnSystemAtLocation` with one of the game's own systems, by `Effect`
  (any case): `Dust` (the default) `/PBZVFXPack/VFX/BattleFX/Common/Footsteps/NS_Hun_FootSteps_Dust_101`, the
  player's footstep dust; `Jump` `/PBZVFXPack/VFX/BattleFX/Common/Jump/NS_Jump_Stone_301`, the game's take-off
  dust; `Shadow` `/PBZVFXPack/VFX/BattleFX/Hun/NS_Hun_SpecialDash_Show_001`, the player's special dash. All at
  the feet: the pawn's location minus `CapsuleComponent:GetScaledCapsuleHalfHeight()`, else 90 (at the pawn's
  location, the middle of the body, Shadow showed around the head). `Off` shows none. The chosen system is kept
  loaded: the mod looks for it (`StaticFindObject`) when it is chosen and every second, and loads it with UE4SS's
  `LoadAsset` when it is missing; the game drops an effect that nothing holds (in 1.2 Dust was gone before the
  first jump). After a failed load it tries again 30 seconds later. A failed effect call does not stop the jump. Up to 1.1 the effect was the game's blue attack warning
  (`NS_AttackAlert_Blue_001`), with a flash and a sound.

The mod uses no UE4SS key bind (`RegisterKeyBind`): it knows only fixed keyboard keys, and its callbacks run on
UE4SS's own thread, not on the game thread.

Errors: the step runs inside `pcall`. The log gets at most 5 error lines; after 20 failed frames in a row the mod
stops until the game starts again. The first air jump has a log line; `LogDetail = true` logs every air jump, every
ignored press (also one with no air jump left) and every change of the movement mode.

## Deploy and test

```powershell
powershell -ExecutionPolicy Bypass -File .\deploy.ps1     # copy the mod folder into the game's ue4ss\Mods
python tests\test_main.py                                 # offline test of main.lua (needs lupa)
```

`deploy.ps1` copies `src\phantombladezero_morejumps\` to `<game folder>\platform\steam\ue4ss\Mods\phantombladezero_morejumps\`. The game
folder is `$env:UE5_GAMES_DIR\PBZ`; `-GameDir` or `-ModsDir` override it. The mod folder holds
`enabled.txt`, so UE4SS starts it without an entry in `mods.txt`. An existing `Scripts\config.lua` in the game stays
(the tester's settings); `-ResetConfig` copies the shipped one. UE4SS loads Lua mods at game start. The mod writes
its lines into `ue4ss\UE4SS.log`, for example `[More Jumps] 1.1 loaded.`

`tests\test_main.py` runs `main.lua` in Lua 5.4 ([lupa](https://pypi.org/project/lupa/)) with mocks of the UE4SS
functions that the script uses. It finds syntax and logic errors before a game start.

Versioning: every change raises the second number (1.0 -> 1.1) in `mod.json` and in `main.lua`:
`python scripts\bump_version.py`.

## Settings

`Scripts/config.lua` holds the player's settings, `DEFAULTS` in `main.lua` every setting with its default and
`LIMITS` the range of the number settings (`Jumps` 2 to 3, a whole number: others are rounded, `WHOLE`). The mod reads the file at start and again every 5 seconds (`ReadConfig`):
a changed file is used from the next frame on, a broken or half-saved one keeps the last settings, a missing one
means the defaults. Players and mod managers keep their own `config.lua` across updates, so a new `main.lua` can
meet an older file: a setting that the file lacks, or has with another type, keeps its default, and the log says so
(`ParseConfig`). Key names are Unreal's (`SpaceBar`, `W`, `Gamepad_FaceButton_Bottom`); a text that is no key name is
named in the log (`CheckKeySettings`). Add each setting to both files with the same value, and read it only from
`Settings`, never as `config.X or default` (for a true/false setting, `false or true` is true).
`tests\test_main.py` checks that `config.lua` ships exactly the defaults, and runs `main.lua` with a missing, empty,
broken and wrong `config.lua`.

## Project layout

```
src/phantombladezero_morejumps/   The UE4SS mod folder: Scripts/main.lua, Scripts/config.lua, enabled.txt
tests/test_main.py    Offline test of main.lua with mocks of UE4SS and the game
docs/                 Cover and screenshots
scripts/              bump_version.py
deploy.ps1            Copies the mod folder into the game's ue4ss\Mods
mod.json              Name, version, game, engine and UE4SS version
```

## License

MIT, see [LICENSE](LICENSE).

-- Settings of More Jumps. Change a value and save the file: the mod reads it again every 5 seconds, in game.
-- A file it cannot read (for example while it is saved) keeps the last settings.
-- A setting that this file does not have keeps its default, so an older copy of the file still works after an update.
-- Key names are Unreal's, for example SpaceBar, W, LeftShift, Up, Gamepad_FaceButton_Bottom.
return {
    Enable = true,          -- false: the mod does nothing, the game as normal
    Jumps = 2,              -- jumps before you land, the game's own jump included: 2 = double jump, 3 = triple jump
    UpSpeed = 800,          -- the upward speed of an air jump (0 to 5000)
    DirectionSpeed = 600,   -- the speed in the direction you hold, added to your current speed (0 to 5000; 0 = only up)
    Effect = "Dust",        -- the effect on an air jump: "Dust" (a small dust puff at your feet), "Jump" (the game's take-off dust), "Shadow" (your special dash's afterimage) or "Off"
    FallingOnly = false,    -- true: an air jump only while you fall; false: in every state but walking and flying
    JumpKeys = "",          -- "": the keys of the game's own jump (your key settings); or your own, for example "SpaceBar, Gamepad_FaceButton_Bottom"
    ForwardKey = "W",       -- the four direction keys the mod looks at for the direction of an air jump
    BackKey = "S",
    LeftKey = "A",
    RightKey = "D",
    LogDetail = false,      -- true: ue4ss\UE4SS.log names every air jump and every change of your movement mode (for tests)
}

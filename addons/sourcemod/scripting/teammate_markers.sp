// Teammate markers for co-op (Black Mesa has no player outline glow):
//  - a coloured glow sprite floating above every living player, hidden from
//    that player themselves
//  - a HUD line per teammate with distance and direction relative to where
//    you're looking ("Player2  25m  ahead-left, below")
#include <sourcemod>
#include <sdktools>
#include <sdkhooks>

#pragma semicolon 1
#pragma newdecls required

public Plugin myinfo =
{
    name = "Teammate markers",
    author = "stitch",
    description = "Glow above teammates' heads + HUD direction/distance",
    version = "1.5.0",
    url = ""
};

#define SPRITE_MDL "sprites/light_glow02_add_noz.vmt"   // HL2 content (mounted by Blue Shift), $ignorez: draws through walls
#define HEAD_OFFSET 84.0

ConVar g_cvGlow, g_cvHud, g_cvHudMode, g_cvLag;
int g_GameText = INVALID_ENT_REFERENCE;
int g_Sprite[MAXPLAYERS + 1] = {INVALID_ENT_REFERENCE, ...};
Handle g_HudSync;
bool g_HasHudMsg;

static const int g_Colors[][3] = {
    {255, 140, 0}, {0, 220, 255}, {120, 255, 60}, {255, 60, 200},
    {255, 230, 0}, {170, 110, 255}, {255, 70, 70}, {255, 255, 255}
};

public void OnPluginStart()
{
    g_cvGlow = CreateConVar("markers_glow", "1", "Glow sprite above each player's head");
    g_cvHud = CreateConVar("markers_hud", "1", "HUD line per teammate with distance and direction");
    g_cvHudMode = CreateConVar("markers_hud_mode", "1", "1 = SourceMod HudMsg, 2 = game_text entity, 3 = hint box, 4 = centre text");
    g_cvLag = CreateConVar("markers_lag", "0.05", "Seconds the dot trails the player's movement (match client interpolation)");
    RegServerCmd("sm_markers_test", Cmd_Test, "Show a test line with every HUD method");
    g_cvGlow.AddChangeHook(OnGlowChanged);
    RegServerCmd("sm_markers", Cmd_Status, "Show teammate marker status");
    HookEvent("player_spawn", Event_Spawn);
    HookEvent("player_death", Event_Death);
    g_HudSync = CreateHudSynchronizer();
    g_HasHudMsg = GetUserMessageId("HudMsg") != INVALID_MESSAGE_ID;
    CreateTimer(0.5, Timer_Tick, _, TIMER_REPEAT);
}

public void OnMapStart()
{
    PrecacheModel(SPRITE_MDL, true);
    for (int i = 1; i <= MaxClients; i++)
        g_Sprite[i] = INVALID_ENT_REFERENCE;
    g_GameText = INVALID_ENT_REFERENCE;
}

int GetGameText()
{
    int e = EntRefToEntIndex(g_GameText);
    if (e != INVALID_ENT_REFERENCE)
        return e;
    e = CreateEntityByName("game_text");
    if (e == -1)
        return -1;
    DispatchKeyValue(e, "targetname", "teammate_markers_text");
    DispatchKeyValue(e, "x", "0.015");
    DispatchKeyValue(e, "y", "0.02");
    DispatchKeyValue(e, "channel", "3");
    DispatchKeyValue(e, "color", "255 200 120");
    DispatchKeyValue(e, "color2", "255 200 120");
    DispatchKeyValue(e, "effect", "0");
    DispatchKeyValue(e, "fadein", "0");
    DispatchKeyValue(e, "fadeout", "0");
    DispatchKeyValue(e, "holdtime", "0.7");
    DispatchKeyValue(e, "spawnflags", "0");   // only the activator
    DispatchKeyValue(e, "message", " ");
    DispatchSpawn(e);
    g_GameText = e > 0 ? EntIndexToEntRef(e) : e;
    return e;
}

void ShowText(int viewer, int mode, const char[] text)
{
    if (mode == 1 && g_HasHudMsg)
    {
        // same channel every time with a hold longer than the refresh: each
        // message replaces the last in place (the sync helper clears first,
        // which flashed)
        SetHudTextParams(0.015, 0.02, 1.0, 255, 200, 120, 220, 0, 0.0, 0.0, 0.0);
        ShowHudText(viewer, 5, "%s", text);
    }
    else if (mode == 2)
    {
        int e = GetGameText();
        if (e == -1) return;
        DispatchKeyValue(e, "message", text);
        AcceptEntityInput(e, "Display", viewer, viewer);
    }
    else if (mode == 3)
        PrintHintText(viewer, "%s", text);
    else if (mode == 4)
        PrintCenterText(viewer, "%s", text);
}

int g_TestLeft;

public Action Cmd_Test(int args)
{
    g_TestLeft = 20;   // re-sent every second for 20 seconds
    CreateTimer(1.0, Timer_Test, _, TIMER_REPEAT | TIMER_FLAG_NO_MAPCHANGE);
    SendTest();
    PrintToServer("[markers] sending test lines 1-4 for 20s");
    return Plugin_Handled;
}

public Action Timer_Test(Handle t)
{
    if (--g_TestLeft <= 0)
        return Plugin_Stop;
    SendTest();
    return Plugin_Continue;
}

void SendTest()
{
    for (int c = 1; c <= MaxClients; c++)
    {
        if (!IsClientInGame(c) || IsFakeClient(c)) continue;
        SetHudTextParams(0.015, 0.02, 1.3, 255, 200, 120, 255, 0, 0.0, 0.0, 0.0);
        ShowSyncHudText(c, g_HudSync, "TEST 1 (HudMsg) top-left");
        int e = GetGameText();
        if (e != -1)
        {
            DispatchKeyValue(e, "y", "0.15");
            DispatchKeyValue(e, "holdtime", "1.3");
            DispatchKeyValue(e, "channel", "4");
            DispatchKeyValue(e, "message", "TEST 2 (game_text) top-left, lower");
            AcceptEntityInput(e, "Display", c, c);
            DispatchKeyValue(e, "y", "0.02");
            DispatchKeyValue(e, "holdtime", "0.7");
            DispatchKeyValue(e, "channel", "3");
        }
        PrintHintText(c, "TEST 3 (hint box)");
        PrintCenterText(c, "TEST 4 (centre text)");
    }
}

public void OnPluginEnd()
{
    for (int i = 1; i <= MaxClients; i++)
        RemoveSprite(i);
}

public void OnClientDisconnect(int client)
{
    RemoveSprite(client);
}

void OnGlowChanged(ConVar cv, const char[] oldv, const char[] newv)
{
    if (!cv.BoolValue)
        for (int i = 1; i <= MaxClients; i++)
            RemoveSprite(i);
}

public void Event_Spawn(Event e, const char[] name, bool dontBroadcast)
{
    int client = GetClientOfUserId(e.GetInt("userid"));
    // the spawn position is set after the event: attach a moment later
    if (client > 0)
        CreateTimer(0.2, Timer_Attach, GetClientUserId(client));
}

public void Event_Death(Event e, const char[] name, bool dontBroadcast)
{
    int client = GetClientOfUserId(e.GetInt("userid"));
    if (client > 0)
        RemoveSprite(client);
}

public Action Timer_Attach(Handle t, int userid)
{
    int client = GetClientOfUserId(userid);
    if (client > 0)
        EnsureSprite(client);
    return Plugin_Stop;
}

bool IsRealAlive(int c)
{
    return IsClientInGame(c) && !IsFakeClient(c) && IsPlayerAlive(c);
}

void RemoveSprite(int client)
{
    int e = EntRefToEntIndex(g_Sprite[client]);
    if (e != INVALID_ENT_REFERENCE && e > 0)
        AcceptEntityInput(e, "Kill");
    g_Sprite[client] = INVALID_ENT_REFERENCE;
}

void EnsureSprite(int client)
{
    if (!g_cvGlow.BoolValue || !IsRealAlive(client))
        return;
    int e = EntRefToEntIndex(g_Sprite[client]);
    if (e != INVALID_ENT_REFERENCE && e > 0)
        return;

    e = CreateEntityByName("env_sprite");
    if (e == -1)
        return;
    int col = (client - 1) % sizeof(g_Colors);
    char color[32];
    Format(color, sizeof(color), "%d %d %d", g_Colors[col][0], g_Colors[col][1], g_Colors[col][2]);
    DispatchKeyValue(e, "model", SPRITE_MDL);
    DispatchKeyValue(e, "rendermode", "5");      // additive; the glow modes fade out when occluded
    DispatchKeyValue(e, "rendercolor", color);
    DispatchKeyValue(e, "renderamt", "255");
    DispatchKeyValue(e, "scale", "0.35");
    DispatchKeyValue(e, "GlowProxySize", "4");
    DispatchKeyValue(e, "spawnflags", "1");      // start on
    DispatchKeyValue(e, "targetname", "teammate_marker");
    DispatchSpawn(e);

    // not parented: a child of an out-of-PVS player isn't sent, so the dot
    // vanished at range. Instead it's always networked and moved every frame.
    float pos[3];
    GetClientAbsOrigin(client, pos);
    pos[2] += HEAD_OFFSET;
    TeleportEntity(e, pos, NULL_VECTOR, NULL_VECTOR);
    SetEdictFlags(e, GetEdictFlags(e) | FL_EDICT_ALWAYS);
    AcceptEntityInput(e, "ShowSprite");

    SDKHook(e, SDKHook_SetTransmit, Hook_SpriteTransmit);
    g_Sprite[client] = EntIndexToEntRef(e);
}

public void OnGameFrame()
{
    static int frame;
    bool rescale = (++frame % 6) == 0;
    for (int c = 1; c <= MaxClients; c++)
    {
        int e = EntRefToEntIndex(g_Sprite[c]);
        if (e == INVALID_ENT_REFERENCE || e <= 0)
            continue;
        if (!IsRealAlive(c))
        {
            RemoveSprite(c);
            continue;
        }
        // clients draw other players ~0.1s in the past (interpolation) but a
        // teleported sprite at the newest position, so a running player's dot
        // drifted ahead of them: place it where their model is being drawn
        float pos[3], vel[3];
        GetClientAbsOrigin(c, pos);
        GetEntPropVector(c, Prop_Data, "m_vecAbsVelocity", vel);
        ScaleVector(vel, g_cvLag.FloatValue);
        SubtractVectors(pos, vel, pos);
        pos[2] += HEAD_OFFSET;
        TeleportEntity(e, pos, NULL_VECTOR, NULL_VECTOR);
        if (rescale)
        {
            // one sprite serves every viewer: size it for the farthest teammate
            // so it stays visible to them (closer ones just see a bigger dot)
            float far = 0.0, vpos[3];
            for (int v = 1; v <= MaxClients; v++)
            {
                if (v == c || !IsRealAlive(v)) continue;
                GetClientEyePosition(v, vpos);
                float d = GetVectorDistance(vpos, pos);
                if (d > far) far = d;
            }
            float scale = 0.25 * (far / 400.0);
            if (scale < 0.25) scale = 0.25;
            if (scale > 6.0) scale = 6.0;
            // only resend when it changes noticeably
            if (FloatAbs(scale - GetEntPropFloat(e, Prop_Send, "m_flSpriteScale")) > 0.05)
                SetEntPropFloat(e, Prop_Send, "m_flSpriteScale", scale);
        }
    }
}

// don't draw a player's own marker for them (only works if the engine still
// asks SetTransmit for always-networked entities - see markers_glow notes)
public Action Hook_SpriteTransmit(int entity, int viewer)
{
    if (viewer >= 1 && viewer <= MaxClients && EntRefToEntIndex(g_Sprite[viewer]) == entity)
        return Plugin_Handled;
    return Plugin_Continue;
}

void Direction(int viewer, const float target[3], char[] out, int len)
{
    float eye[3], ang[3], d[3];
    GetClientEyePosition(viewer, eye);
    GetClientEyeAngles(viewer, ang);
    SubtractVectors(target, eye, d);
    float yawTo = RadToDeg(ArcTangent2(d[1], d[0]));
    float rel = yawTo - ang[1];
    while (rel > 180.0) rel -= 360.0;
    while (rel < -180.0) rel += 360.0;
    // Source yaw grows counter-clockwise, so positive rel = to the viewer's left;
    // index = rel in 45-degree steps starting at -180 (behind)
    static const char dirs[][] = {"behind", "behind-R", "right", "ahead-R", "ahead", "ahead-L", "left", "behind-L"};
    int idx = RoundToNearest((rel + 180.0) / 45.0) % 8;
    strcopy(out, len, dirs[idx]);
    float up = target[2] - (eye[2] - 64.0);
    if (up > 120.0) StrCat(out, len, " up");
    else if (up < -120.0) StrCat(out, len, " down");
}

public Action Timer_Tick(Handle t)
{
    for (int c = 1; c <= MaxClients; c++)
        if (IsRealAlive(c))
            EnsureSprite(c);

    if (!g_cvHud.BoolValue)
        return Plugin_Continue;

    for (int viewer = 1; viewer <= MaxClients; viewer++)
    {
        if (!IsClientInGame(viewer) || IsFakeClient(viewer))
            continue;
        char text[512] = "", line[96], name[32], dir[40];
        float vpos[3];
        GetClientAbsOrigin(viewer, vpos);
        for (int o = 1; o <= MaxClients; o++)
        {
            // no team filter: co-op players sit in team 0 ("unassigned"), which hid everyone
            if (o == viewer || !IsClientInGame(o) || IsFakeClient(o))
                continue;
            GetClientName(o, name, 13);   // keep the line short
            if (!IsPlayerAlive(o))
            {
                Format(line, sizeof(line), "%s dead\n", name);
            }
            else
            {
                float opos[3];
                GetClientAbsOrigin(o, opos);
                int meters = RoundToNearest(GetVectorDistance(vpos, opos) * 0.0254);
                Direction(viewer, opos, dir, sizeof(dir));
                Format(line, sizeof(line), "%s %dm %s\n", name, meters, dir);
            }
            StrCat(text, sizeof(text), line);
        }
        if (text[0] == '\0')
            continue;
        ShowText(viewer, g_cvHudMode.IntValue, text);
    }
    return Plugin_Continue;
}

public Action Cmd_Status(int args)
{
    PrintToServer("[markers] glow=%d hud=%d HudMsg=%s", g_cvGlow.IntValue, g_cvHud.IntValue, g_HasHudMsg ? "yes" : "NO (HUD text unavailable)");
    for (int c = 1; c <= MaxClients; c++)
    {
        if (!IsClientInGame(c) || IsFakeClient(c))
            continue;
        int e = EntRefToEntIndex(g_Sprite[c]);
        PrintToServer("  %N: %s, sprite %d", c, IsPlayerAlive(c) ? "alive" : "dead", e == INVALID_ENT_REFERENCE ? -1 : e);
    }
    return Plugin_Handled;
}

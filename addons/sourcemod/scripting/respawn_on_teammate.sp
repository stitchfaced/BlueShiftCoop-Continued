/**
 * Respawn On Teammate
 *
 * SourceCoop respawns you at the map's last activated checkpoint. On the Blue
 * Shift campaign that can mean a long walk back, and on the Chapter 5 maps
 * (bs_c4m*) there are no checkpoints defined at all.
 *
 * This teleports a respawning player next to a randomly chosen living
 * teammate instead. If nobody is alive, it does nothing and SourceCoop's
 * normal checkpoint spawn stands.
 *
 * It deliberately ignores the FIRST spawn on a map, so SourceCoop's own
 * map-start placement (intro sequences, tram rides) is left alone. Only a
 * spawn that follows a death is redirected.
 *
 * Convars:
 *   respawn_on_teammate         1     on/off
 *   respawn_on_teammate_delay   0.2   seconds to wait after respawn
 *   respawn_on_teammate_offset  48.0  how far from the teammate to land
 *
 * Config is written to cfg/sourcemod/respawn_on_teammate.cfg on first run.
 */

#include <sourcemod>
#include <sdktools>

#pragma semicolon 1
#pragma newdecls required

#define PLUGIN_VERSION "1.0.0"

/* Standard Source standing player hull. Used for the clearance trace so we
   don't drop someone inside a wall next to their teammate. */
static const float HULL_MINS[3] = { -16.0, -16.0,  0.0 };
static const float HULL_MAXS[3] = {  16.0,  16.0, 72.0 };

ConVar g_cvEnabled;
ConVar g_cvDelay;
ConVar g_cvOffset;

bool g_bHasDied[MAXPLAYERS + 1];

public Plugin myinfo =
{
    name        = "Respawn On Teammate",
    author      = "stitch",
    description = "Teleports respawning players to a living teammate instead of the checkpoint.",
    version     = PLUGIN_VERSION,
    url         = ""
};

public void OnPluginStart()
{
    g_cvEnabled = CreateConVar("respawn_on_teammate", "1",
        "Teleport respawning players to a living teammate.", _, true, 0.0, true, 1.0);
    g_cvDelay = CreateConVar("respawn_on_teammate_delay", "0.2",
        "Delay in seconds before teleporting, so SourceCoop finishes spawning first.", _, true, 0.0, true, 5.0);
    g_cvOffset = CreateConVar("respawn_on_teammate_offset", "48.0",
        "How far from the teammate to place the respawning player.", _, true, 0.0, true, 256.0);

    HookEvent("player_death", Event_PlayerDeath, EventHookMode_Post);
    HookEvent("player_spawn", Event_PlayerSpawn, EventHookMode_Post);

    AutoExecConfig(true, "respawn_on_teammate");
}

public void OnMapStart()
{
    for (int i = 1; i <= MAXPLAYERS; i++)
    {
        g_bHasDied[i] = false;
    }
}

public void OnClientDisconnect(int client)
{
    if (client >= 1 && client <= MAXPLAYERS)
    {
        g_bHasDied[client] = false;
    }
}

public void Event_PlayerDeath(Event event, const char[] name, bool dontBroadcast)
{
    int client = GetClientOfUserId(event.GetInt("userid"));
    if (client >= 1 && client <= MAXPLAYERS)
    {
        g_bHasDied[client] = true;
    }
}

public void Event_PlayerSpawn(Event event, const char[] name, bool dontBroadcast)
{
    if (!g_cvEnabled.BoolValue)
    {
        return;
    }

    int client = GetClientOfUserId(event.GetInt("userid"));
    if (client < 1 || client > MAXPLAYERS || !IsClientInGame(client))
    {
        return;
    }

    /* First spawn of the map - leave SourceCoop's placement untouched. */
    if (!g_bHasDied[client])
    {
        return;
    }
    g_bHasDied[client] = false;

    float delay = g_cvDelay.FloatValue;
    if (delay <= 0.0)
    {
        delay = 0.1;
    }

    CreateTimer(delay, Timer_Teleport, GetClientUserId(client), TIMER_FLAG_NO_MAPCHANGE);
}

public Action Timer_Teleport(Handle timer, int userid)
{
    int client = GetClientOfUserId(userid);
    if (client < 1 || !IsClientInGame(client) || !IsPlayerAlive(client))
    {
        return Plugin_Stop;
    }

    int target = PickLivingTeammate(client);
    if (target < 1)
    {
        /* Nobody alive to spawn on - keep the checkpoint spawn. */
        return Plugin_Stop;
    }

    float base[3], ang[3], dest[3];
    GetClientAbsOrigin(target, base);
    GetClientEyeAngles(target, ang);
    ang[0] = 0.0;
    ang[2] = 0.0;

    if (!FindClearSpot(client, base, g_cvOffset.FloatValue, dest))
    {
        /* No clear ring position; land on the teammate and let
           srccoop_addon_unstuck push us out. */
        dest[0] = base[0];
        dest[1] = base[1];
        dest[2] = base[2] + 8.0;
    }

    TeleportEntity(client, dest, ang, NULL_VECTOR);
    return Plugin_Stop;
}

int PickLivingTeammate(int client)
{
    int candidates[MAXPLAYERS + 1];
    int count = 0;

    for (int i = 1; i <= MaxClients; i++)
    {
        if (i == client || !IsClientInGame(i) || IsFakeClient(i) || !IsPlayerAlive(i))
        {
            continue;
        }
        candidates[count++] = i;
    }

    if (count == 0)
    {
        return -1;
    }
    return candidates[GetRandomInt(0, count - 1)];
}

/* Walk a ring of 8 points around the teammate and return the first that can
   fit a player hull without hitting world geometry. */
bool FindClearSpot(int client, const float center[3], float dist, float out[3])
{
    for (int i = 0; i < 8; i++)
    {
        float yaw = DegToRad(45.0 * float(i));
        float test[3];
        test[0] = center[0] + (dist * Cosine(yaw));
        test[1] = center[1] + (dist * Sine(yaw));
        test[2] = center[2] + 8.0;

        TR_TraceHullFilter(test, test, HULL_MINS, HULL_MAXS, MASK_PLAYERSOLID, TraceFilter_IgnoreSelf, client);
        bool hit = TR_DidHit();

        if (!hit)
        {
            out[0] = test[0];
            out[1] = test[1];
            out[2] = test[2];
            return true;
        }
    }
    return false;
}

public bool TraceFilter_IgnoreSelf(int entity, int contentsMask, any data)
{
    return entity != data;
}

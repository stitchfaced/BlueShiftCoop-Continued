// Throwaway test helpers for verifying configs/plugins over RCON (ent_fire /
// ent_dump need a player client and do nothing from the server console).
#include <sourcemod>
#include <sdktools>

#pragma semicolon 1
#pragma newdecls required

public void OnPluginStart()
{
    RegServerCmd("bst_fire", Cmd_Fire, "bst_fire <targetname> <input> [param] - no activator");
    RegServerCmd("bst_firekill", Cmd_FireKill, "bst_firekill <target> <input> <killname> [killname...] - fire, then kill named ents the same tick");
    RegServerCmd("bst_use", Cmd_Use, "bst_use <entity name> <player name substring> - player Uses the entity");
    RegServerCmd("bst_give", Cmd_Give, "bst_give <player name substring> <classname>");
    RegServerCmd("bst_bring", Cmd_Bring, "bst_bring <player to move> <player to move them onto> - same tick");
    RegServerCmd("bst_fireid", Cmd_FireId, "bst_fireid <hammerid> <input> [param]");
    RegServerCmd("bst_tpent", Cmd_TpEnt, "bst_tpent <name> <x> <y> <z> <pitch> <yaw> <roll> - move an entity");
    RegServerCmd("bst_tp", Cmd_Tp, "bst_tp <player name substring> <x> <y> <z>");
    RegServerCmd("bst_kv", Cmd_Kv, "bst_kv <targetname|classname> <datamap field> - print field");
}

// Iterates every entity, including edict-less logical ones (logic_relay,
// math_counter, logic_timer) that live above the edict range as references.
int FindNamed(int start, const char[] name)
{
    char buf[128];
    int ent = start;
    while ((ent = FindEntityByClassname(ent, "*")) != -1)
    {
        GetEntPropString(ent, Prop_Data, "m_iName", buf, sizeof(buf));
        if (StrEqual(buf, name, false))
            return ent;
        GetEntityClassname(ent, buf, sizeof(buf));
        if (StrEqual(buf, name, false))
            return ent;
    }
    return -1;
}

public Action Cmd_Fire(int args)
{
    char name[128], input[64], param[128];
    GetCmdArg(1, name, sizeof(name));
    GetCmdArg(2, input, sizeof(input));
    GetCmdArg(3, param, sizeof(param));
    int n = 0, ent = -1;
    while ((ent = FindNamed(ent, name)) != -1)
    {
        if (param[0] != '\0')
            SetVariantString(param);
        AcceptEntityInput(ent, input, -1, -1);
        n++;
    }
    PrintToServer("bst_fire: %s -> %s(%s) on %d entities", name, input, param, n);
    return Plugin_Handled;
}

public Action Cmd_Kv(int args)
{
    char name[128], field[64], val[256], cls[64];
    GetCmdArg(1, name, sizeof(name));
    GetCmdArg(2, field, sizeof(field));
    int ent = -1, n = 0;
    while ((ent = FindNamed(ent, name)) != -1)
    {
        GetEntityClassname(ent, cls, sizeof(cls));
        if (ent >= 1 && ent <= MaxClients && IsClientInGame(ent))
        {
            GetClientName(ent, cls, sizeof(cls));
            Format(cls, sizeof(cls), "player '%s'%s", cls, IsPlayerAlive(ent) ? "" : " (dead)");
        }
        PropFieldType type;
        if (FindDataMapInfo(ent, field, type) == -1)
        {
            PrintToServer("bst_kv: #%d %s has no field %s", ent, cls, field);
        }
        else if (type == PropField_String || type == PropField_String_T)
        {
            GetEntPropString(ent, Prop_Data, field, val, sizeof(val));
            PrintToServer("bst_kv: #%d %s %s = \"%s\"", ent, cls, field, val);
        }
        else if (type == PropField_Entity)
        {
            int h = GetEntPropEnt(ent, Prop_Data, field);
            char hn[128] = "";
            if (h > 0 && IsValidEntity(h))
                GetEntPropString(h, Prop_Data, "m_iName", hn, sizeof(hn));
            PrintToServer("bst_kv: #%d %s %s = #%d \"%s\"", ent, cls, field, h, hn);
        }
        else if (type == PropField_Vector)
        {
            float v[3];
            GetEntPropVector(ent, Prop_Data, field, v);
            PrintToServer("bst_kv: #%d %s %s = %.1f %.1f %.1f", ent, cls, field, v[0], v[1], v[2]);
        }
        else if (type == PropField_Float || type == PropField_Variant)
        {
            PrintToServer("bst_kv: #%d %s %s = %f", ent, cls, field, GetEntPropFloat(ent, Prop_Data, field));
        }
        else
        {
            PrintToServer("bst_kv: #%d %s %s = %d", ent, cls, field, GetEntProp(ent, Prop_Data, field));
        }
        n++;
    }
    if (n == 0)
        PrintToServer("bst_kv: no entity named %s", name);
    return Plugin_Handled;
}

public Action Cmd_FireKill(int args)
{
    char name[128], input[64], kill[128];
    GetCmdArg(1, name, sizeof(name));
    GetCmdArg(2, input, sizeof(input));
    int n = 0, ent = -1;
    while ((ent = FindNamed(ent, name)) != -1)
    {
        AcceptEntityInput(ent, input, -1, -1);
        n++;
    }
    int killed = 0;
    for (int a = 3; a <= args; a++)
    {
        GetCmdArg(a, kill, sizeof(kill));
        ent = -1;
        while ((ent = FindNamed(ent, kill)) != -1)
        {
            AcceptEntityInput(ent, "Kill");
            killed++;
        }
    }
    PrintToServer("bst_firekill: %s -> %s on %d, killed %d", name, input, n, killed);
    return Plugin_Handled;
}

public Action Cmd_Tp(int args)
{
    char who[64], buf[64], pname[64];
    GetCmdArg(1, who, sizeof(who));
    float pos[3];
    for (int i = 0; i < 3; i++) { GetCmdArg(2 + i, buf, sizeof(buf)); pos[i] = StringToFloat(buf); }
    for (int c = 1; c <= MaxClients; c++)
    {
        if (!IsClientInGame(c) || IsFakeClient(c) || !IsPlayerAlive(c)) continue;
        GetClientName(c, pname, sizeof(pname));
        if (StrContains(pname, who, false) != -1)
        {
            TeleportEntity(c, pos, NULL_VECTOR, view_as<float>({0.0, 0.0, 0.0}));
            PrintToServer("bst_tp: %s -> %.0f %.0f %.0f", pname, pos[0], pos[1], pos[2]);
        }
    }
    return Plugin_Handled;
}

public Action Cmd_Use(int args)
{
    char name[128], who[64], pname[64];
    GetCmdArg(1, name, sizeof(name));
    GetCmdArg(2, who, sizeof(who));
    int ent = FindNamed(-1, name);
    for (int c = 1; c <= MaxClients; c++)
    {
        if (!IsClientInGame(c) || IsFakeClient(c) || !IsPlayerAlive(c)) continue;
        GetClientName(c, pname, sizeof(pname));
        if (ent != -1 && StrContains(pname, who, false) != -1)
        {
            AcceptEntityInput(ent, "Use", c, c);
            PrintToServer("bst_use: %s used %s", pname, name);
            return Plugin_Handled;
        }
    }
    PrintToServer("bst_use: no match (ent %d)", ent);
    return Plugin_Handled;
}

public Action Cmd_Give(int args)
{
    char who[64], cls[64], pname[64];
    GetCmdArg(1, who, sizeof(who));
    GetCmdArg(2, cls, sizeof(cls));
    for (int c = 1; c <= MaxClients; c++)
    {
        if (!IsClientInGame(c) || IsFakeClient(c) || !IsPlayerAlive(c)) continue;
        GetClientName(c, pname, sizeof(pname));
        if (StrContains(pname, who, false) != -1)
        {
            int ent = GivePlayerItem(c, cls);
            PrintToServer("bst_give: %s <- %s (ent %d)", pname, cls, ent);
        }
    }
    return Plugin_Handled;
}

int FindPlayer(const char[] who)
{
    char pname[64];
    for (int c = 1; c <= MaxClients; c++)
    {
        if (!IsClientInGame(c) || IsFakeClient(c) || !IsPlayerAlive(c)) continue;
        GetClientName(c, pname, sizeof(pname));
        if (StrContains(pname, who, false) != -1) return c;
    }
    return -1;
}

public Action Cmd_Bring(int args)
{
    char a[64], b[64];
    GetCmdArg(1, a, sizeof(a));
    GetCmdArg(2, b, sizeof(b));
    int ca = FindPlayer(a), cb = FindPlayer(b);
    if (ca < 1 || cb < 1) { PrintToServer("bst_bring: no match"); return Plugin_Handled; }
    float pos[3], vel[3];
    GetClientAbsOrigin(cb, pos);
    GetEntPropVector(cb, Prop_Data, "m_vecAbsVelocity", vel);
    pos[2] += 4.0;
    TeleportEntity(ca, pos, NULL_VECTOR, vel);
    PrintToServer("bst_bring: %N -> %N at %.0f %.0f %.0f", ca, cb, pos[0], pos[1], pos[2]);
    return Plugin_Handled;
}

public Action Cmd_FireId(int args)
{
    char id[32], input[64], param[128];
    GetCmdArg(1, id, sizeof(id));
    GetCmdArg(2, input, sizeof(input));
    GetCmdArg(3, param, sizeof(param));
    int want = StringToInt(id), n = 0, ent = -1;
    while ((ent = FindEntityByClassname(ent, "*")) != -1)
    {
        if (HasEntProp(ent, Prop_Data, "m_iHammerID") && GetEntProp(ent, Prop_Data, "m_iHammerID") == want)
        {
            if (param[0] != '\0') SetVariantString(param);
            AcceptEntityInput(ent, input, -1, -1);
            n++;
        }
    }
    PrintToServer("bst_fireid: #%d -> %s(%s) on %d", want, input, param, n);
    return Plugin_Handled;
}

public Action Cmd_TpEnt(int args)
{
    char name[128], buf[32];
    GetCmdArg(1, name, sizeof(name));
    float pos[3], ang[3];
    for (int i = 0; i < 3; i++) { GetCmdArg(2 + i, buf, sizeof(buf)); pos[i] = StringToFloat(buf); }
    for (int i = 0; i < 3; i++) { GetCmdArg(5 + i, buf, sizeof(buf)); ang[i] = StringToFloat(buf); }
    int ent = FindNamed(-1, name);
    if (ent == -1) { PrintToServer("bst_tpent: no entity %s", name); return Plugin_Handled; }
    TeleportEntity(ent, pos, ang, NULL_VECTOR);
    PrintToServer("bst_tpent: %s -> %.1f %.1f %.1f / %.0f %.0f %.0f", name, pos[0], pos[1], pos[2], ang[0], ang[1], ang[2]);
    return Plugin_Handled;
}

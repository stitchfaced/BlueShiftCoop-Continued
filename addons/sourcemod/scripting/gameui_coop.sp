/**
 * game_ui for co-op
 *
 * Black Mesa: Blue Shift drives its Captive Freight train, the chapter 5
 * railgun / demolisher turrets, the security camera consoles and several Xen
 * puzzle interfaces through game_ui. On this multiplayer server game_ui does
 * not work: the train would not move at all, which in turn blocked Ronny's
 * rescue and Los's keypad door on bs_c3m1b.
 *
 * This plugin takes over every game_ui. Its Activate / Deactivate inputs are
 * handled here instead of by the engine; the activating player becomes that
 * game_ui's user and their key presses fire the game_ui's own outputs
 * (PressedForward, UnpressedBack, PressedAttack, ...). PlayerOn / PlayerOff
 * fire on activate / deactivate. Each map's existing I/O therefore runs
 * unchanged, bound to the right player.
 *
 * The user is the input's activator (the player who pressed the button,
 * entered the trigger or took the turret). If the activator is not a player,
 * the living player nearest the calling entity is used instead.
 *
 * Spawnflags honoured, as in the engine's game_ui:
 *   32   Freeze player     FL_ATCONTROLS while in use
 *   64   Hide weapon       gun hidden and unable to fire; attack drives the UI
 *   128  +USE deactivates
 *   256  Jump deactivates
 * FieldOfView is not implemented (every Blue Shift game_ui uses -1, off).
 *
 * One deliberate difference from the engine: on deactivate, any UI button
 * still held fires its Unpressed output, so leaving the train with W held
 * cannot leave the throttle timer running.
 *
 * Hooks CBaseEntity::AcceptInput using SourceCoop's gamedata (srccoop.games),
 * which is already patched for -game bshift.
 *
 * Convars:
 *   gameui_coop        1  on/off (0 = engine game_ui behaviour)
 *   gameui_coop_debug  0  log activations and every output fired
 *
 * Config is written to cfg/sourcemod/gameui_coop.cfg on first run.
 */

#include <sourcemod>
#include <sdktools>
#include <dhooks>

#pragma semicolon 1
#pragma newdecls required

#define PLUGIN_VERSION "1.1.0"

#define SF_GAMEUI_FREEZE_PLAYER     32
#define SF_GAMEUI_HIDE_WEAPON       64
#define SF_GAMEUI_USE_DEACTIVATES   128
#define SF_GAMEUI_JUMP_DEACTIVATES  256

/* Buttons the engine's game_ui reports, and the output pair for each. */
static const int UI_BUTTONS[] = { IN_MOVELEFT, IN_MOVERIGHT, IN_FORWARD, IN_BACK, IN_ATTACK, IN_ATTACK2 };
static const char UI_PRESSED[][] = {
    "PressedMoveLeft", "PressedMoveRight", "PressedForward",
    "PressedBack", "PressedAttack", "PressedAttack2"
};
static const char UI_UNPRESSED[][] = {
    "UnpressedMoveLeft", "UnpressedMoveRight", "UnpressedForward",
    "UnpressedBack", "UnpressedAttack", "UnpressedAttack2"
};

DynamicHook g_hkAcceptInput;
ConVar g_cvEnabled;
ConVar g_cvDebug;

/* Per client: the game_ui (entity reference) they are using, the buttons
   seen on their last command, and whether we set FL_ATCONTROLS on them. */
int g_iUI[MAXPLAYERS + 1];
int g_iLastButtons[MAXPLAYERS + 1];
bool g_bFrozen[MAXPLAYERS + 1];
int g_iHiddenWeapon[MAXPLAYERS + 1];   // entity ref of the weapon we made unable to fire, or INVALID_ENT_REFERENCE
bool g_bWeaponHidden[MAXPLAYERS + 1];

#define HIDEHUD_WEAPONSELECTION (1 << 0)

public Plugin myinfo =
{
    name        = "game_ui for co-op",
    author      = "stitch",
    description = "Binds game_ui to the activating player in multiplayer and fires its outputs from their input.",
    version     = PLUGIN_VERSION,
    url         = ""
};

public void OnPluginStart()
{
    GameData gd = new GameData("srccoop.games");
    if (gd == null)
    {
        SetFailState("gamedata srccoop.games not found");
    }
    g_hkAcceptInput = DynamicHook.FromConf(gd, "CBaseEntity::AcceptInput");
    delete gd;
    if (g_hkAcceptInput == null)
    {
        SetFailState("CBaseEntity::AcceptInput missing from srccoop.games");
    }

    g_cvEnabled = CreateConVar("gameui_coop", "1",
        "Handle game_ui in co-op (0 = engine behaviour).", _, true, 0.0, true, 1.0);
    g_cvDebug = CreateConVar("gameui_coop_debug", "0",
        "Log game_ui activations and every output fired.", _, true, 0.0, true, 1.0);
    g_cvEnabled.AddChangeHook(OnEnabledChanged);

    HookEvent("player_death", Event_PlayerDeath, EventHookMode_Post);

    RegAdminCmd("sm_gameui", Cmd_Status, ADMFLAG_GENERIC, "List game_ui entities currently in use and by whom.");

    ResetAll();

    /* Late load: hook the game_ui entities that already exist. */
    int ent = -1;
    while ((ent = FindEntityByClassname(ent, "game_ui")) != -1)
    {
        HookUI(ent);
    }

    AutoExecConfig(true, "gameui_coop");
}

public void OnMapStart()
{
    ResetAll();
}

public void OnMapEnd()
{
    ResetAll();
}

void ResetAll()
{
    for (int i = 0; i <= MAXPLAYERS; i++)
    {
        g_iUI[i] = INVALID_ENT_REFERENCE;
        g_iLastButtons[i] = 0;
        g_bFrozen[i] = false;
        g_iHiddenWeapon[i] = INVALID_ENT_REFERENCE;
        g_bWeaponHidden[i] = false;
    }
}

public void OnEnabledChanged(ConVar convar, const char[] oldValue, const char[] newValue)
{
    if (!convar.BoolValue)
    {
        for (int i = 1; i <= MaxClients; i++)
        {
            if (g_iUI[i] != INVALID_ENT_REFERENCE)
            {
                Deactivate(i);
            }
        }
    }
}

public void OnEntityCreated(int entity, const char[] classname)
{
    if (StrEqual(classname, "game_ui", false))
    {
        HookUI(entity);
    }
}

public void OnEntityDestroyed(int entity)
{
    if (entity <= MaxClients || !IsValidEntity(entity))
    {
        return;
    }
    int ref = EntIndexToEntRef(entity);
    for (int i = 1; i <= MaxClients; i++)
    {
        if (g_iUI[i] == ref)
        {
            /* The game_ui is going away; no outputs to fire, just let go. */
            Release(i);
        }
    }
}

void HookUI(int ui)
{
    g_hkAcceptInput.HookEntity(Hook_Pre, ui, Hook_AcceptInput);
}

public MRESReturn Hook_AcceptInput(int ui, DHookReturn hReturn, DHookParam hParams)
{
    if (!g_cvEnabled.BoolValue)
    {
        return MRES_Ignored;
    }

    char input[32];
    hParams.GetString(1, input, sizeof(input));

    if (StrEqual(input, "Activate", false))
    {
        int activator = hParams.IsNull(2) ? -1 : hParams.Get(2);
        int caller = hParams.IsNull(3) ? -1 : hParams.Get(3);
        int client = ResolvePlayer(ui, activator, caller);
        if (client > 0)
        {
            Activate(ui, client);
        }
        else
        {
            Debug("%s: Activate with no living player to bind", UIName(ui));
        }
    }
    else if (StrEqual(input, "Deactivate", false))
    {
        int client = UserOf(ui);
        if (client > 0)
        {
            Deactivate(client);
        }
    }
    else
    {
        return MRES_Ignored;
    }

    hReturn.Value = true;
    return MRES_Supercede;
}

int ResolvePlayer(int ui, int activator, int caller)
{
    if (IsLivingPlayer(activator))
    {
        return activator;
    }
    int from = (caller > 0 && IsValidEntity(caller)) ? caller : ui;
    return NearestLivingPlayer(from);
}

void Activate(int ui, int client)
{
    int current = UserOf(ui);
    if (current > 0)
    {
        /* Already in use - the engine ignores a second activation too. */
        if (current != client)
        {
            Debug("%s: %N tried to activate, already used by %N", UIName(ui), client, current);
        }
        return;
    }
    if (g_iUI[client] != INVALID_ENT_REFERENCE)
    {
        Deactivate(client);
    }

    g_iUI[client] = EntIndexToEntRef(ui);
    g_iLastButtons[client] = GetClientButtons(client);

    if (GetEntProp(ui, Prop_Data, "m_spawnflags") & SF_GAMEUI_FREEZE_PLAYER)
    {
        SetEntityFlags(client, GetEntityFlags(client) | FL_ATCONTROLS);
        g_bFrozen[client] = true;
    }

    if (GetEntProp(ui, Prop_Data, "m_spawnflags") & SF_GAMEUI_HIDE_WEAPON)
    {
        HideWeapon(client);
    }

    Debug("%s: activated by %N", UIName(ui), client);
    Fire(ui, "PlayerOn", client);
}

void Deactivate(int client)
{
    int ui = EntRefToEntIndex(g_iUI[client]);
    int held = g_iLastButtons[client];
    Release(client);

    if (ui == INVALID_ENT_REFERENCE)
    {
        return;
    }
    for (int i = 0; i < sizeof(UI_BUTTONS); i++)
    {
        if (held & UI_BUTTONS[i])
        {
            Fire(ui, UI_UNPRESSED[i], client);
        }
    }
    Debug("%s: deactivated (%N)", UIName(ui), client);
    Fire(ui, "PlayerOff", client);
}

/* Forget the client's game_ui and undo our freeze, without firing outputs. */
void Release(int client)
{
    g_iUI[client] = INVALID_ENT_REFERENCE;
    g_iLastButtons[client] = 0;
    if (g_bWeaponHidden[client])
    {
        RestoreWeapon(client);
    }
    if (g_bFrozen[client])
    {
        g_bFrozen[client] = false;
        if (IsClientInGame(client))
        {
            SetEntityFlags(client, GetEntityFlags(client) & ~FL_ATCONTROLS);
        }
    }
}

/* The engine's game_ui holsters the weapon for "hide weapon" UIs. Stripping
   IN_ATTACK on the server is not enough: the client still predicts the shot
   from its own key press. Pushing m_flNextPrimary/SecondaryAttack far ahead is
   networked to the owner, so neither side fires; the viewmodel and weapon
   selection are hidden for the duration. */
void HideWeapon(int client)
{
    int w = GetEntPropEnt(client, Prop_Send, "m_hActiveWeapon");
    if (w > MaxClients && IsValidEntity(w) && HasEntProp(w, Prop_Send, "m_flNextPrimaryAttack"))
    {
        float never = GetGameTime() + 100000.0;
        SetEntPropFloat(w, Prop_Send, "m_flNextPrimaryAttack", never);
        if (HasEntProp(w, Prop_Send, "m_flNextSecondaryAttack"))
        {
            SetEntPropFloat(w, Prop_Send, "m_flNextSecondaryAttack", never);
        }
        g_iHiddenWeapon[client] = EntIndexToEntRef(w);
    }
    if (HasEntProp(client, Prop_Send, "m_bDrawViewmodel"))
    {
        SetEntProp(client, Prop_Send, "m_bDrawViewmodel", 0);
    }
    if (HasEntProp(client, Prop_Send, "m_iHideHUD"))
    {
        SetEntProp(client, Prop_Send, "m_iHideHUD", GetEntProp(client, Prop_Send, "m_iHideHUD") | HIDEHUD_WEAPONSELECTION);
    }
    g_bWeaponHidden[client] = true;
}

void RestoreWeapon(int client)
{
    g_bWeaponHidden[client] = false;
    int w = EntRefToEntIndex(g_iHiddenWeapon[client]);
    g_iHiddenWeapon[client] = INVALID_ENT_REFERENCE;
    if (w != INVALID_ENT_REFERENCE && IsValidEntity(w))
    {
        SetEntPropFloat(w, Prop_Send, "m_flNextPrimaryAttack", GetGameTime());
        if (HasEntProp(w, Prop_Send, "m_flNextSecondaryAttack"))
        {
            SetEntPropFloat(w, Prop_Send, "m_flNextSecondaryAttack", GetGameTime());
        }
    }
    if (!IsClientInGame(client))
    {
        return;
    }
    if (HasEntProp(client, Prop_Send, "m_bDrawViewmodel"))
    {
        SetEntProp(client, Prop_Send, "m_bDrawViewmodel", 1);
    }
    if (HasEntProp(client, Prop_Send, "m_iHideHUD"))
    {
        SetEntProp(client, Prop_Send, "m_iHideHUD", GetEntProp(client, Prop_Send, "m_iHideHUD") & ~HIDEHUD_WEAPONSELECTION);
    }
}

public Action OnPlayerRunCmd(int client, int &buttons, int &impulse, float vel[3], float angles[3],
    int &weapon, int &subtype, int &cmdnum, int &tickcount, int &seed, int mouse[2])
{
    if (g_iUI[client] == INVALID_ENT_REFERENCE)
    {
        return Plugin_Continue;
    }
    int ui = EntRefToEntIndex(g_iUI[client]);
    if (ui == INVALID_ENT_REFERENCE)
    {
        Release(client);
        return Plugin_Continue;
    }

    int sf = GetEntProp(ui, Prop_Data, "m_spawnflags");
    int pressed = buttons & ~g_iLastButtons[client];

    if (((sf & SF_GAMEUI_USE_DEACTIVATES) && (pressed & IN_USE))
        || ((sf & SF_GAMEUI_JUMP_DEACTIVATES) && (pressed & IN_JUMP)))
    {
        Deactivate(client);
        return Plugin_Continue;
    }

    int released = g_iLastButtons[client] & ~buttons;
    for (int i = 0; i < sizeof(UI_BUTTONS); i++)
    {
        if (pressed & UI_BUTTONS[i])
        {
            Fire(ui, UI_PRESSED[i], client);
        }
        else if (released & UI_BUTTONS[i])
        {
            Fire(ui, UI_UNPRESSED[i], client);
        }
    }
    g_iLastButtons[client] = buttons;

    if ((sf & SF_GAMEUI_HIDE_WEAPON) && ((buttons & (IN_ATTACK | IN_ATTACK2)) || weapon != 0))
    {
        buttons &= ~(IN_ATTACK | IN_ATTACK2);
        weapon = 0;   // no switching to a weapon that could fire
        return Plugin_Changed;
    }
    return Plugin_Continue;
}

public void Event_PlayerDeath(Event event, const char[] name, bool dontBroadcast)
{
    int client = GetClientOfUserId(event.GetInt("userid"));
    if (client >= 1 && client <= MaxClients && g_iUI[client] != INVALID_ENT_REFERENCE)
    {
        Deactivate(client);
    }
}

public void OnClientDisconnect(int client)
{
    if (g_iUI[client] != INVALID_ENT_REFERENCE)
    {
        Deactivate(client);
    }
    Release(client);
}

public Action Cmd_Status(int client, int args)
{
    int n = 0;
    for (int i = 1; i <= MaxClients; i++)
    {
        int ui = EntRefToEntIndex(g_iUI[i]);
        if (ui != INVALID_ENT_REFERENCE)
        {
            ReplyToCommand(client, "[gameui] %s used by %N", UIName(ui), i);
            n++;
        }
    }
    if (n == 0)
    {
        ReplyToCommand(client, "[gameui] no game_ui in use");
    }
    return Plugin_Handled;
}

int UserOf(int ui)
{
    int ref = EntIndexToEntRef(ui);
    for (int i = 1; i <= MaxClients; i++)
    {
        if (g_iUI[i] == ref)
        {
            return i;
        }
    }
    return -1;
}

bool IsLivingPlayer(int client)
{
    return client >= 1 && client <= MaxClients && IsClientInGame(client) && IsPlayerAlive(client);
}

int NearestLivingPlayer(int entity)
{
    float from[3], pos[3];
    GetEntPropVector(entity, Prop_Data, "m_vecAbsOrigin", from);

    int best = -1;
    float bestDist = -1.0;
    for (int i = 1; i <= MaxClients; i++)
    {
        if (!IsLivingPlayer(i) || IsFakeClient(i))
        {
            continue;
        }
        GetClientAbsOrigin(i, pos);
        float d = GetVectorDistance(from, pos, true);
        if (best == -1 || d < bestDist)
        {
            best = i;
            bestDist = d;
        }
    }
    return best;
}

void Fire(int ui, const char[] output, int client)
{
    Debug("%s: %s (%N)", UIName(ui), output, client);
    FireEntityOutput(ui, output, client, 0.0);
}

char[] UIName(int ui)
{
    char name[64];
    GetEntPropString(ui, Prop_Data, "m_iName", name, sizeof(name));
    if (name[0] == '\0')
    {
        Format(name, sizeof(name), "game_ui #%d", ui);
    }
    return name;
}

void Debug(const char[] fmt, any ...)
{
    if (!g_cvDebug.BoolValue)
    {
        return;
    }
    char msg[256];
    VFormat(msg, sizeof(msg), fmt, 2);
    LogMessage("%s", msg);
}

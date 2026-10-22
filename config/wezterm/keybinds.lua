-- =============================================================================
-- WezTerm Modular Keybindings (~/.config/wezterm/keybinds.lua)
-- Keeps default OS shortcuts intact while adding multiplexer leader bindings.
-- Leader Key: Ctrl + q (2000ms timeout)
-- =============================================================================

local wezterm = require("wezterm")
local act = wezterm.action

local M = {}

M.leader = { key = "q", mods = "CTRL", timeout_milliseconds = 2000 }

M.keys = {
  -- Pane splitting (Leader + - / |)
  { key = "-", mods = "LEADER", action = act.SplitVertical({ domain = "CurrentPaneDomain" }) },
  { key = "|", mods = "LEADER|SHIFT", action = act.SplitHorizontal({ domain = "CurrentPaneDomain" }) },
  { key = "\\", mods = "LEADER", action = act.SplitHorizontal({ domain = "CurrentPaneDomain" }) },

  -- Pane navigation (Leader + h/j/k/l)
  { key = "h", mods = "LEADER", action = act.ActivatePaneDirection("Left") },
  { key = "j", mods = "LEADER", action = act.ActivatePaneDirection("Down") },
  { key = "k", mods = "LEADER", action = act.ActivatePaneDirection("Up") },
  { key = "l", mods = "LEADER", action = act.ActivatePaneDirection("Right") },

  -- Pane zoom & close
  { key = "z", mods = "LEADER", action = act.TogglePaneZoomState },
  { key = "x", mods = "LEADER", action = act.CloseCurrentPane({ confirm = true }) },

  -- Tab management
  { key = "c", mods = "LEADER", action = act.SpawnTab("CurrentPaneDomain") },
  { key = "n", mods = "LEADER", action = act.ActivateTabRelative(1) },
  { key = "p", mods = "LEADER", action = act.ActivateTabRelative(-1) },
  { key = "w", mods = "LEADER", action = act.ShowLauncherArgs({ flags = "FUZZY|TABS|LAUNCH_MENU_ITEMS|WORKSPACES" }) },

  -- Copy mode & QuickSelect
  { key = "[", mods = "LEADER", action = act.ActivateCopyMode },
  { key = " ", mods = "LEADER", action = act.QuickSelect },

  -- Reload configuration
  { key = "r", mods = "LEADER", action = act.ReloadConfiguration },
}

M.key_tables = {}

return M

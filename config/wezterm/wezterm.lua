-- =============================================================================
-- WezTerm Configuration (~/.config/wezterm/wezterm.lua)
-- Author: Youhei Yamada (@sun-flat-yamada)
-- Theme: Dark 2026 (Harmonized with VS Code, Windows Terminal & Starship)
-- =============================================================================

local wezterm = require("wezterm")
local config = wezterm.config_builder()

config.automatically_reload_config = true

----------------------------------------------------
-- Rendering & Performance (2026 Best Practices)
----------------------------------------------------
config.front_end = "WebGpu"
config.webgpu_power_preference = "HighPerformance"
config.max_fps = 120
config.animation_fps = 60
config.scrollback_lines = 10000

----------------------------------------------------
-- Default Terminal & Launch Menu
----------------------------------------------------
local is_windows = wezterm.target_triple:find("windows") ~= nil

if is_windows then
  config.default_prog = { "pwsh.exe", "-NoLogo" }
  config.launch_menu = {
    { label = "PowerShell 7", args = { "pwsh.exe", "-NoLogo" } },
    { label = "WSL2 (Ubuntu)", args = { "wsl.exe", "-d", "Ubuntu" } },
    { label = "Windows PowerShell 5.1", args = { "powershell.exe", "-NoLogo" } },
    { label = "Command Prompt", args = { "cmd.exe" } },
  }
end

----------------------------------------------------
-- Font & Typography
----------------------------------------------------
config.font = wezterm.font_with_fallback({
  "HackGen Console NF",
  "HackGen Console NF Regular",
  "Hack Nerd Font Mono",
  "Hack Nerd Font Mono Regular",
  "Consolas",
})
config.font_size = 11.0
config.line_height = 1.0

----------------------------------------------------
-- Input & IME
----------------------------------------------------
config.use_ime = true
config.ime_preedit_rendering = "Builtin"

----------------------------------------------------
-- Window Background & Dark 2026 Palette
----------------------------------------------------
config.window_background_opacity = 0.85
config.macos_window_background_blur = 20
config.window_padding = {
  left = 8,
  right = 8,
  top = 6,
  bottom = 6,
}

config.window_background_gradient = {
  colors = { "#171c2a", "#0d1018" },
  orientation = "Vertical",
}

config.colors = {
  foreground = "#ffffff",
  background = "#171c2a",
  cursor_bg = "#ffd866",
  cursor_fg = "#171c2a",
  cursor_border = "#ffd866",
  selection_fg = "#ffffff",
  selection_bg = "#5332a0",
  ansi = {
    "#171c2a", -- black
    "#E35535", -- red
    "#52AB62", -- green
    "#ffd866", -- yellow
    "#00B3BD", -- blue
    "#e991e3", -- magenta
    "#78e8c6", -- cyan
    "#FFFFFF", -- white
  },
  brights = {
    "#5c6d74", -- bright black (muted slate)
    "#E35535", -- bright red
    "#52AB62", -- bright green
    "#ffd866", -- bright yellow
    "#00B3BD", -- bright blue
    "#e991e3", -- bright magenta
    "#78e8c6", -- bright cyan
    "#ffffff", -- bright white
  },
  tab_bar = {
    background = "#171c2a",
    inactive_tab_edge = "none",
  },
}

----------------------------------------------------
-- Tab Bar Customization (Dark 2026 Powerline)
----------------------------------------------------
config.show_tabs_in_tab_bar = true
config.window_frame = {
  inactive_titlebar_bg = "none",
  active_titlebar_bg = "none",
}

local SOLID_LEFT_ARROW = wezterm.nerdfonts.ple_lower_right_triangle
local SOLID_RIGHT_ARROW = wezterm.nerdfonts.ple_upper_left_triangle

wezterm.on("format-tab-title", function(tab, _tabs, _panes, _config, hover, max_width)
  local edge_background = "#171c2a"
  local background = hover and "#3a383a" or "#5c6d74"
  local foreground = "#FFFFFF"
  if tab.is_active then
    background = "#5332a0"
    foreground = "#ffd866"
  end
  local edge_foreground = background
  local title = "   " .. wezterm.truncate_right(tab.active_pane.title, math.max(1, max_width - 1)) .. "   "
  return {
    { Background = { Color = edge_background } },
    { Foreground = { Color = edge_foreground } },
    { Text = SOLID_LEFT_ARROW },
    { Background = { Color = background } },
    { Foreground = { Color = foreground } },
    { Text = title },
    { Background = { Color = edge_background } },
    { Foreground = { Color = edge_foreground } },
    { Text = SOLID_RIGHT_ARROW },
  }
end)

----------------------------------------------------
-- Modular Keybindings (Safe Load with Diagnostics)
----------------------------------------------------
local ok, keybinds = pcall(require, "keybinds")
if ok and type(keybinds) == "table" then
  config.leader = keybinds.leader or { key = "q", mods = "CTRL", timeout_milliseconds = 2000 }
  config.keys = keybinds.keys
  config.key_tables = keybinds.key_tables
else
  wezterm.log_warn("Optional keybinds module could not be loaded: " .. tostring(keybinds))
end

return config

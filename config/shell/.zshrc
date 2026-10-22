# ==============================================================================
# Zsh Configuration (~/.zshrc)
# Author: Youhei Yamada (@sun-flat-yamada)
# Target: WSL2 (Ubuntu 24.04+), Linux, macOS
# ==============================================================================

# Exit early if non-interactive
[[ $- != *i* ]] && return

# ------------------------------------------------------------------------------
# 1. XDG Base Directories & Core Environment
# ------------------------------------------------------------------------------
export XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$HOME/.cache}"
export XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
export XDG_STATE_HOME="${XDG_STATE_HOME:-$HOME/.local/state}"

export LANG="${LANG:-en_US.UTF-8}"
export EDITOR="code --wait"
export VISUAL="code --wait"
export STARSHIP_CONFIG="$XDG_CONFIG_HOME/starship.toml"

# Ensure ~/.local/bin and mise shims are in PATH
for _dir in "$HOME/.local/bin" "$XDG_DATA_HOME/mise/shims"; do
  if [[ -d "$_dir" ]]; then
    case ":$PATH:" in
      *":$_dir:"*) ;;
      *) export PATH="$_dir:$PATH" ;;
    esac
  fi
done
unset _dir

# ------------------------------------------------------------------------------
# 2. History & Secret-Leak Prevention (POSIX ERE Safe)
# ------------------------------------------------------------------------------
HISTFILE="${XDG_STATE_HOME}/zsh_history"
mkdir -p "$(dirname "$HISTFILE")" 2>/dev/null
HISTSIZE=50000
SAVEHIST=50000

setopt HIST_IGNORE_ALL_DUPS
setopt HIST_IGNORE_SPACE
setopt HIST_REDUCE_BLANKS
setopt SHARE_HISTORY
setopt EXTENDED_HISTORY
setopt AUTO_CD
setopt INTERACTIVE_COMMENTS

# Never record commands containing secret patterns or leading spaces
zshaddhistory() {
  emulate -L zsh
  setopt localoptions nocasematch
  local line="${1%%$'\n'}"
  if [[ "$line" == [[:space:]]* ]]; then
    return 1
  fi
  if [[ "$line" =~ '(api[_-]?key|secret|password|passwd|token|credential|bearer)[[:space:]]*[:=[:space:]]' ]] || \
     [[ "$line" =~ '(gh[pousr]_|github_pat_|sk-ant-|sk-(proj-|svcacct-)?|AIza|AKIA|ASIA|xox[baprs]-|hf_)[A-Za-z0-9_-]{10,}' ]]; then
    return 1
  fi
  return 0
}

# ------------------------------------------------------------------------------
# 3. Completion System (Cached once per day for <30ms startup)
# ------------------------------------------------------------------------------
autoload -Uz compinit
mkdir -p "$XDG_CACHE_HOME/zsh"
_zcompdump="$XDG_CACHE_HOME/zsh/zcompdump"
_zcompdump_stale=("$_zcompdump"(N.mh+24))
if [[ ! -f "$_zcompdump" || ${#_zcompdump_stale} -gt 0 ]]; then
  compinit -d "$_zcompdump"
else
  compinit -C -d "$_zcompdump"
fi
unset _zcompdump _zcompdump_stale

# ------------------------------------------------------------------------------
# 4. WSL2 Host Interop (Clipboard & Browser Bridge)
# ------------------------------------------------------------------------------
if grep -qi microsoft /proc/version 2>/dev/null; then
  export IS_WSL=1
  if command -v wslview >/dev/null 2>&1; then
    export BROWSER="wslview"
  elif command -v explorer.exe >/dev/null 2>&1; then
    export BROWSER="explorer.exe"
  fi
  if command -v clip.exe >/dev/null 2>&1; then
    alias pbcopy='clip.exe'
  fi
fi

# ------------------------------------------------------------------------------
# 5. Shared Aliases & Tool Initializations
# ------------------------------------------------------------------------------
[[ -f "$HOME/.aliases" ]] && source "$HOME/.aliases"

# mise (polyglot runtime manager)
if command -v mise >/dev/null 2>&1; then
  eval "$(mise activate zsh)"
fi

# zoxide (smart directory jumper)
if command -v zoxide >/dev/null 2>&1; then
  eval "$(zoxide init zsh)"
fi

# fzf keybindings
if command -v fzf >/dev/null 2>&1; then
  eval "$(fzf --zsh 2>/dev/null)" || true
fi

# Starship prompt (with clean fallback)
if command -v starship >/dev/null 2>&1; then
  eval "$(starship init zsh)"
else
  PROMPT='%F{cyan}%~%f %F{yellow}❯%f '
fi

# ------------------------------------------------------------------------------
# 6. Machine-Local Private Overrides (~/.zshrc.local)
# ------------------------------------------------------------------------------
[[ -f "$HOME/.zshrc.local" ]] && source "$HOME/.zshrc.local"

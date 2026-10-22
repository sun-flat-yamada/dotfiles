# ==============================================================================
# Bash Configuration (~/.bashrc)
# Author: Youhei Yamada (@sun-flat-yamada)
# Target: WSL2 (Ubuntu 24.04+), Linux, Git Bash
# ==============================================================================

case $- in
  *i*) ;;
  *) return ;;
esac

export XDG_CONFIG_HOME="${XDG_CONFIG_HOME:-$HOME/.config}"
export XDG_DATA_HOME="${XDG_DATA_HOME:-$HOME/.local/share}"
export EDITOR="code --wait"
export VISUAL="code --wait"
export STARSHIP_CONFIG="$XDG_CONFIG_HOME/starship.toml"

for _dir in "$HOME/.local/bin" "$XDG_DATA_HOME/mise/shims"; do
  if [[ -d "$_dir" ]]; then
    case ":$PATH:" in
      *":$_dir:"*) ;;
      *) export PATH="$_dir:$PATH" ;;
    esac
  fi
done
unset _dir

# History settings with secret protection (ignorespace + ignoredups, upper & lower case)
HISTCONTROL=ignoreboth:erasedups
HISTSIZE=50000
HISTFILESIZE=50000
HISTIGNORE=" *:*TOKEN*:*token*:*SECRET*:*secret*:*PASSWORD*:*password*:*API_KEY*:*api_key*:*ghp_*:*gho_*:*github_pat_*:*sk-ant-*:*sk-proj-*:*AIza*:*AKIA*"
shopt -s histappend
shopt -s checkwinsize

# WSL2 detection
if grep -qi microsoft /proc/version 2>/dev/null; then
  export IS_WSL=1
  if command -v clip.exe >/dev/null 2>&1; then
    alias pbcopy='clip.exe'
  fi
fi

# Load shared aliases
[[ -f "$HOME/.aliases" ]] && . "$HOME/.aliases"

# mise
if command -v mise >/dev/null 2>&1; then
  eval "$(mise activate bash)"
fi

# zoxide
if command -v zoxide >/dev/null 2>&1; then
  eval "$(zoxide init bash)"
fi

# Starship prompt
if command -v starship >/dev/null 2>&1; then
  eval "$(starship init bash)"
else
  PS1='\[\033[01;36m\]\w\[\033[00m\] \[\033[01;33m\]❯\[\033[00m\] '
fi

# Machine-local overrides
[[ -f "$HOME/.bashrc.local" ]] && . "$HOME/.bashrc.local"

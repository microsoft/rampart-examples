#!/usr/bin/env bash
# To be removed once RAMPART is public:
# https://github.com/microsoft/rampart-examples/issues/3

set -euo pipefail

: "${RAMPART_REPO_READER:?RAMPART_REPO_READER env var must be set}"

mkdir -p ~/.ssh
chmod 700 ~/.ssh

cat > ~/.ssh/rampart_deploy <<EOF
${RAMPART_REPO_READER}
EOF
chmod 600 ~/.ssh/rampart_deploy

ssh-keyscan -t ed25519,rsa github.com >> ~/.ssh/known_hosts 2>/dev/null
chmod 600 ~/.ssh/known_hosts

cat >> ~/.ssh/config <<'EOF'
Host github.com
  IdentityFile ~/.ssh/rampart_deploy
  IdentitiesOnly yes
EOF
chmod 600 ~/.ssh/config

git config --global url."git@github.com:".insteadOf "https://github.com/"

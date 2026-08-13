#!/usr/bin/env bash
# Sync a new source snapshot from 08-05/, retain production fixes, then deploy.
# Run from any directory: bash scripts/update-from-08-05.sh

set -Eeuo pipefail

repo_root=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
source_root=${SOURCE_ROOT:-"$repo_root/08-05"}
server=${DEPLOY_SERVER:-"root@31.58.152.104"}
commit_message=${COMMIT_MESSAGE:-"Merge updates from 08-05"}
temp_dir=
nested_git_moved=0

die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
note() { printf '\n==> %s\n' "$*"; }

restore_nested_git() {
  if [[ $nested_git_moved -eq 1 && -d "$temp_dir/backend-dot-git" ]]; then
    mv "$temp_dir/backend-dot-git" "$repo_root/backend/.git"
  fi
  [[ -n "$temp_dir" ]] && rmdir "$temp_dir" 2>/dev/null || true
}
trap restore_nested_git EXIT

cd "$repo_root"

[[ -d "$source_root/backend" && -d "$source_root/frontend" ]] || \
  die "source snapshot must contain backend/ and frontend/: $source_root"

[[ -z $(git status --porcelain) ]] || \
  die "working tree is not clean. Commit, stash, or resolve existing changes first."

git diff --quiet HEAD origin/main || die "local main differs from origin/main; run git pull --ff-only first."
for commit in 1314148 2b13d03; do
  git rev-parse --verify -q "$commit^{commit}" >/dev/null || die "required protection commit missing: $commit"
done

note "Creating a local rollback branch"
backup_branch="backup/pre-08-05-$(date +%Y%m%d%H%M%S)"
git branch "$backup_branch"

note "Syncing source snapshot from $source_root"
rsync -a \
  --exclude='.git' --exclude='.env' --exclude='.env.*' \
  --exclude='db.sqlite3' --exclude='__pycache__' --exclude='*.pyc' --exclude='.DS_Store' \
  "$source_root/backend/" backend/
rsync -a \
  --exclude='.git' --exclude='node_modules' --exclude='dist' \
  --exclude='.env' --exclude='.env.*' --exclude='.DS_Store' \
  "$source_root/frontend/" frontend/

# These deployment requirements must never be removed by a source snapshot.
note "Restoring production proxy and runtime safeguards"
python3 - <<'PY'
from pathlib import Path

settings = Path('backend/config/settings.py')
text = settings.read_text(encoding='utf-8')
proxy = "    SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')\n"
marker = '    SECURE_SSL_REDIRECT = True\n'
if proxy not in text:
    if marker not in text:
        raise SystemExit('SECURE_SSL_REDIRECT production block not found in backend/config/settings.py')
    text = text.replace(marker, proxy + marker, 1)
settings.write_text(text, encoding='utf-8')

requirements = Path('backend/requirements.txt')
lines = requirements.read_text(encoding='utf-8').splitlines()
for requirement in ('gunicorn>=23.0,<24.0', 'requests>=2.31,<3.0'):
    if requirement not in lines:
        lines.append(requirement)
requirements.write_text('\n'.join(lines) + '\n', encoding='utf-8')
PY

# backend is also an old standalone Git checkout; hide its metadata while staging
# the real files in this root repository.
temp_dir=$(mktemp -d)
if [[ -d backend/.git ]]; then
  mv backend/.git "$temp_dir/backend-dot-git"
  nested_git_moved=1
fi

note "Staging snapshot before three-way protection merges"
git add -A backend frontend

note "Applying referral-code and unique-device-ID protections"
git diff 1314148^ 1314148 > "$temp_dir/referral.patch"
git diff 2b13d03^ 2b13d03 > "$temp_dir/device-id.patch"
git apply --3way "$temp_dir/referral.patch" || true
git apply --3way "$temp_dir/device-id.patch" || true

if git diff --name-only --diff-filter=U | grep -q .; then
  printf '\nAutomatic merge stopped safely. Resolve these files, then rerun the checks and deployment commands manually:\n' >&2
  git diff --name-only --diff-filter=U >&2
  exit 2
fi

# If a source snapshot changed a protection too much for git-apply to restore,
# do not allow an incomplete deployment to be committed.
rg -q "SECURE_PROXY_SSL_HEADER = \('HTTP_X_FORWARDED_PROTO', 'https'\)" backend/config/settings.py || \
  die "HTTPS proxy safeguard was not retained"
grep -Fxq 'gunicorn>=23.0,<24.0' backend/requirements.txt || die "gunicorn requirement was not retained"
grep -Fxq 'requests>=2.31,<3.0' backend/requirements.txt || die "requests requirement was not retained"
rg -q 'referral_code' backend/platform_api/data_factory/account_add.py || die "referral-code safeguard was not retained"
rg -q 'uuid\.uuid5|x-device-id' backend/platform_api/data_factory/account_add.py || die "unique-device-ID safeguard was not retained"

note "Restoring nested backend Git metadata"
restore_nested_git
nested_git_moved=0
temp_dir=
trap - EXIT

note "Running checks"
python3 -m compileall -q backend/config backend/platform_api
(cd frontend && npx vue-tsc --noEmit)
git diff --check

note "Committing and pushing"
git add -A backend frontend
git commit -m "$commit_message"
git push origin main

note "Backing up and deploying on $server"
ssh "$server" 'bash -s' <<'REMOTE'
set -Eeuo pipefail
cd /opt/aibetauto
stamp=$(date +%Y%m%d%H%M%S)
backup="backups/pre-08-05-update-${stamp}.sql"
mkdir -p backups
docker compose exec -T db sh -c 'mysqldump -uroot -p"$MYSQL_ROOT_PASSWORD" --no-tablespaces "$MYSQL_DATABASE"' > "$backup"
test -s "$backup"
git pull --ff-only
docker compose up -d --build --force-recreate --no-deps backend frontend
docker compose exec -T backend python manage.py migrate
docker compose exec -T backend python manage.py check
docker compose ps
printf 'Database backup: %s\n' "$backup"
printf 'Deployed commit: '
git log -1 --oneline
REMOTE

note "Finished successfully"

#!/usr/bin/env bash
# sync-deploy.sh
# DART Trading → GitHub tenburger(main) → Cloud5 재배포
# 사용법: bash sync-deploy.sh
set -e

PROJECT_ROOT="/c/Users/j0708/Desktop/ten"
PEM="/c/Users/j0708/Desktop/cloud5-mvp/cloud5.pem"
REMOTE="ubuntu@3.38.40.170"
APP_DIR="/home/ubuntu/apps/tenburger/source"
GH_REPO="https://github.com/JessyLimitless/tenburger.git"

CONTAINER_NAME="cloud5-tenburger"
HOST_PORT=10003
APP_NAME="tenburger"

echo "=== [1/4] 로컬 커밋 확인 ==="
cd "$PROJECT_ROOT"
if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "⚠ uncommitted 변경이 있습니다. 먼저 git commit 후 실행하세요."
  git status --short
  exit 1
fi
echo "✓ 커밋 상태 정상"

echo ""
echo "=== [2/4] GitHub main 푸시 ==="
git push origin main
echo "✓ GitHub 푸시 완료"

echo ""
echo "=== [3/4] Cloud5 git pull ==="
ssh -i "$PEM" "$REMOTE" "
  mkdir -p $APP_DIR
  cd $APP_DIR
  if [ ! -d .git ]; then
    git clone $GH_REPO .
  else
    git fetch origin main
    git reset --hard origin/main
  fi
  echo '현재 파일:' && ls
"
echo "✓ git pull 완료"

echo ""
echo "=== [4/4] Cloud5 Docker 재빌드 & 실행 ==="
ssh -i "$PEM" "$REMOTE" "
  set -e

  # .env 파일 확인
  ENV_FILE=/home/ubuntu/apps/tenburger/.env
  if [ ! -f \$ENV_FILE ]; then
    echo '⚠ .env 파일이 없습니다. 생성합니다...'
    echo '# DART Trading 환경변수' > \$ENV_FILE
    echo 'KIWOOM_APP_KEY=YOUR_KEY_HERE' >> \$ENV_FILE
    echo 'KIWOOM_APP_SECRET=YOUR_SECRET_HERE' >> \$ENV_FILE
    echo '⚠ .env 파일을 수정해주세요: nano \$ENV_FILE'
  fi
  echo '✓ .env 파일 확인'

  docker stop $CONTAINER_NAME 2>/dev/null || true
  docker rm   $CONTAINER_NAME 2>/dev/null || true
  cd $APP_DIR
  docker build -t $CONTAINER_NAME . 2>&1 | tail -4
  docker run -d --name $CONTAINER_NAME --restart unless-stopped \
    -p $HOST_PORT:3000 \
    --env-file /home/ubuntu/apps/tenburger/.env \
    $CONTAINER_NAME
  NEW_ID=\$(docker ps --filter name=$CONTAINER_NAME --format '{{.ID}}')
  echo \"컨테이너: \$NEW_ID\"
  cd /home/ubuntu/cloud5-mvp
  node -e \"
    const db=require('better-sqlite3')('./data/cloud5.db');
    db.prepare('UPDATE deployments SET container_id=?,status=? WHERE app_name=?').run('\$NEW_ID','running','$APP_NAME');
    console.log('매니저 DB 업데이트 완료');
  \"
"
echo "✓ Docker 재배포 완료"

echo ""
echo "=== 헬스체크 ==="
sleep 5
curl -s https://tenburger.cloud5.socialbrain.co.kr/ | head -c 80
echo ""
echo "=== ✓ DART Trading 재배포 완료 ==="

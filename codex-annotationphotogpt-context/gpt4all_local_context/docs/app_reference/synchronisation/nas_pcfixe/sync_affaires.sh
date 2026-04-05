#!/bin/sh
set -eu

export HOME=/volume1/home/nicolas
export USER=nicolas
export PATH=/usr/local/sbin:/usr/local/bin:/sbin:/bin:/usr/sbin:/usr/bin


# Journal mensuel + rotation (sans dépendances)*
LOG_DIR="/volume1/Web/logs"
mkdir -p "$LOG_DIR" 2>/dev/null || true

LOG_FILE="$LOG_DIR/sync_affaires.$(date '+%Y-%m').log"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

log "RUN_AS=$(whoami) UID=$(id -u) HOME=$HOME"
echo "RUN_AS=$(whoami) UID=$(id -u) HOME=$HOME" >> "$LOG_FILE"

# Purge des logs sync > 90 jours (1 fois par exécution, léger)
find "$LOG_DIR" -maxdepth 1 -type f -name 'sync_affaires.*.log' -mtime +90 -delete 2>/dev/null || true

# Option A — si sendmail est disponible
SMTP_ENV="/volume1/Web/secrets/smtp_lws.env"

if [ -r "$SMTP_ENV" ]; then
  . "$SMTP_ENV"
else
  log "WARN: fichier SMTP_ENV absent ou illisible → alertes mail désactivées ($SMTP_ENV)"
fi

alert_mail() {
  [ -z "${SMTP_HOST:-}" ] && return 0

  : "${SMTP_PORT:=587}"
  : "${MAIL_FROM:=no-reply@ntu-consult.com}"
  : "${MAIL_TO:=nicolas.turcry@outlook.com}"
  : "${RUN_TMP:=/tmp}"   # fallback sûr si RUN_TMP pas encore créé

  subject="$1"
  body="$2"

  tmp="$RUN_TMP/sync_affaires_mail.$$.$(date +%s).eml"
  err="$RUN_TMP/smtp_err.$$"

  cat >"$tmp" <<EOF
From: $MAIL_FROM
To: $MAIL_TO
Subject: $subject

$body
EOF

  log "DEBUG SMTP: host='${SMTP_HOST:-}' port='${SMTP_PORT:-}' user='${SMTP_USER:-}' from='${MAIL_FROM:-}' to='${MAIL_TO:-}' env='$SMTP_ENV'"

  if ! curl --silent --show-error --fail --ssl-reqd \
    --url "smtp://${SMTP_HOST}:${SMTP_PORT}" \
    --mail-from "$MAIL_FROM" \
    --mail-rcpt "$MAIL_TO" \
    --upload-file "$tmp" \
    --user "${SMTP_USER}:${SMTP_PASS}" \
    >"$err" 2>&1
    log "INFO: alerte mail envoyée à $MAIL_TO"
  then
    log "WARN: échec envoi mail: $(tail -n 1 "$err" 2>/dev/null || true)"
  fi

  rm -f "$tmp" "$err" 2>/dev/null || true
}

# Option B — si pas de mail local : simple “flag d’échec”

FAIL_FLAG="$LOG_DIR/sync_affaires.FAIL"

fail() {
  msg="$1"
  log "ERREUR: $msg"
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $msg (log: $LOG_FILE)" > "$FAIL_FLAG"
  exit 1
}


START_TS=$(date +%s)
# ------------------------------------------------

PC_HOST="10.0.1.10"
PC_PORT="2222"
PC_USER="sshsync"
SSH_KEY="/volume1/home/nicolas/.ssh/id_ed25519"

SRC_NAS="/volume1/Affaires/"
DST_PC="/c/Affaires/"
SSH_OPTS="-p ${PC_PORT} -i ${SSH_KEY} \
  -o BatchMode=yes \
  -o PasswordAuthentication=no \
  -o KbdInteractiveAuthentication=no \
  -o UserKnownHostsFile=/volume1/home/nicolas/.ssh/known_hosts \
  -o StrictHostKeyChecking=accept-new"



RSYNC_REMOTE="C:\\msys64\\usr\\bin\\rsync.exe"

COMMON_OPTS="--old-args -avz --info=progress2 --partial --update --chmod=Du=rwx,Dgo=rx,Fu=rw,Fgo=r"

# --- Filtres ---
TMP_DIR="/volume1/Web/tmp"
RUN_TMP="$TMP_DIR/sync_affaires.$$.$(date +%s)"
mkdir -p "$RUN_TMP"
trap 'rm -rf "$RUN_TMP" 2>/dev/null || true' EXIT


FILTER_A_FILE="$RUN_TMP/rsync_filter_A.rules"
FILTER_B_FILE="$RUN_TMP/rsync_filter_B.rules"

# Type A : 00_,01_,02_... + contenu
cat >"$FILTER_A_FILE" <<'EOF'
+ */
+ **/BE_*/
+ **/BE_*/**
+ **/[0-9][0-9]_*/
+ **/[0-9][0-9]_*/**
- **/_DB/***
- **/_Config/***
- **/[A-Z][A-Z]_*/***
- **
EOF
# Type B : AA_,AB_,AC_... + contenu
cat >"$FILTER_B_FILE" <<'EOF'
+ */
+ **/BE_*/
+ **/BE_*/**
+ **/[A-Z][A-Z]_*/
+ **/[A-Z][A-Z]_*/**
- **/_DB/***
- **/_Config/***
- **/[0-9][0-9]_*/***
- **
EOF

log "Début synchronisation NAS ↔ PC"

# 1) NAS -> PC (type A)

direction="NAS → PC (type A)"
OUTPUT=$(rsync ${COMMON_OPTS} --filter="merge $FILTER_A_FILE" \
  -e "ssh ${SSH_OPTS}" \
  --rsync-path="${RSYNC_REMOTE}" \
  "${SRC_NAS}" \
  "${PC_USER}@${PC_HOST}:${DST_PC}" 2>&1) || {
    log "ERREUR ${direction}"
    log "$OUTPUT"
    alert_mail "NAS sync_affaires: ECHEC" \
"Erreur lors de ${direction}

Log:
$OUTPUT


Fichier log: $LOG_FILE"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ${direction} (log: $LOG_FILE)" > "$FAIL_FLAG"
    exit 1
}
log "OK ${direction}"


# 2) PC -> NAS (type B)
direction="PC → NAS (type B)"
OUTPUT=$(rsync ${COMMON_OPTS} --filter="merge $FILTER_B_FILE" \
  -e "ssh ${SSH_OPTS}" \
  --rsync-path="${RSYNC_REMOTE}" \
  "${PC_USER}@${PC_HOST}:${DST_PC}" \
  "${SRC_NAS}" 2>&1) || {
    log "ERREUR ${direction}"
    log "$OUTPUT"
    alert_mail "NAS sync_affaires: ECHEC" \
"Erreur lors de ${direction}

Log:
$OUTPUT


Fichier log: $LOG_FILE"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ${direction} (log: $LOG_FILE)" > "$FAIL_FLAG"
    
    exit 1
}
log "OK ${direction}"



# fin

rm -f "$FAIL_FLAG" 2>/dev/null || true

log "Synchronisation terminée avec succès (durée: $(( $(date +%s) - START_TS ))s)"

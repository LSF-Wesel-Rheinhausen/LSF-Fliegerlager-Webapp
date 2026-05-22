#!/usr/bin/env bash
set -uo pipefail

if [[ "${CI:-}" == "true" ]]; then
  printf 'Dieses Script ist nur fuer lokale manuelle Tests gedacht und in CI/CD deaktiviert.\n'
  exit 2
fi

declare -a STEPS=(
  "Django check|.venv/bin/python src/manage.py check"
  "Python tests|.venv/bin/python -m pytest"
  "E2E (Playwright)|npm run test:e2e"
)

declare -a RESULTS=()
overall=0
pass_count=0
fail_count=0
run_timestamp="$(date +%Y%m%d-%H%M%S)"
log_dir=".test-local-logs/${run_timestamp}"

mkdir -p "${log_dir}"

print_line() {
  printf '%s\n' "----------------------------------------------------------------------------------------------------------"
}

print_header() {
  print_line
  printf '%-18s | %-7s | %-8s | %-30s | %s\n' "Schritt" "Status" "Dauer" "Befehl" "Log"
  print_line
}

run_step() {
  local label="$1"
  local command="$2"
  local logfile safe_label start end duration status

  safe_label="$(printf '%s' "${label}" | tr '[:upper:]' '[:lower:]' | tr ' ' '-' | tr -cd 'a-z0-9-_')"
  logfile="${log_dir}/${safe_label}.log"
  start="$(date +%s)"
  if bash -lc "${command}" >"${logfile}" 2>&1; then
    status="PASS"
    pass_count="$((pass_count + 1))"
  else
    status="FAIL"
    overall=1
    fail_count="$((fail_count + 1))"
  fi
  end="$(date +%s)"
  duration="$((end - start))s"
  RESULTS+=("${label}|${status}|${duration}|${command}|${logfile}")
  printf '    %s (%s)\n' "${status}" "${duration}"
  if [[ "${status}" == "FAIL" ]]; then
    printf '    Letzte 30 Log-Zeilen (%s):\n' "${logfile}"
    tail -n 30 "${logfile}"
  fi
}

for step in "${STEPS[@]}"; do
  IFS='|' read -r label command <<<"${step}"
  printf '\n==> %s\n' "${label}"
  run_step "${label}" "${command}"
done

printf '\n'
print_header
for result in "${RESULTS[@]}"; do
  IFS='|' read -r label status duration command logfile <<<"${result}"
  printf '%-18s | %-7s | %-8s | %-30s | %s\n' "${label}" "${status}" "${duration}" "${command}" "${logfile}"
done
print_line
printf 'Bestanden: %s | Fehlgeschlagen: %s | Logs: %s\n' "${pass_count}" "${fail_count}" "${log_dir}"

if [[ "${overall}" -eq 0 ]]; then
  printf 'Gesamt: PASS\n'
else
  printf 'Gesamt: FAIL\n'
fi

exit "${overall}"

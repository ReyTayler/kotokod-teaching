#!/bin/bash
# Установка Ansible на сервер журнала — первая команда на новом VPS.
#
# Ansible ставится в отдельное окружение /opt/ansible, а не пакетом Ubuntu:
# в 22.04 пакет ansible — версия 2.10 (2021 г.). Версия ядра закреплена:
# 2.17.x — последняя ветка, работающая на системном Python 3.10 Ubuntu 22.04
# (2.18+ требуют 3.11+). Поддержка ветки 2.17 закончилась; это приемлемо —
# Ansible не сервис и не смотрит в сеть, а при переезде на Ubuntu 24.04
# (Python 3.12) поднять версию — правка одной строки ниже.
#
# Повторный запуск безопасен: доустанавливает недостающее, лишнего не делает.
#
# Запуск (root): bash deploy/scripts/bootstrap-ansible.sh

set -euo pipefail

ANSIBLE_CORE_VERSION="2.17.14"
VENV=/opt/ansible
REQUIREMENTS="$(dirname "$(readlink -f "$0")")/../ansible/requirements.yml"

# Зависимости самого Ansible, а не журнала, — поэтому здесь, а не в ролях:
#   python3-venv     — без него не создать окружение, где Ansible запустится;
#   python3-psycopg2 — через него модули community.postgresql ходят в базу
#                      (модули выполняются системным Python 3.10);
#   acl              — Ansible переключается с root на непривилегированного
#                      пользователя (postgres) и через ACL даёт ему прочитать
#                      свои временные файлы; без пакета такие задачи падают.
PKGS=""
for p in python3-venv python3-psycopg2 acl; do
    dpkg -s "$p" >/dev/null 2>&1 || PKGS="$PKGS $p"
done
if [ -n "$PKGS" ]; then
    apt-get update -q
    DEBIAN_FRONTEND=noninteractive apt-get install -y -q $PKGS
fi

if [ ! -x "$VENV/bin/python" ]; then
    /usr/bin/python3 -m venv "$VENV"
fi

"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q "ansible-core==$ANSIBLE_CORE_VERSION"

"$VENV/bin/ansible-galaxy" collection install -r "$REQUIREMENTS" -p "$VENV/collections"

"$VENV/bin/ansible" --version | head -1

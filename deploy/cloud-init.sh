#!/bin/bash
# Droplet bootstrap (DigitalOcean user-data). Use the "Docker on Ubuntu" marketplace image
# (docker-20-04) so Docker + compose are preinstalled; this just fetches the code. Secrets
# are NOT placed here — they're delivered over SSH afterward, so they never sit in droplet
# metadata. Replace BRANCH at render time (deploy script does this).
set -eux
git clone --branch BRANCH https://github.com/Yugandhar-G/yunaki-skills.git /root/app
touch /root/cloud-init-done

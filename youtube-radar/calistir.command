#!/bin/bash
cd "$(dirname "$0")"
echo "YouTube Niş Radarı başlatılıyor..."
read -p "Konu (boş bırakırsan genel tarama): " KONU
if [ -z "$KONU" ]; then python3 radar.py; else python3 radar.py --konu "$KONU"; fi
echo
read -p "Kapatmak için Enter'a bas..."

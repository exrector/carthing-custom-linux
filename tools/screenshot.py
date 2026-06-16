#!/usr/bin/env python3
"""Скриншот с Car Thing через рендеринг в PIL."""

import sys
import os

# На устройстве
DEVICE_PATH = '/usr/lib/carthing'

if len(sys.argv) < 2:
    print("Usage: python3 screenshot.py <output.png>")
    sys.exit(1)

output_path = sys.argv[1]

# Добавить путь к GUI модулям
sys.path.insert(0, DEVICE_PATH)

from PIL import Image

# Импорты из GUI
import screens as Screens
import ui_theme as T

# Создать пустое изображение (480x800, портрет)
img = Image.new('RGB', (480, 800), T.BG)

# Попытка создать экран и рендернуть
screen = Screens.NowPlayingScreen()
img = screen.render()

# Сохранить
img.save(output_path)
print(f'Screenshot saved to {output_path}')

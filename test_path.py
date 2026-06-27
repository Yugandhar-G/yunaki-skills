#!/usr/bin/env python3
from pathlib import Path
p = Path('/Users/yugandhargopu/yunaki-skills/src/yunaki_skills/config.py').resolve().parent.parent.parent.parent / '.env'
print(f'Config looks for .env at: {p}')
print(f'Exists: {p.exists()}')

# Correct path should be:
correct = Path('/Users/yugandhargopu/yunaki-skills/.env')
print(f'Correct .env path: {correct}')
print(f'Correct exists: {correct.exists()}')

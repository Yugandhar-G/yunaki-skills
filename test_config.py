#!/usr/bin/env python3
from yunaki_skills.config import get
uri = get('MONGODB_URI')
print(f"URI length: {len(uri)}")
print(f"URI prefix: {uri[:30]}...")

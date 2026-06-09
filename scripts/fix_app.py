"""Remove orphaned SkyTonight routes from app.py."""
filepath = 'd:/Code/myastroboard/backend/app.py'

with open(filepath, encoding='utf-8') as f:
    content = f.read()

# The orphaned block: starts with the empty weather route + skytonight routes
# and ends just before the real '# API Weather' section
ORPHAN_START = "@app.route('/api/weather/forecast', methods=['GET'])\n\n\n@app.route('/api/skytonight/scheduler/trigger'"
REAL_WEATHER = "\n\n# ============================================================\n# API Weather\n# ============================================================\n\n@app.route('/api/weather/forecast', methods=['GET'])\n@login_required\ndef get_hourly_forecast_api():"

pos_orphan = content.find(ORPHAN_START)
pos_real = content.find(REAL_WEATHER)

print(f"Orphan start pos: {pos_orphan}")
print(f"Real weather pos: {pos_real}")

if pos_orphan == -1:
    print("ERROR: orphan start not found")
elif pos_real == -1:
    print("ERROR: real weather section not found")
else:
    # Remove from orphan start up to (but not including) the real weather section
    new_content = content[:pos_orphan] + content[pos_real:]
    
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(new_content)
    print(f"Removed {pos_real - pos_orphan} bytes of orphaned SkyTonight routes")
    print("Done!")

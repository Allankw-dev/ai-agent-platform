# Usage (from the repo root, with the stack running):
#   .\scripts\check-gemini-models.ps1
#
# Asks Gemini which models your key can use, then sends each of the first few flash models a tiny
# request and prints how fast it answered. Use the result to pick an agent's model: free-tier
# models are sometimes overloaded (HTTP 503) or slow, and a model that works for one key may not
# exist for another. Runs inside the worker container so it uses the same key and network as runs.
$ErrorActionPreference = "Stop"

$script = @'
import os, time, httpx
key = os.environ["GEMINI_API_KEY"]
H = {"x-goog-api-key": key}
base = "https://generativelanguage.googleapis.com/v1beta"
found = httpx.get(f"{base}/models?pageSize=200", headers=H, timeout=30).json().get("models", [])
skip = ("image", "tts", "live", "audio", "embedding", "robotics", "computer", "exp")
names = [m["name"].removeprefix("models/") for m in found
         if "generateContent" in m.get("supportedGenerationMethods", [])
         and "flash" in m["name"] and not any(s in m["name"] for s in skip)]
print("flash models your key can use:", len(names))
for name in names[:8]:
    t = time.time()
    try:
        r = httpx.post(f"{base}/models/{name}:generateContent", headers=H, timeout=20,
                       json={"contents": [{"role": "user", "parts": [{"text": "Say hi in three words."}]}]})
        print(f"{name:45} HTTP {r.status_code}  {time.time() - t:4.1f}s")
    except Exception as e:
        print(f"{name:45} {type(e).__name__}  {time.time() - t:4.1f}s")
'@

$script | docker compose exec -T worker python -

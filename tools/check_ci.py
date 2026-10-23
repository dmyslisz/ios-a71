import urllib.request, json

url = 'https://api.github.com/repos/dmyslisz/ios-a71/actions/runs?per_page=5'
req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
try:
    with urllib.request.urlopen(req) as resp:
        data = json.loads(resp.read().decode())
        for run in data.get('workflow_runs', []):
            msg = run['head_commit']['message'].splitlines()[0] if run.get('head_commit') else ''
            print(f"Run {run['id']}: status={run['status']}, conclusion={run['conclusion']}, name={run['name']}, commit='{msg}'")
except Exception as e:
    print('Error:', e)

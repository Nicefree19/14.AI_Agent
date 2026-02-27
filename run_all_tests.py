import subprocess, sys
r = subprocess.run(
    [sys.executable, '-m', 'pytest', 'tests/', '-v', '--tb=short'],
    capture_output=True, text=True,
    cwd=r'D:\00.Work_AI_Tool\14.AI_Agent'
)
with open(r'D:\00.Work_AI_Tool\14.AI_Agent\all_tests_output.txt', 'w', encoding='utf-8') as f:
    f.write(f'RC={r.returncode}\n---STDOUT---\n{r.stdout}\n---STDERR---\n{r.stderr}')

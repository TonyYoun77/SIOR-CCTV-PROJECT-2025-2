import subprocess

# recording.py / analysis.py / checker.py 세 파이썬 파일 동시 실행

files = ['recording.py' , 'analysis.py', 'checker.py']
processes = []

for f in files:
	p = subprocess.Popen(['python',f])
	processes.append(p)

for p in processes:
	p.wait()

```
# Clone the exercism repo
git clone git@github.com:exercism/python.git

pip install -r requirements.txt

python benchmark.py -model="gpt-4o" -task="python/exercises/practice" -threads=3 -output="../reports"
```
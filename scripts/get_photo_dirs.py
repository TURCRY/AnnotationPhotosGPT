import sys
from pathlib import Path
import pandas as pd

photos_csv = Path(sys.argv[1])
df = pd.read_csv(photos_csv, sep=";", encoding="utf-8-sig")

native = str(df.loc[0, "chemin_photo_native"]).strip().replace('"', "")
reduite = str(df.loc[0, "chemin_photo_reduite"]).strip().replace('"', "")

print(native)
print(reduite)

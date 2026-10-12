import sys
from pathlib import Path

# Permite `import config`, `import agents...` desde la raíz del repo.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

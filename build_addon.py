import os
import zipfile

def build_addon():
    base = os.path.dirname(os.path.abspath(__file__))
    source = os.path.join(base, 'addon')
    output = os.path.join(base, 'neurovox.nvda-addon')

    with zipfile.ZipFile(output, 'w', zipfile.ZIP_DEFLATED) as zipf:
        for root, dirs, files in os.walk(source):
            for file in files:
                file_path = os.path.join(root, file)
                arcname = os.path.relpath(file_path, source)
                zipf.write(file_path, arcname)

if __name__ == "__main__":
    build_addon()
